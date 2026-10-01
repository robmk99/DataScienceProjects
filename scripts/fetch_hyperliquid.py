#!/usr/bin/env python3
"""
Pull Hyperliquid L2 book snapshots for the competitor execution cases.

The Hyperliquid archive is a REQUESTER-PAYS S3 bucket, so it needs AWS
credentials on the caller's side. Hyperliquid charges nothing for the data;
AWS bills the requester for egress and requests (tens of dollars at this scale).

Setup once:
    pip install boto3
    aws configure            # or export AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY

Estimate before pulling:
    python3 fetch_hyperliquid.py --manifest manifest.csv --out data/hl --estimate

Pull:
    python3 fetch_hyperliquid.py --manifest manifest.csv --out data/hl

Object layout:
    s3://hyperliquid-archive/market_data/<YYYYMMDD>/<H>/l2Book/<COIN>.lz4
One object per coin per hour, LZ4-framed newline JSON of L2 snapshots.
"""
import argparse, json, sys, os
from pathlib import Path
import pandas as pd

BUCKET = "hyperliquid-archive"
PREFIX = "market_data/{date}/{hour}/l2Book/{coin}.lz4"

def coin_of(pair):
    # ETH-USD.PERP / VVV-USDC.PERP -> ETH / VVV
    return pair.split("-")[0]

def keys_for(manifest, cases=None):
    m = pd.read_csv(manifest, parse_dates=["start", "end"])
    m = m[m.exchange == "hyperliquid"]
    if cases:
        m = m[m.case.astype(str).isin(cases)]
    out = []
    for _, r in m.iterrows():
        coin = coin_of(r.pair)
        for t in pd.date_range(r.start, r.end - pd.Timedelta(hours=1), freq="h"):
            out.append((str(r.case), coin, t, PREFIX.format(
                date=t.strftime("%Y%m%d"), hour=t.hour, coin=coin)))
    # de-duplicate: several cases can want the same coin-hour
    seen, uniq = set(), []
    for c, coin, t, k in out:
        if k not in seen:
            seen.add(k); uniq.append((c, coin, t, k))
    return uniq

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cases", default="")
    ap.add_argument("--estimate", action="store_true", help="size/cost only, no download")
    a = ap.parse_args()
    cases = {c.strip() for c in a.cases.split(",")} if a.cases else None
    todo = keys_for(a.manifest, cases)
    print(f"{len(todo)} coin-hour objects to fetch")

    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        print("boto3 missing: pip install boto3 lz4", file=sys.stderr); sys.exit(1)
    s3 = boto3.client("s3")

    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    total = 0; missing = []
    for case, coin, t, key in todo:
        try:
            h = s3.head_object(Bucket=BUCKET, Key=key, RequestPayer="requester")
            total += h["ContentLength"]
        except ClientError as e:
            missing.append(key); continue
        if a.estimate:
            continue
        dest = out / f"{coin}_{t.strftime('%Y%m%d_%H')}.lz4"
        if dest.exists():
            continue
        s3.download_file(BUCKET, key, str(dest), ExtraArgs={"RequestPayer": "requester"})
        print(f"[ok] {dest.name} {dest.stat().st_size//1024} KiB", flush=True)

    gb = total / 1024**3
    # AWS S3 egress to internet is about $0.09/GB; GET requests about $0.0004 per 1000
    print(f"\nfound {len(todo)-len(missing)} objects, {gb:.2f} GiB")
    print(f"estimated AWS cost: ${gb*0.09:.2f} egress + ${len(todo)*0.0000004:.4f} requests")
    if missing:
        print(f"{len(missing)} objects missing (archive has gaps); first few:")
        for k in missing[:5]:
            print("   ", k)

if __name__ == "__main__":
    main()
