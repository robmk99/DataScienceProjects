# Market data for the competitor execution cases

`manifest.csv` lists, for each of the 15 parent orders, the venue, the instrument
and the UTC hour window that has to be covered.

## What is free and what is not

| Venue | Tick trades | Best bid/ask | Full L2 depth |
|---|---|---|---|
| Bybit (linear + spot) | free, `public.bybit.com` | no | no |
| OKX (swap + spot) | free, `static.okx.com` CDN | no | no |
| Binance USD-M futures | free, `data.binance.vision` | discontinued after 2024-03-30 | only `bookDepth`: notional within ±1..5% of mid, about every 25 s |
| Hyperliquid | requester-pays S3 | included in the L2 snapshots | requester-pays S3, hourly objects per coin |
| Bitget, Lighter, Aster | no public archive found | no | no |

## Running it

```
pip install pandas pyarrow
python3 fetch_market_data.py --manifest manifest.csv --out ../data --bookdepth
```

Hyperliquid needs an AWS account because the bucket is requester-pays. Hyperliquid
itself charges nothing; AWS bills the requester for egress.

```
pip install boto3 lz4
aws configure
python3 fetch_hyperliquid.py --manifest manifest.csv --out ../data/hl --estimate
python3 fetch_hyperliquid.py --manifest manifest.csv --out ../data/hl
```

Each download is trimmed to its case window immediately and written as parquet, so
peak disk use stays close to the size of one day of one instrument.
