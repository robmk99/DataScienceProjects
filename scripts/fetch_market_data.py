#!/usr/bin/env python3
"""
Download free exchange market data for the 15 competitor execution cases.

Covers the venues that publish free historical data without an account:
  Bybit   linear perps + spot  -> tick trades
  OKX     swaps + spot         -> tick trades
  Binance USD-M futures        -> aggTrades (+ coarse bookDepth)
Hyperliquid needs a requester-pays S3 account and is handled by fetch_hyperliquid.py.

Each file is trimmed to the case's hour window straight after download and stored
as parquet; the raw archive is deleted, so peak disk stays small.

Usage:
  python3 fetch_market_data.py --manifest manifest.csv --out data/
  python3 fetch_market_data.py --manifest manifest.csv --out data/ --cases 1,2,3
  python3 fetch_market_data.py --manifest manifest.csv --out data/ --dry-run
"""
import argparse, io, gzip, zipfile, sys, os, shutil
from pathlib import Path
import urllib.request, urllib.error
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (research)"}
TIMEOUT = 300

# currency_pair in the competitor log -> venue-native symbol
def bybit_symbol(pair):
    # ETH-USDT -> ETHUSDT (spot), VVV-USDT.PERP -> VVVUSDT (linear)
    return pair.replace(".PERP", "").replace("-", "")

def okx_symbol(pair):
    # ZEC-USDT.PERP -> ZEC-USDT-SWAP ; ETH-USDT -> ETH-USDT
    return pair.replace(".PERP", "-SWAP") if pair.endswith(".PERP") else pair

def binance_symbol(pair):
    return pair.replace(".PERP", "").replace("-", "")

def http_get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()

def trim(df, tcol, start, end, unit=None):
    t = pd.to_datetime(df[tcol], unit=unit, utc=True) if unit else pd.to_datetime(df[tcol], utc=True)
    df = df.assign(ts=t)
    return df[(df.ts >= start) & (df.ts < end)].copy()

def fetch_bybit(pair, day, start, end, is_spot):
    sym = bybit_symbol(pair)
    d = day.strftime("%Y-%m-%d")
    url = (f"https://public.bybit.com/spot/{sym}/{sym}_{d}.csv.gz" if is_spot
           else f"https://public.bybit.com/trading/{sym}/{sym}{d}.csv.gz")
    raw = http_get(url)
    df = pd.read_csv(io.BytesIO(gzip.decompress(raw)))
    # linear: timestamp = epoch seconds float; spot: timestamp = epoch ms int
    tc = "timestamp"
    if is_spot:
        out = trim(df, tc, start, end, unit="ms")
    else:
        out = trim(df, tc, start, end, unit="s")
    return out, url

def fetch_okx(pair, day, start, end):
    inst = okx_symbol(pair)
    url = (f"https://static.okx.com/cdn/okex/traderecords/trades/daily/"
           f"{day.strftime('%Y%m%d')}/{inst}-trades-{day.strftime('%Y-%m-%d')}.zip")
    raw = http_get(url)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            df = pd.read_csv(f)
    return trim(df, "created_time", start, end, unit="ms"), url

def fetch_binance(pair, day, start, end, kind="aggTrades"):
    sym = binance_symbol(pair)
    d = day.strftime("%Y-%m-%d")
    url = f"https://data.binance.vision/data/futures/um/daily/{kind}/{sym}/{sym}-{kind}-{d}.zip"
    raw = http_get(url)
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        name = z.namelist()[0]
        with z.open(name) as f:
            first = f.readline().decode()
        hdr = 0 if not first[0].isdigit() else None
        with z.open(name) as f:
            df = pd.read_csv(f, header=hdr)
    if kind == "aggTrades":
        if df.columns[0] != "agg_trade_id":
            df.columns = ["agg_trade_id","price","quantity","first_trade_id","last_trade_id",
                          "transact_time","is_buyer_maker"][:len(df.columns)]
        tc = "transact_time"
        unit = "us" if df[tc].max() > 2e15 else "ms"
        return trim(df, tc, start, end, unit=unit), url
    else:  # bookDepth
        return trim(df, "timestamp", start, end), url

VENUE = {
    "bybit": "trades", "okex": "trades", "binancefutures": "trades",
    "hyperliquid": "SKIP-s3", "bitget": "none", "lighter": "none", "asterperps": "none",
}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--bookdepth", action="store_true", help="also pull Binance bookDepth")
    a = ap.parse_args()

    m = pd.read_csv(a.manifest, parse_dates=["start", "end"])
    if a.cases:
        keep = {c.strip() for c in a.cases.split(",")}
        m = m[m.case.astype(str).isin(keep)]
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    log = []
    for _, r in m.iterrows():
        start = r.start.tz_localize("UTC"); end = r.end.tz_localize("UTC")
        kind = VENUE.get(r.exchange, "none")
        tag = f"case{r.case}_{r.exchange}_{r.pair.replace('/','-')}"
        if kind != "trades":
            log.append((tag, kind, 0, "")); print(f"[skip] {tag}: {kind}", flush=True); continue
        # A window can straddle a file boundary, so pull every daily file it touches.
        # OKX cuts its daily files at 16:00 UTC (a UTC+8 day), so the file named D
        # holds [D-1 16:00, D 16:00); shift by 8h to pick the right file names.
        shift = pd.Timedelta(hours=8) if r.exchange == "okex" else pd.Timedelta(0)
        days = pd.date_range((start + shift).floor("D"),
                             (end - pd.Timedelta(seconds=1) + shift).floor("D"), freq="D")
        frames, urls = [], []
        for day in days:
            try:
                if r.exchange == "bybit":
                    df, u = fetch_bybit(r.pair, day, start, end, is_spot=not r.pair.endswith(".PERP"))
                elif r.exchange == "okex":
                    df, u = fetch_okx(r.pair, day, start, end)
                else:
                    df, u = fetch_binance(r.pair, day, start, end)
                frames.append(df); urls.append(u)
                print(f"  {tag} {day.date()}: {len(df)} rows", flush=True)
            except urllib.error.HTTPError as e:
                print(f"  [HTTP {e.code}] {tag} {day.date()}", flush=True)
            except Exception as e:
                print(f"  [ERR] {tag} {day.date()}: {type(e).__name__} {e}", flush=True)
        if not frames:
            log.append((tag, "FAILED", 0, "")); continue
        df = pd.concat(frames).sort_values("ts")
        if a.dry_run:
            print(f"[dry] {tag}: {len(df)} rows"); log.append((tag, "dry", len(df), urls[0])); continue
        p = out / f"{tag}_trades.parquet"
        df.to_parquet(p, index=False)
        log.append((tag, "ok", len(df), urls[0]))
        print(f"[ok] {p.name}: {len(df)} rows, {p.stat().st_size//1024} KiB", flush=True)

        if a.bookdepth and r.exchange == "binancefutures":
            try:
                bd, u = fetch_binance(r.pair, days[0], start, end, kind="bookDepth")
                bd.to_parquet(out / f"{tag}_bookdepth.parquet", index=False)
                print(f"[ok] {tag} bookDepth: {len(bd)} rows", flush=True)
            except Exception as e:
                print(f"  [ERR bookDepth] {tag}: {e}", flush=True)

    pd.DataFrame(log, columns=["tag","status","rows","url"]).to_csv(out/"_fetch_log.csv", index=False)
    print("\n", pd.DataFrame(log, columns=["tag","status","rows","url"])[["tag","status","rows"]].to_string(index=False))

if __name__ == "__main__":
    main()
