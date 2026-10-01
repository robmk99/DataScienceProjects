#!/usr/bin/env python3
"""
Download and replay full L2 order books for the competitor execution cases.

Free, no account needed:
  Bybit  quote-saver.bycsi.com  orderbook.200 websocket dump, 200 levels/side, 100 ms
  OKX    static.okx.com CDN     L2 400 or 5000 levels, 15-min snapshots + ~10 ms deltas

The raw dumps are large (a few hundred MB per symbol-day), so each file is streamed,
replayed into a book, reduced to a per-update row (touch, depth at several bps bands,
level counts) over the case window only, then written as parquet and deleted.

Usage:
  python3 fetch_orderbook.py --manifest manifest.csv --out ../data/book --cases 1,2,3,5
  python3 fetch_orderbook.py --manifest manifest.csv --out ../data/book --check
"""
import argparse, io, json, zipfile, tarfile, sys, shutil, urllib.request, urllib.error
from pathlib import Path
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (research)"}
BANDS_BPS = [1, 2, 5, 10, 25]          # cumulative depth within N bps of the touch
BYBIT = "https://quote-saver.bycsi.com/orderbook/{cat}/{sym}/{d}_{sym}_ob200.data.zip"
OKX = ("https://static.okx.com/cdn/okx/match/orderbook/pro/L2/{lv}/daily/{dcompact}/"
       "{inst}-L2orderbook-{lv}-{d}.tar.gz")

def bybit_symbol(pair): return pair.replace(".PERP", "").replace("-", "")
def okx_inst(pair): return pair.replace(".PERP", "-SWAP") if pair.endswith(".PERP") else pair

def head_ok(url):
    try:
        req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-100"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status in (200, 206)
    except urllib.error.HTTPError:
        return False
    except Exception:
        return False

def download(url, dest):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=1800) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f, length=1 << 20)
    return dest

def reduce_book(bids, asks, ts, out):
    """Touch plus cumulative size within each bps band. Called only at sample points,
    because walking 400 levels on every 100 ms update would dominate the runtime."""
    if not bids or not asks:
        return
    bb = max(bids); ba = min(asks)
    if bb >= ba:
        return
    mid = (bb + ba) / 2
    row = {"ts": ts, "bid": bb, "ask": ba, "bid_sz": bids[bb], "ask_sz": asks[ba],
           "n_bid": len(bids), "n_ask": len(asks)}
    for b in BANDS_BPS:
        lo = mid * (1 - b / 1e4); hi = mid * (1 + b / 1e4)
        row[f"bid_d{b}"] = sum(s for p, s in bids.items() if p >= lo)
        row[f"ask_d{b}"] = sum(s for p, s in asks.items() if p <= hi)
    out.append(row)

def replay_bybit(path, start, end, step_ms=250, marks=frozenset()):
    """orderbook.200 dump: snapshot sets the book, delta mutates it; size 0 removes."""
    bids, asks, out = {}, {}, []
    s_ms, e_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    next_sample = s_ms
    with zipfile.ZipFile(path) as z:
        name = z.namelist()[0]
        with z.open(name) as fh:
            for line in io.TextIOWrapper(fh, encoding="utf-8"):
                if not line.strip():
                    continue
                try: m = json.loads(line)
                except Exception: continue
                ts = m.get("ts")
                if ts is None or ts >= e_ms:
                    if ts is not None and ts >= e_ms: break
                    continue
                d = m.get("data", {})
                if m.get("type") == "snapshot":
                    bids = {float(p): float(s) for p, s in d.get("b", []) if float(s) > 0}
                    asks = {float(p): float(s) for p, s in d.get("a", []) if float(s) > 0}
                else:
                    for p, s in d.get("b", []):
                        p, s = float(p), float(s)
                        bids.pop(p, None) if s == 0 else bids.__setitem__(p, s)
                    for p, s in d.get("a", []):
                        p, s = float(p), float(s)
                        asks.pop(p, None) if s == 0 else asks.__setitem__(p, s)
                if ts >= s_ms and (ts >= next_sample or ts in marks):
                    reduce_book(bids, asks, ts, out)
                    while next_sample <= ts:
                        next_sample += step_ms
    return pd.DataFrame(out)

def replay_okx(path, start, end, step_ms=250, marks=frozenset()):
    """OKX L2: one flat JSON object per line,
       {"instId":..,"action":"snapshot"|"update","ts":"<ms>","asks":[[px,sz,n_orders]],"bids":[..]}
       Sizes are in contracts, so multiply by the instrument's ctVal for base units."""
    bids, asks, out = {}, {}, []
    s_ms, e_ms = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    next_sample = s_ms
    with tarfile.open(path, "r:gz") as tf:
        for member in tf:
            if not member.isfile():
                continue
            fh = tf.extractfile(member)
            if fh is None:
                continue
            for line in io.TextIOWrapper(fh, encoding="utf-8"):
                if not line.strip():
                    continue
                try: m = json.loads(line)
                except Exception: continue
                ts = m.get("ts")
                if ts is None:
                    continue
                ts = int(ts)
                if ts >= e_ms:
                    return pd.DataFrame(out)
                if m.get("action") == "snapshot":
                    bids = {float(l[0]): float(l[1]) for l in m.get("bids", []) if float(l[1]) > 0}
                    asks = {float(l[0]): float(l[1]) for l in m.get("asks", []) if float(l[1]) > 0}
                else:
                    for l in m.get("bids", []):
                        p, sz = float(l[0]), float(l[1])
                        bids.pop(p, None) if sz == 0 else bids.__setitem__(p, sz)
                    for l in m.get("asks", []):
                        p, sz = float(l[0]), float(l[1])
                        asks.pop(p, None) if sz == 0 else asks.__setitem__(p, sz)
                if ts >= s_ms and (ts >= next_sample or ts in marks):
                    reduce_book(bids, asks, ts, out)
                    while next_sample <= ts:
                        next_sample += step_ms
    return pd.DataFrame(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default="")
    ap.add_argument("--check", action="store_true", help="only report which files exist")
    ap.add_argument("--tmp", default="/tmp/obraw")
    ap.add_argument("--step-ms", type=int, default=250,
                    help="book sampling grid; the competitor's own event times are always sampled")
    ap.add_argument("--marks", default="",
                    help="directory of competitor case CSVs, to sample the book at their event times")
    a = ap.parse_args()

    m = pd.read_csv(a.manifest, parse_dates=["start", "end"])
    if a.cases:
        m = m[m.case.astype(str).isin({c.strip() for c in a.cases.split(",")})]
    m = m[m.exchange.isin(["bybit", "okex"])]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    tmp = Path(a.tmp); tmp.mkdir(parents=True, exist_ok=True)

    for _, r in m.iterrows():
        start = r.start.tz_localize("UTC"); end = r.end.tz_localize("UTC")
        tag = f"case{r.case}_{r.exchange}_{r.pair}"
        dest = out / f"{tag}_book.parquet"
        if dest.exists():
            print(f"[have] {dest.name}"); continue
        # Both venues cut their ORDER BOOK files at 00:00 UTC. Note this differs from
        # OKX's trade files, which are cut at 16:00 UTC - see fetch_market_data.py.
        days = pd.date_range(start.floor("D"),
                             (end - pd.Timedelta(seconds=1)).floor("D"), freq="D")
        marks = frozenset()
        if a.marks:
            import glob as _g
            cfs = _g.glob(f"{a.marks}/{r.case}/*.csv")
            if cfs:
                cdf = pd.read_csv(cfs[0])
                tt = pd.concat([pd.to_datetime(cdf.created_at), pd.to_datetime(cdf.finished_at)])
                marks = frozenset((tt.astype("int64") // 10**6).tolist())
        frames = []
        for day in days:
            d = day.strftime("%Y-%m-%d")
            if r.exchange == "bybit":
                cat = "linear" if r.pair.endswith(".PERP") else "spot"
                url = BYBIT.format(cat=cat, sym=bybit_symbol(r.pair), d=d)
            else:
                url = OKX.format(lv="400lv", dcompact=day.strftime("%Y%m%d"),
                                 inst=okx_inst(r.pair), d=d)
            if a.check:
                print(f"{'OK ' if head_ok(url) else 'MISS'} {tag} {d}"); continue
            raw = tmp / Path(url).name
            try:
                print(f"  downloading {tag} {d}", flush=True)
                download(url, raw)
                print(f"  replaying {raw.stat().st_size//1024//1024} MiB", flush=True)
                fn = replay_bybit if r.exchange == "bybit" else replay_okx
                df = fn(raw, start, end, step_ms=a.step_ms, marks=marks)
                frames.append(df)
                print(f"  {tag} {d}: {len(df)} book updates", flush=True)
            except urllib.error.HTTPError as e:
                print(f"  [HTTP {e.code}] {tag} {d}")
            except Exception as e:
                print(f"  [ERR] {tag} {d}: {type(e).__name__} {e}")
            finally:
                raw.unlink(missing_ok=True)
        frames = [f for f in frames if len(f)]
        if a.check or not frames:
            print(f"[empty] {tag}" if not a.check else "", end="")
            continue
        df = pd.concat(frames).drop_duplicates("ts").sort_values("ts")
        df["ts"] = pd.to_datetime(df.ts, unit="ms", utc=True)
        df.to_parquet(dest, index=False)
        print(f"[ok] {dest.name}: {len(df)} rows, {dest.stat().st_size//1024} KiB", flush=True)

if __name__ == "__main__":
    main()
