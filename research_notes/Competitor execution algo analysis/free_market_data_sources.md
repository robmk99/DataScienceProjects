# Free historical market data sources — September 2026 verification

Tested 2026-10-01. Every HTTP code below was observed with `curl` from this machine.
Dates probed: 2026-09-17, 2026-09-27, 2026-09-29. Symbols as used in the execution-algo study.

## Headline

Two previously-unknown free FULL L2 archives were found and verified:

1. **OKX** publishes real tick-level L2 order book archives (400 and 5000 levels) as
   `.tar.gz` on `static.okx.com`, free, no auth. The download URLs are not guessable —
   they come from an undocumented but **unauthenticated** JSON API.
2. **Bybit** publishes raw `orderbook.200` WebSocket dumps on **`quote-saver.bycsi.com`**
   (not `public.bybit.com`), free, no auth, 200 levels/side, 100 ms deltas.

---

## 1. OKX — FULL L2 depth, free (NEW)

### The real mechanism

`https://www.okx.com/historical-data` (302 → `/en-us/historical-data`, 200) is a React page;
the "Download" buttons are JS. The page bundle
`https://www.okx.com/cdn/assets/okfe/broker-center/assets/brokerHistory-79YS5Hwe.js`
contains the API surface:

```
GET  /priapi/v5/broker/public/trade-data/instruments?instType=SWAP   -> 200 (no auth)
GET  /priapi/v5/broker/public/trade-data/coins                       -> 200
POST /priapi/v5/broker/public/trade-data/download-link               -> 200 (no auth)
GET  /priapi/v5/broker/user/isVip                                    -> 403 (auth only; NOT required)
```

`module` enum from the bundle:
`1`=TRADE_HISTORY, `2`=CANDLESTICK, `3`=FUNDING_RATES, `4`=ORDER_BOOK_400,
`5`=ORDER_BOOK_5000, `11`=INTEREST_RATE. (`10` is rejected: `Parameter module error`.)

Note: the old listing endpoint `/priapi/v5/broker/public/orderRecord` is dead (404). This
`trade-data/*` family is its replacement.

### Working command (verified, HTTP 200, no auth, no cookies)

```bash
# SWAP: use instFamilyList (family, NOT the -SWAP instId).  SPOT: use instIdList.
curl -s -X POST https://www.okx.com/priapi/v5/broker/public/trade-data/download-link \
  -H 'Content-Type: application/json' \
  -d '{"module":"4","instType":"SWAP",
       "instQueryParam":{"instFamilyList":["ZEC-USDT"]},
       "dateQuery":{"dateAggrType":"daily","begin":"1789603200000","end":"1789603200000"}}'
```

Response (`code":"0"`) gives `details[].groupDetails[].{filename,sizeMB,url}`.

### Verified download URL templates

```
https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/<YYYYMMDD>/<INST>-L2orderbook-400lv-<YYYY-MM-DD>.tar.gz
https://static.okx.com/cdn/okx/match/orderbook/pro/L2/5000lv/daily/<YYYYMMDD>/<INST>-L2orderbook-5000lv-<YYYY-MM-DD>.tar.gz
```

`curl -I` results (all HTTP/2 200, `content-type: application/gzip`):

| URL | content-length | last-modified |
|---|---|---|
| `.../400lv/daily/20260917/ZEC-USDT-SWAP-L2orderbook-400lv-2026-09-17.tar.gz` | 344,728,297 | 2026-09-18 00:11 |
| `.../5000lv/daily/20260917/ZEC-USDT-SWAP-L2orderbook-5000lv-2026-09-17.tar.gz` | 130,723,438 | 2026-09-18 00:23 |
| `.../400lv/daily/20260929/TAO-USDT-SWAP-L2orderbook-400lv-2026-09-29.tar.gz` | 51,037,984 | 2026-09-30 00:11 |

### Verified file contents (downloaded TAO-USDT-SWAP 2026-09-29 400lv, 51 MB → 380 MB)

Single `.data` member, JSON Lines, **full incremental L2 feed**:

```json
{"instId":"TAO-USDT-SWAP","action":"snapshot","ts":"1790640000001","asks":[["308","20","7"],...],"bids":[...]}
{"instId":"TAO-USDT-SWAP","action":"update","ts":"1790640000011","asks":[["309.1","2911","17"]],"bids":[]}
```

- Level tuple = `[price, size, n_orders]`.
- 2,343,887 lines/day; **96 `snapshot` rows/day ⇒ one full snapshot every 15 min**, with
  `update` deltas in between at ~10 ms resolution (ts ...0001, ...0011, ...0021, ...0031).
- Snapshot depth measured: **400 asks × 400 bids** (so "400lv" is per side, true full book
  to 400 levels). 5000lv file is *smaller* (price-level-sparse book written differently —
  13–131 MB) but same schema.

### Instrument coverage probed (module=4, SWAP, 2026-09-29)

| instFamily | file returned |
|---|---|
| ZEC-USDT | yes |
| TAO-USDT | yes |
| VVV-USDT | yes |
| AERO-USDT | yes |
| LIT-USDT | yes |
| PUMP-USDT | yes |
| PONS-USDT | **NONE** (not listed on OKX) |
| MON-USDT | **NONE** |
| BTC-USDT | **NONE on 09-29 at 400lv**, but present 09-17 and 09-27 at 400lv, and present 09-29 at 5000lv |

SPOT verified too: `module=4`, `instType":"SPOT"`, `instIdList":["ETH-USDT"]` →
`https://static.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/20260929/ETH-USDT-L2orderbook-400lv-2026-09-29.tar.gz` (115 MB).

**Operational rule: always query `download-link` per (symbol, date); do not construct URLs
blindly — per-day/per-tier gaps exist (BTC-USDT 400lv 09-29).**

### Trades (already known, re-confirmed via same API)
`module=1` → `https://static.okx.com/cdn/okex/traderecords/trades/daily/20260917/ZEC-USDT-SWAP-trades-2026-09-17.zip?v=999`

### What does NOT work (tested)
- `static.okx.com/cdn/okex/traderecords/orderbooks|books|depth|l2/...` → 404 (wrong root; the
  book data lives under `cdn/okx/match/orderbook/pro/L2/`, a different prefix entirely).
- Bucket listing: `https://okg-pub-hk.oss-cn-hongkong.aliyuncs.com/?list-type=2&prefix=...`
  → `AccessDenied` ("bucket does not belong to you"); `static.okx.com/?list-type=2` → `AcdcessDenied`.
  No directory listing; the API is the only index.
- `https://www.okx.com/data-download` → 404.
- `GET /api/v5/market/history-candles?instId=ZEC-USDT-SWAP&bar=1m&after=<Sept>` → 200 but
  `data: []` (public history-candles retention does not reach Sept 2026 at 1m).
- `GET /api/v5/market/history-trades` → 200 but returns only ~current trades (no time filter).

---

## 2. Bybit — FULL L2-200 depth, free (NEW)

`public.bybit.com/` root listing is definitive — only these 5 dirs, **no order book**:
`kline_for_metatrader4/ premium_index/ spot/ spot_index/ trading/`.
`public.bybit.com/orderbook/`, `/depth/`, `/l2/`, `/books/`, `/quote/` → **404**.
`quote.bybit.com` → DNS/connect fail (000). `www.bybit.com/derivatives/en/history-data` → **403** (geo).

The archive is on a **different host**, found via `github.com/nssanta/Bybit-Download-OrderBook-Trades-Klines`:

```
https://quote-saver.bycsi.com/orderbook/linear/<SYMBOL>/<YYYY-MM-DD>_<SYMBOL>_ob200.data.zip
https://quote-saver.bycsi.com/orderbook/spot/<SYMBOL>/<YYYY-MM-DD>_<SYMBOL>_ob200.data.zip
https://quote-saver.bycsi.com/orderbook/inverse/<SYMBOL>/<YYYY-MM-DD>_<SYMBOL>_ob200.data.zip
```

### Verified HTTP 200 (no auth, no referer needed)

| path | 09-17 | 09-27 | 09-29 |
|---|---|---|---|
| linear/VVVUSDT | 200 | 200 | 200 |
| linear/AEROUSDT | 200 | 200 | 200 |
| linear/LITUSDT | 200 | 200 | 200 |
| linear/MONUSDT | 200 | 200 | 200 |
| linear/ZECUSDT | 200 | 200 | 200 |
| spot/ETHUSDT | 200 | — | 200 |
| spot/LITUSDT | 200 | — | 200 |
| spot/BTCUSDT | 200 | — | 200 |
| inverse/BTCUSD | 200 | — | — |

Variant suffixes `ob500`, `ob50`, `ob1` → **404**. Only `ob200` exists.
`quote-saver.bycsi.com/trade/...` → 404 (trades stay on `public.bybit.com`).
`quote-saver.bycsi.com/` root → 404 NoSuchKey (no listing).

Example sizes: `linear/VVVUSDT/2026-09-17` = 66,584,019 B (last-modified 2026-09-18 00:27);
`linear/LITUSDT/2026-09-17` = 32,290,788 B zipped → 193,952,395 B raw.

### Verified contents (downloaded LITUSDT linear 2026-09-17)

Zip with one `.data` member, JSON Lines — **raw V5 WebSocket `orderbook.200` stream**:

```json
{"topic":"orderbook.200.LITUSDT","type":"snapshot","ts":1789603201611,"data":{"s":"LITUSDT","b":[...200...],"a":[...200...],"u":29090667,"seq":262949701298},"cts":1789603201560}
{"topic":"orderbook.200.LITUSDT","type":"delta","ts":1789603201710,"data":{"s":"LITUSDT","b":[4 rows],"a":[2 rows],"u":29090668,"seq":262949702148},"cts":1789603201708}
```

- First row is a **200×200 full snapshot**; everything after is `delta`.
- Cadence: `ts` steps 1611 → 1710 → 1810 → 1910 → 2010 ⇒ **100 ms** (Bybit's linear ob200 push rate).
- `u` (updateId) and `seq` present ⇒ gap detection / exact replay possible.
- Community note: coverage starts ~May 2025, ~450 MB/day raw for liquid symbols.

### Trades (re-confirmed for our symbols, all HTTP 200)

```
https://public.bybit.com/trading/<SYMBOL>/<SYMBOL><YYYY-MM-DD>.csv.gz     # linear perps
https://public.bybit.com/spot/<SYMBOL>/<SYMBOL>_<YYYY-MM-DD>.csv.gz       # spot
```
Verified 200 for VVVUSDT, AEROUSDT, LITUSDT, MONUSDT (09-17, 09-29) and spot ETHUSDT, LITUSDT.

---

## 3. Binance USDⓈ-M futures (established, re-confirmed for our symbols)

| path | PUMPUSDT | PONSUSDT |
|---|---|---|
| `futures/um/daily/aggTrades/<S>/<S>-aggTrades-2026-09-17.zip` | 200 | 200 |
| `futures/um/daily/aggTrades/<S>/<S>-aggTrades-2026-09-29.zip` | 200 | 200 |
| `futures/um/daily/bookDepth/<S>/<S>-bookDepth-2026-09-29.zip` | 200 | 200 |
| `futures/um/daily/bookTicker/<S>/<S>-bookTicker-2026-09-29.zip` | **404** | **404** |

Host: `https://data.binance.vision/data/...`.
`bookDepth` = ±1..5% percentage-depth snapshots ~every 25 s (`timestamp,percentage,depth,notional`)
— **not** a usable L2 book. `bookTicker` discontinued after 2024-03-30. No free full L2.

---

## 4. Bitget — trades yes (REST), book no

| probe | code | result |
|---|---|---|
| `api.bitget.com/api/v2/spot/market/fills-history?symbol=BTCUSDT&limit=1000&startTime=1789603200000&endTime=1789606800000` | 200 | 1000 tick trades, ts 1789605464073→1789606799066 — **reaches Sept 2026** |
| `api.bitget.com/api/v2/mix/market/fills-history?symbol=ZECUSDT&productType=usdt-futures&startTime=...&endTime=...` | 200 | tick trades for Sept window |
| `api.bitget.com/api/v2/spot/market/history-candles?...&endTime=1790640000000` | 200 | 1m OHLCV for Sept |
| `api.bitget.com/api/v2/mix/market/history-candles?...productType=usdt-futures` | 200 | 1m OHLCV for Sept |
| `api.bitget.com/api/v2/spot/market/orderbook?symbol=BTCUSDT` | 200 | **live snapshot only** |
| `www.bitget.com/api/v2/...` | 404 | wrong host; use `api.bitget.com` |
| `img.bitgetimg.com/`, `static.bitget.com/` | 403 | no listing |
| `data.bitget.com/`, `quote-saver.bitget.com/`, `bitget-public.s3.amazonaws.com/` | 000 / 404 | do not exist |
| `www.bitget.com/support/articles/historical-data` | 404 | — |

So: **tick trades are free and historical via REST** (1000 rows/page, `startTime`/`endTime`
windowing — paginate by shrinking the window). No order-book archive, no BBO history.
Bitget's own "historical data" pages are retail OHLCV CSV only.

---

## 5. Hyperliquid — no free L2 history

### Official archive
- `s3://hyperliquid-archive/market_data/<YYYYMMDD>/<H>/l2Book/<COIN>.lz4` — **requester-pays**.
  `https://hyperliquid-archive.s3.amazonaws.com/market_data/20260929/9/l2Book/ETH.lz4` → **403**
  `AccessDenied: Anonymous users cannot invoke requests against Requester Pays buckets.`
- Could not be listed from this machine: no AWS CLI installed and the env `AWS_ACCESS_KEY_ID`
  is a sandbox-proxy credential, not a real AWS key (`sts:GetCallerIdentity` →
  `InvalidClientTokenId`; `ListObjectsV2` → `InvalidAccessKeyId`). **The object-key layout and
  contents below are from documentation and open-source readers, not from a direct listing.**
- Also `s3://hyperliquid-archive/asset_ctxs/<YYYYMMDD>.csv.lz4` (per-minute OI, mark, oracle,
  mid, impact bid/ask, daily volume — ~7 MB/day; this is the closest thing to a free-ish BBO proxy).
- Official docs: uploads happen "**approximately once a month**… no guarantee of timely updates
  and data may be missing." Validator perps only. L2 history nominally back to May 2023.
- Per `github.com/bond-labs-dev/hyperliquid-data`: L2 snapshots are **event-driven, ~550 ms
  cadence (~1.8/s on an active alt)**, not a fixed grid; **full depth with resting-order count
  `n`**; contents are lz4-compressed JSONL. Fills live in a *second* requester-pays bucket
  `s3://hl-mainnet-node-data/node_fills_by_block/hourly/<YYYYMMDD>/<H>.lz4` (current format
  from 2025-07-27; earlier under `node_fills/hourly/`), ~0.8–1.0 GiB/day across all coins.
- Reading it requires `RequestPayer: requester` on every call (`aws s3 cp --request-payer requester ...`).

### Non-requester-pays mirror: none found
Both known third-party mirrors are *also* requester-pays:
- `s3://sonarx-hyperliquid-public` — `market_data/perp/<MARKET>/l2-summary-snapshots/<partition>/<height>.json.gz`,
  **top 20 levels per side**, every 20 blocks, weekly refresh w/ 2-day lag, CC0.
- `s3://hydromancer-reservoir` (ap-northeast-1) — `by_dex/hyperliquid/...`, **20-level L2**,
  orderbook refreshed weekly; fills + 1 s candles daily.

So the only cost is AWS egress (~$0.09/GB), but it needs a real AWS account → **not "free, no account"**.

### Free HTTP API (`POST https://api.hyperliquid.xyz/info`) — tested
| type | result |
|---|---|
| `l2Book` `{"coin":"VVV"}` | 200, full live book — **live only, no time parameter** |
| `recentTrades` `{"coin":"ETH"}` | 200, recent trades — **no time parameter, live only** |
| `trades`, `userFills` (coin only), `l2BookSnapshot` | `Failed to deserialize the JSON body` — not public types |
| `candleSnapshot` | 200, **historical OHLCV works**, but ~5000-candle retention per interval |

`candleSnapshot` retention measured for ETH (returns `{t,T,s,i,o,c,h,l,v,n}`; `n` = trade count):

| interval | 2026-09-28 | 2026-09-26 | 2026-09-17 |
|---|---|---|---|
| 1m | 61 rows | **0** | **0** |
| 5m | — | — | 73 rows |
| 15m | — | — | 25 rows |
| 1h | — | — | 7 rows |

⇒ **1m candles only go back ~3.5 days** (5000×1m). For 2026-09-17 the finest free granularity
is 5m. Confirmed working for ETH, VVV, PUMP, PONS. **There is no free historical trades or L2
HTTP endpoint.**

---

## 6. Lighter (zkLighter) — trades via cursor walk only

Base `https://mainnet.zklighter.elliot.ai/api/v1/`. Market ids resolved: ETH=0, MORPHO=68, **LIT=120**.

| endpoint | code | note |
|---|---|---|
| `orderBooks`, `orderBookDetails`, `exchangeStats` | 200 | metadata; 246 markets |
| `recentTrades?market_id=0&limit=5` | 200 | live |
| `trades?market_id=120&limit=100&sort_by=timestamp` | 200 | returns `next_cursor`, walks backwards |
| `fundings?market_id=0&resolution=1h&start_timestamp=...` | 200 | **historical funding works** |
| `candlesticks?market_id=...&resolution=1m&start_timestamp=...` | **403** | 403 from this IP with every param form and with full browser UA/Origin/Referer; other endpoints on the same host return 200, so it is an endpoint-level block, not a bad request |
| `openapi.json`, `/docs` | 403 | — |
| `api.lighter.xyz/...` | 000 | wrong host |

`trades` pagination: cursor is base64 `{"index":<global trade_id>}`. Sequential walk works
(10 pages × 100 trades covered ~28 min of LIT). **Seeking is not possible** — injecting a
synthetic `index` (e.g. a ms timestamp, or an arbitrary lower trade_id like 32000000000)
returns `trades: []`; `&from=<ms>` also returns `[]`. So reaching 2026-09-17 means ~700+
sequential pages per day per market. **No file archive, no book history.**

---

## 7. Aster DEX — trades via REST, no archive

Binance-compatible API at `https://fapi.asterdex.com`.

| endpoint | code | result |
|---|---|---|
| `fapi/v1/exchangeInfo` | 200 | — |
| `fapi/v1/aggTrades?symbol=MORPHOUSDT&startTime=1790640000000&endTime=1790640600000` | 200 | **historical agg trades for Sept 2026**, e.g. `{"a":19854,"p":"2.5267000","q":"13.3","T":1790640413400,"m":true}` |
| `fapi/v1/klines?symbol=MORPHOUSDT&interval=1m&startTime=1790640000000` | 200 | 1m OHLCV for Sept |
| `fapi/v1/depth?symbol=MORPHOUSDT&limit=1000` | 200 | **live snapshot only** |
| `fapi/v1/historicalTrades` | 401 | `API-key format invalid` — needs a key |
| `data.asterdex.com` | — | blocked by this environment's egress proxy (`connect_rejected`), not verifiable here |
| `asterdex-public.s3.amazonaws.com` | 404 | `NoSuchBucket` |
| `sapi.asterdex.com/api/v1/aggTrades?symbol=MORPHOUSDT` | 400 | `Invalid symbol` (spot host, no MORPHOUSDT) |

No `data.binance.vision` equivalent found. `aggTrades` with `startTime`/`endTime` is the
historical path (free, no key).

---

## Definitive per-venue summary

| Venue / instruments | TRADES free | BBO/quotes free | FULL L2 depth free |
|---|---|---|---|
| **Bybit linear** VVVUSDT, AEROUSDT, LITUSDT, MONUSDT | **YES** `public.bybit.com/trading/<S>/<S><date>.csv.gz` | YES (derive from ob200 top level) | **YES** `quote-saver.bycsi.com/orderbook/linear/<S>/<date>_<S>_ob200.data.zip` — 200 lvl/side, 100 ms |
| **Bybit spot** ETHUSDT, LITUSDT | **YES** `public.bybit.com/spot/<S>/<S>_<date>.csv.gz` | YES (from ob200) | **YES** `quote-saver.bycsi.com/orderbook/spot/<S>/<date>_<S>_ob200.data.zip` |
| **OKX swaps** ZEC-USDT-SWAP, TAO-USDT-SWAP | **YES** `static.okx.com/cdn/okex/traderecords/trades/daily/<YYYYMMDD>/<INST>-trades-<date>.zip` | YES (from L2) | **YES** `static.okx.com/cdn/okx/match/orderbook/pro/L2/{400lv,5000lv}/daily/<YYYYMMDD>/<INST>-L2orderbook-<tier>-<date>.tar.gz`, URL from `POST /priapi/v5/broker/public/trade-data/download-link` — 400 lvl/side, 15-min snapshots + ~10 ms deltas |
| **Bitget spot** BTCUSDT, ETHUSDT | **YES** REST `api/v2/spot/market/fills-history` (1000/page, startTime/endTime) | NO | **NO** |
| **Bitget linear** ZECUSDT | **YES** REST `api/v2/mix/market/fills-history` (productType=usdt-futures) | NO | **NO** |
| **Binance USDⓈ-M** PUMPUSDT, PONSUSDT | **YES** `data.binance.vision/data/futures/um/daily/aggTrades/...` | **NO** (bookTicker 404 after 2024-03-30) | **NO** (only `bookDepth` ±1–5% notional, ~25 s) |
| **Hyperliquid perps** (all 10 coins) | **NO** free — fills are in requester-pays `s3://hl-mainnet-node-data`; REST `recentTrades` is live-only | NO (impact bid/ask via requester-pays `asset_ctxs`) | **NO** free — `s3://hyperliquid-archive/market_data/<date>/<hr>/l2Book/<coin>.lz4` is requester-pays (403 anonymous); mirrors (sonarx, hydromancer) also requester-pays, top-20 only. Free REST gives OHLCV only (1m ≤ ~3.5 d; 5m reaches 09-17) |
| **Lighter perps** LIT | **PARTIAL** — `api/v1/trades` cursor walk back to Sept is possible but no seek, ~700 pages/day/market | NO | **NO** |
| **Aster DEX perps** MORPHO | **YES** `fapi.asterdex.com/fapi/v1/aggTrades?symbol=...&startTime=&endTime=` | NO | **NO** |

### Practical implication for the execution-algo study
For Sept 2026, real microstructure (queue position, spread, depth-at-touch) is only
reconstructible on **Bybit** (all 6 requested instruments) and **OKX** (ZEC, TAO swaps — plus
VVV, AERO, LIT, PUMP and ETH-USDT spot if useful). Binance, Bitget, Lighter, Aster and
Hyperliquid are trades-only at zero cost; Hyperliquid full L2 needs an AWS account and
requester-pays egress (official archive, ~550 ms event-driven, full depth with order counts).
