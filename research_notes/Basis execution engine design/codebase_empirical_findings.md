# Basis engine — empirical findings compiled from the codebase docs

Compiled 2026-09-30 from the read-only checkout at `scratchpad/be/basis-engine`. Every number below is
tagged with the source file and line it was taken from. Evidence classes follow the team's own
convention: **[M]** measured (with n and host), **[V]** venue documentation, **[R]** third-party report,
**[U]** unverified/guess, **[X]** venue doc quoted verbatim (Bybit).

Headline for the reviewer: **the team has run exactly 4 live parents, all Taker-Taker, all on HL
testnet, all one clip (~$12.5 spot / ~$50 perp), on a thin placeholder pair (CC/USDC @1216).** No MT
(passive) parent has ever posted a maker order, no mainnet order has been sent, no Bybit order has been
sent, and **no runner emits a TCA record** — every TCA metric is defined but unmeasured on real fills.
What *is* measured well: block cadence, feed one-way latency, WS push cadence, HL/Bybit book depth,
the HL edge-class lottery, the HL testnet fee schedule and the venue-side latency of one TT parent.

---

## 1. Latency and cadence numbers per venue / environment

### 1.1 The host (CONNECTIVITY.md §0, lines 27–41)

| fact | value | src |
|---|---|---|
| Host | Vultr Tokyo `149.28.26.157` (`edge-desk-01`), 3 vCPU shared with Robert's live bots | CONNECTIVITY L31–33 |
| Loadavg during measurements | 3.88 / 4.51 / 5.44 (oversubscribed 1.3–1.8×); 2.5→5.7 and 3.5→9.46 during ROB-272 probes | CONNECTIVITY L34; LATENCY_PLAN L73, L185 |
| Invalidation criterion | loadavg > 1.5 → every host-sensitive tail is an upper bound | LATENCY_PLAN L74; CONNECTIVITY §3.0 |
| NTP | `System clock synchronized: yes`, SNTP offsets −4.7…+2.7 ms → clock term ≲5 ms | LATENCY_PLAN L154–156 |
| Not available without root | `chrt`, `isolcpus`, `SO_BUSY_POLL`, cpuset; only `taskset` | CONNECTIVITY L35–36 |

### 1.2 HL network hop — the edge-class lottery [M, ROB-79] (CONNECTIVITY.md §1.5, L100–156)

`api.hyperliquid.xyz` resolves to three CloudFront /24s, 960 DNS answers sampled:

| edge class | DNS share | ICMP min/avg | TCP connect p50 | p99 | one-way |
|---|---|---|---|---|---|
| `13.227.50.x` far | **71%** | 8.30 / 9.81 ms | **8.61 ms** | 21.5 ms | ~4.3 ms |
| `3.173.197.x` near | 18% | 1.40 / 2.23 ms | 2.54 ms | 24.4 ms | ~1.25 ms |
| `99.86.195.x` near | 11% | 0.53 / 1.95 ms | 2.06 ms | 47.6 ms | ~1.0 ms |

- Connect − ICMP ≈ +0.3 ms on both classes → SYN/CloudFront overhead ruled out; far class goes via Arelion AS1299 / NTT AS2914 transit (L120–123).
- TLS handshake p50 **12.6–13.1 ms** on all three classes → a fresh connection costs ~15 ms (near) / ~21 ms (far) before payload (L137–142).
- Everything we control ≈ **1.05–1.4 ms near / ~4.35 ms far** vs HL-side ≈380–900 ms → 0.1–0.3% / 0.5–1.2% of one action (L16–18, L61–63). Software (a+b) is 0.03–0.12 ms [R/U, still unmeasured] (L13).

### 1.3 HL block cadence — clock-free instrument [M, ROB-272] (LATENCY_PLAN.md §1.2, L100–147)

Measured from the venue's own block stamps on `bbo` frames, so no local clock/load caveat.

| env | window | distinct block stamps | blocks/s (lower bound) | delta min / p10 / p25 / p50 | p75 / p90 / max |
|---|---|---|---|---|---|
| mainnet, 2026-09-30 05:27Z, 300 s | 321.6 s | 3,003 | **9.34/s** | 45 / 63 / 66 / **71 ms** | 133 / 147 / 13,639 ms |
| testnet, dense `bbo` on 40 perps, 200 s | 200.4 s | 1,352 | **6.75/s** | 51 / **102 / 103** / 118 ms | 156 / 247 / 717 ms |

- Mainnet block unit ≈ **66–71 ms** (p75/p90 sit on the 2-block line 133/147); testnet ≈ **102 ms** (per-coin p10 102–104 ms) (L117–132).
- `l2Book` is server-throttled to **5.39 s p50 mainnet / 5.28 s testnet** (n=56/57) and is *not* a cadence instrument (L138–142).
- 693 ms leg ÷ 102 ms = **6.8 testnet blocks** per order (L144–147).

### 1.4 HL feed one-way latency (venue stamp → our socket) [M, probe2, NTP-synced] (LATENCY_PLAN.md §1.3, L160–197)

| channel / env | n | min | p50−min (receiver jitter) | p99−min |
|---|---|---|---|---|
| mainnet `BTC\|bbo` | 1,986 | **156.9 ms** | 83.8 | 367.7 |
| mainnet `@142\|bbo` | 1,285 | 160.8 ms | 85.6 | 390.2 |
| mainnet `HYPE\|bbo` | 1,458 | 160.8 ms | 82.6 | 362.5 |
| mainnet `ETH\|bbo` | 1,719 | 169.1 ms | 73.6 | 389.5 |
| mainnet `BTC\|trades` | 247 | 172.5 ms | 86.2 | 577.1 |
| testnet `BTC\|bbo` | 134 | **229.9 ms** | 31.6 | 142.6 |
| testnet `CC\|bbo` | 299 | 231.2 ms | 44.4 | 187.3 |
| testnet `SOL\|bbo` | 145 | 232.5 ms | 38.9 | 144.0 |

Defensible result = the cross-env difference (clock offset cancels): mainnet feed is **~65–70 ms faster** (~157–169 vs ~230–236 ms), one testnet block less of pipeline (L178–182). Levels are upper bounds (loadavg 3.5→9.46) (L185–187).

### 1.5 HL order path — the only live measurement (LATENCY_PLAN.md §2.2, L221–231; TESTNET_RUNS.md §1.8, L614–631)

Four 22a TT parents, testnet, 2026-09-29 20:45–21:06Z:

| parent | leg S send→reply | leg P send→reply | earliest leg-S fill push − S-reply | parent total |
|---|---|---|---|---|
| open1 204551Z | 726.50 ms | 764.14 ms | +12.51 ms | 1491.61 ms |
| close2 210613Z | 693.40 ms | 692.91 ms | +10.24 ms | 1386.31 ms |
| open3 210623Z | 715.76 ms | 681.92 ms | +0.02 ms | 1397.67 ms |
| close4 210633Z | 741.74 ms | 800.13 ms | +1.79 ms | 1541.88 ms |

- Venue-stamped legging window (leg-S fill block → leg-P fill block): **717 / 719 / 765 / 769 ms** (LATENCY_PLAN L28–29).
- `S-reply→P-send = 0.000 ms` in all four is a per-tick `now` clock artefact, not a measurement (TESTNET_RUNS L623–625).
- The post reply beat the fill push in **4/4** parents by 0.02–12.51 ms; 0 pushes before the reply → the reply is the earliest hedge trigger; racing sources is worth 0 ms median, tail insurance only (LATENCY_PLAN L228–251).
- Engine-side hypotheses all ruled out: `peek()`-based idle read (no 100 ms poll artefact), `TCP_NODELAY` set (`conn.rs:167`), persistent pre-authed WS `post` (LATENCY_PLAN L90–94). CONNECTIVITY L167 (29.09) said NODELAY "not yet wired" — superseded.
- Time to first action after process start: **236 / 490 / 381 / 367 / 451 ms** (TESTNET_RUNS L792–793).
- Smoke run 2026-09-29 11:32Z: order ack **397 ms**, cancel ack **763 ms**, n=1 (TESTNET_RUNS L1478–1483); `scheduleCancel` reply 662.9 ms (VENUES L311).

### 1.6 Published / third-party HL order latency [R]/[V] (CONNECTIVITY.md L59; LATENCY_PLAN.md L35–39)

- REST order-to-fill **884 ms median** from AWS Tokyo, range 695–1634 ms, ~879 ms server-side (Glassnode/Hyperlatency via CoinDesk 2026-03-30).
- HL docs: ~380 ms cancel/ALO e2e; ~0.2 s p50 / 0.9 s p99 **colocated**.
- Verdict (LATENCY_PLAN L38–39): **do not budget a mainnet order-path speed-up; budget 0.7–0.9 s per leg** until the ROB-108 post-ack probe measures it. No mainnet order has been sent (L63–65).
- Priority fee: ≈45 ms of IOC priority per 1 bp, capped 8 bps [V] (CONNECTIVITY L74–75); not paid for MVP.

### 1.7 HL WS push cadence [M, ROB-145] (VENUES.md §1.12, L340–415)

Two 600 s windows per env, 2026-09-29 16:01Z; inter-arrival ms (local clock):

| env | coin | `l2Book` n / p50 / p99 / max | unchanged pushes | `bbo` n / p50 / p99 / max | `trades` n | union p50 / p99 / max / gaps>3000 |
|---|---|---|---|---|---|---|
| testnet | `@1216` spot | 116 / 5219 / 5504 / 5518 | **115/115** | **0** | 0 | 5219 / 5504 / 5518 / **115** |
| testnet | `CC` perp | 116 / 5220 / 5504 / 5518 | 0/115 | 754 / 428 / 4062 / 4390 | 0 | 412 / 3849 / 4390 / 37 |
| mainnet | `@142` spot | 113 / 5385 / 5798 / 5839 | 0/112 | 2907 / 132 / 1410 / 3803 | 143 | 122 / 1150 / 3803 / 3 |
| mainnet | `BTC` perp | 113 / 5384 / 5798 / 5839 | 0/112 | 5459 / **84** / 473 / 1565 | 1048 | 66 / 457 / 1565 / 0 |
| mainnet | `ETH` perp | 113 / 5384 / … | 0/112 | 5286 / 87 / 529 / 1467 | 962 | 67 / 500 / 1467 / 0 |
| mainnet | `HYPE` perp | 113 / 5385 / … | 0/112 | 4398 / 100 / 706 / 1891 | 1207 | 69 / 606 / 1531 / 0 |
| mainnet | `SOL` perp | 113 / 5385 / … | 0/112 | 5215 / 90 / 493 / 1425 | 468 | 79 / 479 / 1425 / 0 |

- `l2Book` is one venue-wide tick: mainnet 8.0 coins/burst, burst span p50 0.9 ms, inter-burst p50 **5385 ms** (min 1340, max 5836); testnet p50 5219 (L379–384). A frozen book is still pushed byte-identical (L388–393). Docs' "each block ≥0.5 since last push" contradicts observation (L391–393).
- `bbo` is change-gated, the only sub-second channel (p50 84–149 ms mainnet) and can be silent 600 s on a frozen book (L394–397). `trades` useless for liveness (L398–399). `allMids` tick ~5.03 s (L376–377, L400–401).
- Worst union gap re-derived for D21: mainnet perp **1834 ms**, mainnet spot **4097 ms**, testnet `@1216` **5530 ms** (DECISIONS L1289–1300) → `stale_halt_ms` = 9000 (min 8000, max 30000).
- Worst `l2Book` tick varied 5839 ms (16:01 window) vs **7336 ms** (15:48 window, venue-wide) (L410–413).

### 1.8 Bybit cadence [M, ROB-26, mainnet public] (VENUES.md §5.1, L1078)

Touch cadence medians: BTC spot 20.5 ms / linear 28.4 ms; ETH spot 39.9 / linear 20.6; HYPE spot 79.5 / linear 70.1. WS `orderbook` delivered snapshot frames only (2,782–9,776 frames/book, 0 reconnects) (L1221). **No Bybit order-path latency exists** — acks, cancels, budget all `[U]` (TESTNET_RUNS L2046–2048, L2083–2086).

---

## 2. Book depth / liquidity measurements per pair

### 2.1 HL mainnet universe study [M, ROB-29] (VENUES.md §1.3–1.5, L78–175; window 2026-09-29 10:06:56–10:09:28Z, 21 snapshots/pair, 801 requests, 19 × HTTP 429)

Spread and executable basis at the touch (bps, medians, n=21):

| pair | spot spread | perp spread | B_open | B_close | B_mid | wrapper prem vs oracle |
|---|---|---|---|---|---|---|
| BTC | 0.119 | 0.119 | −2.97 | −2.73 | −2.85 | −2.07 |
| ETH | 0.368 | 0.368 | +2.58 | +4.05 | +3.31 | −0.92 |
| HYPE | 0.113 | 0.113 | −2.03 | −1.36 | −1.58 | +0.06 |
| SOL | 0.835 | 0.835 | +1.67 | +3.34 | +2.51 | −5.42 |
| ZEC | 0.702 | 0.701 | +2.81 | +4.91 | +3.86 | −1.89 |
| PUMP | 1.394 | 1.989 | +10.37 | +14.34 | +12.36 | −2.68 |
| ENA | 57.454 | 1.978 | −28.53 | +34.44 | +2.97 | −3.96 |

- Fee-only touch edge `B_open − 8.5` negative on 8/9 pairs; with hedge slip 3.0 negative on **9/9** (L98–103). "Spot books are wide" thesis is under question: majors ≈0.06–0.12 bps (VENUES L86–88; PLAN §11, 28.09 18:21 entry: "спот-книги HL для мейджоров узкие (≈0.06 bp)").

Depth within 10 bps of mid (USD, medians; L122–132):

| pair | S bid10 | S ask10 | P bid10 | P ask10 |
|---|---|---|---|---|
| BTC | 568,171 | 634,196 | 5,407,681 | 2,759,986 |
| ETH | 491,902 | 380,806 | 10,612,692 | 7,767,669 |
| HYPE | 113,121 | 96,692 | 119,784 | 103,748 |
| SOL | 122,445 | 227,766 | 2,415,176 | 2,797,731 |
| ZEC | 17,742 | 21,377 | 490,290 | 576,887 |
| PUMP | 11,096 | 2,442 | 22,367 | 66,209 |
| XPL | 1,579 | 1,917 | 12,979 | 14,315 |
| ENA | **0** | **0** | 54,413 | 53,178 |
| PURR | 193 | 224 | 121 | 64 |

- `l2Book` returns ≤20 levels/side → 25-bp column truncated for BTC/ETH/HYPE (L134–139).
- Spot tape is retail: median spot trade $31 (HYPE), $44 (BTC), $1,668 (ETH); spot trades/min HYPE 33.5, BTC 26.5, ETH 11.2, SOL 1.9, ENA 1.5 (L158–174).
- Ranking for MT: BTC, ETH, HYPE, SOL cover $50K at 10 bps; ZEC $10K; ENA/PURR not admissible (L205–225).
- σ perp mid (bps/√s, 152 s): BTC 0.315, ETH 0.568, HYPE 0.583 — ED §5.4 imbalance formula only binds at σ ≥ 4.71 → vol does not constrain `max_imbalance_usd`, the unwind does (L183–193, L439–443).

### 2.2 HL mainnet M3.5 candidate snapshot [M, ROB-111] (research/rob111_mainnet_books.md L1–30; window 2026-09-29T18:23:30–18:24:09Z, 5 snapshots × 19 pairs, 244 requests, 0 × 429, $100 clip)

| rank | pair | wire | ratio | spread S/P | depth 10 bps S ask / P bid | IOC walk at $100 | B_mid | funding APR | TT round trip | carry breakeven |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | BTC | @142 | 1.0001 | 0.12/0.12 | $570,535 / $5,674,154 | 0.00 bps all four | +0.60 | 10.95% | **23.12 bps** | 7.7 d |
| 2 | ETH | @151 | 1.0008 | 0.74/0.37 | $295,358 / $10,542,172 | 0.00 | +7.81 | 10.95% | 23.56 | 7.9 d |
| 3 | ZEC | @272 | 1.0007 | 0.71/0.71 | $12,719 / $279,015 | 0.00 | +7.05 | 18.98% | 23.71 | 4.6 d |
| 4 | HYPE | @107 | 1.0001 | 1.51/0.46 | $189,458 / $100,836 | 0.00 | +0.93 | 10.95% | 23.81 | 7.9 d |
| 5 | SOL | @156 | 0.9998 | 0.84/0.84 | $164,923 / $1,935,860 | 0.00 | −1.68 | 10.95% | 23.84 | 7.9 d |

- Mapping traps caught by guard 2: PUMP @188/@20 ratio **30.5×**, TRUMP @9 **1769×**, BERA @117 **231×**, MON @243/@129 4.22×, AVAX @306 0.964, STABLE 0.788, AZTEC 0.939; PURR |B_mid| +55.2 bps on a $502 book (MAINNET_RUNS L117–127).

### 2.3 HL mainnet spot depth vs $100 clip [M, ROB-272] (LATENCY_PLAN.md §3.3, L324–343; 240 s at 0.4 s, 463 samples/book, band 10 bps from touch)

| book | ask depth min | p01 | p10 | p50 | samples < $100 clip |
|---|---|---|---|---|---|
| @142 UBTC/USDC | **$197,550** | $275,922 | $437,758 | $578,879 | 0/463 |
| @151 UETH/USDC | $138,789 | $194,863 | $340,148 | $390,124 | 0/463 |
| @107 HYPE/USDC | $38,346 | $42,420 | $50,454 | $93,679 | 0/463 |

Thinnest observation is 383× the clip; p01 worst 1,949×; spreads 0.12 bps (@142, @107), 0.37 bps (@151). Zero leg-S under-fill needs a 99.7% depth loss (L334–338).

### 2.4 HL testnet books (the pair the live runs used) [M]

- ROB-104 (2026-09-29 12:24:59Z, 5 snapshots): only **UETH/ETH** and **CC/CC** usable at $12.5 and $25; CC needs `max_slippage_bps` override (+33.8 bps cap); NEAR, HYPE, USOL, legacy BTC unusable (research/rob104_testnet_books.md L11–20). Testnet spot spread on UETH ≈ 9,800 bps; `B_open` = **+273,883 bps** on ETH, σ(spot mid)=0 (VENUES L275–278).
- ROB-171 @1216/CC re-probe (2026-09-29 20:09:51Z, 15 snapshots): spot bid/ask 0.031285/0.031379 (spread **30.0 bps**), top ask **98.25 CC n=1**, top bid 250 CC n=1; perp spread 23.6 bps, top 2512/3178 CC; ratio 4.047× (research/rob171_22a_books.md L11–16). Spot ask depth 98 CC at ±10/25 bps, 348 at 40, 598 at 60, 848 at 100 bps (L22–26). `lot_eff` = 399 CC; TT attemptable at frac 0.5 only at 100 bps cap (L38–52). Worst IOC walk vs touch at $12.5: spot buy **+26.2 bps**, spot sell +11.3, perp 0.0 (L71–80). `--size-usd` 12.5 → target 0 (BelowMinNotional); 12.6 admits (L55–68).
- ROB-205 re-probe (2026-09-29 22:55:19Z): spot 0.031379/0.031473 (29.9 bps), top ask 250 / bid 103, perp spread 11.3 bps, ratio 3.950×; admission floor $12.5075; spot/perp REST fetch skew 671 ms (research/rob205_22b_books.md L11–16, L55–68, L83).
- testnet universe: 1,329 spot pairs, 212 perps, 18 perp-mapped; only ETH two-sided both legs of 4 candidates; testnet spot volume $0–$8.4K/day vs $1.15M–$113.8M mainnet (VENUES L268–294).

### 2.5 Bybit mainnet [M, ROB-26] (VENUES.md §5.2, L1089–1101; 2026-09-29 19:11:36–19:19:40Z, 72 depth rounds `limit=1000`)

| leg | spread bps | depth 5 bp bid/ask | depth 10 bp bid/ask | trades/min | median trade $ | queue clear (min) bid/ask |
|---|---|---|---|---|---|---|
| spot BTCUSDT | 0.012 | 641,332 / 812,897 | 2,211,582 / 1,764,161 | 543 | 89.4 | 0.22 / 0.21 |
| linear BTCUSDT | 0.012 | 10.77M / 10.61M | 28.07M / 27.81M | 807 | 83.6 | 0.36 / 0.49 |
| spot ETHUSDT | 0.037 | 293,956 / 313,948 | 1,014,390 / 1,198,497 | 240 | 296.7 | 0.25 / 0.33 |
| linear ETHUSDT | 0.037 | 6.20M / 5.37M | 15.70M / 14.80M | 1,235 | 27.0 | 0.23 / 0.60 |
| spot HYPEUSDT | 1.156 | 8,779 / 8,135 | 27,529 / 44,994 | 38 | 259.7 | 0.54 / 0.37 |
| linear HYPEUSDT | 1.157 | 144,310 / 137,932 | 433,726 / 457,921 | 150 | 8.6 | 0.61 / 0.41 |

Linear is 10–16× deeper than spot at 10 bps on every pair; spread identical to 0.001 bps (L1098–1101). Maker markout at touch, tape-conditioned, 5 s: BTC spot −0.927/−0.795 (fp 0.577/0.664), linear −0.748/−0.808 (fp 0.911/0.864); ETH spot −0.982/−0.723, linear −0.538/−0.538; HYPE spot −0.597/+0.579 (fp 0.253/0.328), linear −0.579/−0.578 (fp 0.746/0.598) (L1117–1136). Resting the perp fills 1.3–1.6× as often on BTC/ETH, 1.8–3.0× on HYPE (L1149–1150).

### 2.6 Bybit testnet [M, ROB-266] (research/rob266_bybit_books.md L1–125; 2026-09-30T05:04:50Z, 18 snapshots over 62 s)

- Universe: 794 spot, 839 linear, 232 overlapping, **only 5** live on both legs (L8–11).
- Chosen ETHUSDT: spot 2671.71/2671.73, perp 2721.47/2721.48; basis **+186.2 bps** (min 185.2 / p50 185.4 / max 185.7 over 62 s); spread 1 tick each; spot depth 5 bps 2.20/1.08 ETH, perp 0.94/2.24 ETH; `lot_eff` 0.01 ETH ($26.72 spot / $27.21 perp); one spot step $0.0267 < $5 minimum, one perp step $27.21 (L40–80, L85–100).
- Excluded BTCUSDT: one perp step $83.54 > $60 ceiling (L122–125). Fallbacks DOTUSDT, SOLUSDT (L117–120).

### 2.7 HL equity perps (HIP-3) [M, ROB-123] (research/rob123_hl_equity_perps.md L531–566; VENUES.md §4.6, L951–975)

- 34 samples 60 s apart around NYSE open 2026-09-29 13:30Z: perp book does not shut when equities close — NVDA spread 0.434 both regimes, MU 10-bp bid $0.94M closed vs $1.75M open; what degrades is the tape (last-print age p90 72.8 s AAPL, 41.8 s TSLA closed vs 5.6–11.9 s open); first minute of session: AAPL spread 0.593 → 5.089 bps, TSLA mid −1.6% in four minutes (L546–556).
- 29 of 79 `l2Book` requests returned `empty book` — all `km`, `mkts`, `cash`, `flx` equity dexes unquoted (L558–566).
- v1 recommendation: NVDA (24h vol $105.1M, 10-bp bid $601,738, funding +5.475%, breakeven 9.3 d, size cap $150K), META ($48K cap), MU (10-bp bid $933,710, cap $233K), INTC (funding +14.70%, breakeven 3.5 d), + one more (VENUES L969–975).

---

## 3. Execution outcomes from testnet and mainnet runs

### 3.1 Inventory of live runs (research/testnet/)

`run-smoke-2026-09-29T113218Z`, `run-smoke-…T122351Z` (DMS probes); `run-22a-open1-…T184356Z/T184410Z` (ROB-169 incident), `…T195941Z/T195951Z` (StaleReference rerun), `…T204551Z` (run 1), `run-22a-close2-…T210249Z` (run 2a), `…T210613Z` (run 2b), `run-22a-open3-…T210623Z` (run 3), `run-22a-close4-…T210633Z` (run 4). **No 22b (MT), no Bybit, no mainnet run logs exist.** MAINNET_RUNS.md is a DRAFT card awaiting Robert's limits (MAINNET_RUNS L3–5).

### 3.2 22a TT — four live parents, HL testnet, @1216 CC/USDC ↔ CC perp (TESTNET_RUNS.md §1.8, L598–853; research/rob185_22a_results.md)

| run | state | fills | leg-S walk vs touch | leg-P walk | fees |
|---|---|---|---|---|---|
| 1 OPEN 399 CC (204551Z) | killed exit 124 after 298 s silence (D27/D29) — both legs filled | 98.25@0.031379 + 250@0.031473 + 50.75@0.031567 | **+26.39 bps** (3 levels) | 0.00 | spot 0.2793 CC (7.0 bps), perp 4.5 bps |
| 2a CLOSE 397 CC (210249Z) | Killed exit 3 — guard refused at $12.42 < $12.50 floor, nothing sent | — | — | — | — |
| 2b CLOSE 397 CC (210613Z) | Completed exit 0 | 250@0.031473 + 147@0.031379 | +11.06 bps | 0.00 | 7.0 / 4.5 bps |
| 3 OPEN 398 CC (210623Z) | Completed exit 0 | 250@0.031473 + 148@0.031567 | +11.11 bps | 0.00 | 7.0 / 4.5 bps |
| 4 CLOSE 397 CC (210633Z) | Completed exit 0 | 250@0.031473 + 147@0.031379 | +11.06 bps | 0.00 | 7.0 / 4.5 bps |

Findings (L633–683):
1. TT happy path works twice each direction; fill rate on legs **100%** (both legs fully filled in 4/4 sent parents); leg P filled at touch in 4/4, one fill each, **0.00 bps** walk — 4th confirmation of D26's "perp IOC walk 0.0 at every size" (L639–641).
2. Leg-S structural walk **11–26 bps** from the ladder (levels ~30 bps apart holding 98–250 CC vs a 397–399 CC slice → 2–3 levels every time); `max_slippage_bps` 60 is not the binding constraint (L642–649).
3. Fee schedule confirmed on venue: spot taker **7.0 bps**, perp taker **4.5 bps** → `fees_tt_bps` 11.5; total cost of four parents **$0.1783** (~$0.0446 each on ~$50 leg P) vs $0.22 model; `fee_spot_maker_bps` 4.0 **unverified** (L657–662).
4. Every OPEN is left short the base-denominated spot fee: −0.27929956 CC (run 1) / −0.27859980 CC (run 3) = 7.0 bps of leg S unhedged, $0.035, invisible to `flat: true` → D30 (L663–677). At $1M leg S that is $700/OPEN (rob185 L166–169).
5. Account reconciles to the raw unit: 403.1614 CC spot, −3.0 CC perp; **+400 CC standing spot from the 18:44Z ROB-169 incident** (leg S bought 401 CC, leg P refused at the $25 guard, no flatten) still open (L678–683).
6. Legging exposure (honest): leg-S send → leg-P reply **764 / 693 / 682 / 800 ms**; all inside `max_legging_time_ms` 2000; n=4 does not re-parameterise anything (L625–631).
7. Rejects: run 2a guard refusal (`$12.420145 = 397 × 0.03128500` vs $12.50 floor), retry 10 s later passed on a 60-bps-higher touch (L685–693). 19:59Z rerun: **132 StaleReference vs 51 BelowMinNotional** over 119.6 s → touch gate open ~19% of wall time (1 s window per ~5.2 s `l2Book` tick) (L784–787). Fresh parents act on the first tick — the "expect StaleReference" note was wrong (L791–797).
8. Run 4 at 2× (798 CC) cannot start: leg P = $100.71 = 1.68× the $60 per-order ceiling; on this pair the ceiling is structurally a 1-`lot_eff` ceiling (L798–805).
9. **No TCA record exists for any run** — `crates/engine` has no `tca` dependency; arrival benchmarks, `slip_vs_arrival_touch`, `A_to_B_recv`, `book_age_ms` all unmeasured (L777–787).
10. Basis on the pair moved one 30-bps level between runs 10 s apart; implied cross-book spread moved from ~30 bps (20:09Z) to ~100–150 bps (21:02:49Z) (L845–849).

### 3.3 22b MT — never run (TESTNET_RUNS.md §2.7, L1451–1598)

Blocker: nothing emits the §8.6 censoring family (`time_to_first_fill_ms`, `n_ttf_*`) — `FillTimeSummary` has no producer (L1539–1544). Runs 4–5 dropped (D31, leg P 796 CC = $98.70 > $60 ceiling) (L1552–1560). Maker fill deliberately unmodelled (L1473–1477). `requote_min_ms` 800 / `hedge_ack_wait_ms` 600 derived from the one smoke run's 397/763 ms acks (L1478–1483). Card cannot be run with `tt_enabled = true`: `E_tt` ≈ +29,430 bps on testnet (L1463–1468).

### 3.4 Bybit 33-TT/33-MT — never run (TESTNET_RUNS.md §3.7, L2044–2101)

No Bybit testnet keys (ROB-112), no Bybit runner. Blockers: `mt_mode()` requires `passive_leg == Spot` (D25 says perp rests) (L2052–2057); `basis_run` resolves legs from `hl_meta` only (L2062–2067); no venue-neutral OMS adapter (ROB-115b) (L2068–2071); `fees.mt` computes 15.5 bps where Bybit truth is 12.0 (L2072–2077). `hedge_ack_wait_ms` 250 / `requote_min_ms` 300 are defaults from an unmeasured venue (L2083–2086).

### 3.5 Mainnet M3.5 — draft only (MAINNET_RUNS.md)

Proposed limits: $100/order, $500/day, $25 max loss/day, pairs BTC/ETH/HYPE, 5 parents day 1, 1 concurrent, $250 unhedged, $250/leg, ≥$2,000 API wallet (L33–43). Modelled cost 23.12 bps/parent, $1.17 for five (L36). Unverified: mainnet acks (`hedge_ack_wait_ms` 600 carried from testnet), fee tier, 119-step IOC filling inside the touch "modelled not observed", `runcard::apply` loader (L419–453). Prediction to check: MT should post ~100% of the time on mainnet (perp `bbo` every ~100 ms) vs testnet's ~19% (L327–331).

### 3.6 TCA worked example (synthetic fixture, not a run) (research/tca_example_result.md L1–30)

HYPE parent, 45 HYPE, 3 leg-S fills: arrival basis +26.00 mid / +25.64 touch; achieved net +12.84; fees +8.51; slip vs target +2.16; legging 600.642 USD·s; A→B p50/p99 302/582 ms recv, 300/580 exch; tick-to-trade p50 8 ms; hedge fill ratio 3/6. **Synthetic inputs — demonstrates the pipeline only** (TCA L1495).

---

## 4. Venue mechanics discovered

### 4.1 Hyperliquid

| mechanic | finding | src |
|---|---|---|
| `scheduleCancel` (DMS) | Refused: "Cannot set scheduled cancel time until enough volume traded. Required: $1000000. Traded: $3918.75." (n=1, testnet 2026-09-29 12:23:52Z; equity $955.03). Venue DMS is not an MVP component; client watchdog is the protection (D15) | VENUES L306–329 |
| Minimum order | $10 per order, reduce-only included: a $2.7 reduce-only perp buy was refused [L§5e] | LATENCY_PLAN L384; TESTNET_RUNS L361–362 |
| Spot fee denomination | Spot **buy** fee taken in base (CC), spot **sell** in USDC → every OPEN nets short by the fee (7 bps of leg S) | TESTNET_RUNS L663–677 |
| Fees (testnet, tier 0) | spot taker 7.0 bps, perp taker 4.5 bps, confirmed on 4 parents; spot maker 4.0 unverified | TESTNET_RUNS L657–662 |
| Reply vs push ordering | post reply is strictly upstream of the fill push (same block); push +0.02…+12.51 ms after reply, 4/4 | LATENCY_PLAN L221–251 |
| Mixed spot+perp in one `order` action | Verified legal [V]: `orders` is an array, each with own `a`; `hl_sign::encode_order_action` already takes a slice; one call-site change (`runner.rs:1415`) | LATENCY_PLAN L281–297 |
| In-block ordering | Decided by arrival at the API, not timestamp [V]; no block-boundary amplification of a Δ-ms head start | CONNECTIVITY L79–90 |
| `l2Book` semantics | ~5.3 s venue-wide snapshot tick, not change-gated, ≤20 levels/side; `bbo` change-gated L1 only | VENUES L340–401, L134–139 |
| Rate limits (HL) | ~10K requests on a new account then 1 request per $1 traded; unified account ≤50K actions/day [R] | PLAN L130 |
| Spot↔perp mapping | Rule: base name = perp coin, else strip leading `U`; 19 mainnet pairs match, 10 are traps (ratio 30.5×–1769×); pin pair index + asset id, never the base token; indices drift between envs (HYPE 107 mainnet / 1035 testnet) | VENUES L44–76, L293–294; MAINNET_RUNS L117–127 |
| Testnet fills | Spot touch levels are single orders (`n=1`) holding 98–250 CC; IOC spans 2–3 levels of a ~30-bps geometric grid | rob171 L11–16; TESTNET_RUNS L644–649 |
| Admission floor | `--size-usd` exactly $12.50 floors `target_qty` to 0 (BelowMinNotional); need `lot_eff × mid_S × (1+margin)` | rob171 L55–68 |
| Per-order guard | `--max-order-usd` is per **order**, preflighted on the whole package; leg P notional inflated ~4× on the testnet pair | TESTNET_RUNS L798–805 |
| Recorder | Venue reason is only on the `phase: reply` record in `venue_error`; can be missing even on a non-null error | VENUES L331–338 |

### 4.2 Bybit v5 [X] unless noted (VENUES.md §5.4–5.7)

| mechanic | finding | src |
|---|---|---|
| Fees VIP0 | spot maker = taker = **10.0 bps**; linear maker 2.0 / taker 5.5 → resting the perp wins the fee term at every published tier (D25); PRO/MM rates unpublished | VENUES L1159–1196 |
| Spot fee denomination | buy fee in base, sell fee in quote (same asymmetry as HL) → hedge quantity gross-up (D32) | VENUES L1200–1212 |
| Minimums | spot `minOrderAmt` $5, linear `minNotionalValue` $5; minimum is an **order-entry** check, not a fill check: 45/1000 HYPEUSDT linear prints below $5 (smallest $0.8625 = one step), 0/1000 on ETHUSDT (one step $26.71) [M ROB-229, 2026-09-30T01:10Z] | VENUES L1224, L1476–1496 |
| Rate limits | per second per UID, per-endpoint token bucket; linear create/cancel 20/s, amend 10/s; default tier 10/s futures, 20/s spot; IP breach 3000 rps; `10006` "Too many visits" | VENUES L1323–1381 |
| Order entry | ack (`retCode 0`) is neither a fill nor a live order; requote = cancel+create; reduceOnly not allowed on spot (D28) | DECISIONS L2463–2469; TESTNET_RUNS L1947–1948 |
| Batch | ≤20 orders/request linear, 10 spot; WS trade API excludes demo trading | VENUES L1305–1307 |
| Tick/step | spot BTC tick 0.1 / ETH,HYPE 0.01; qtyStep spot BTC 1e-06, ETH 1e-05, HYPE 0.001; linear BTC 0.001, ETH 0.01, HYPE 0.01; max leverage 150×/150×/75× | VENUES L1222–1225 |
| Unknowns | shared rate buckets, crossing-PostOnly status, amend priority, orderLinkId reuse, order-vs-execution stream ordering, whether 10006 drops the socket, reduceOnly on spot retCode | rob190 L198–214 |

---

## 5. TCA metrics defined (TCA.md, 1694 lines) — status: defined, none computed on real fills

| § | metric family | key fields | measured yet? |
|---|---|---|---|
| 1 | Arrival snapshot at admission (`mid_spot_arrival`, B_mid, B_touch) | L133 | derived only (mid bracket from `target_qty`, TESTNET_RUNS L650–656) |
| 2 / 2.5 / 2.6 | Target basis; time-weighted average market basis over life; liquidity-adjusted basis (needs per-leg ladders on `delta_sample` — engine change, Q11) | L188, L222, L301 | no; §2.6 uncomputable today (L1683–1694) |
| 3 | Achieved basis gross/net from leg VWAPs | L395 | no |
| 4 | Fees (`fees_actual_cbps`, fee token in kind) | L445 | fee bps confirmed from fills, not via TCA |
| 5 / 5.1 | `slip_vs_target` = entry buffer + exec slip vs arrival touch + fee variance (exact integer identity) | L499, L528 | no |
| 6 | Markouts per leg, basis, pair (mid-to-mid = headline; from-fill incl. pay-up), 1/5/30/60 s | L559–684 | no |
| 7 | Legging exposure = ∫`unhedged_usd`dt (D1), `legging_sample_ms` 100, tolerance 5000 USD·s | L685 | no |
| 8 | Fill rate, completion, maker ratio, mode mix, residue/carry, time-to-fill with censoring (`n_ttf_filled/censored`) | L750–977 | no producer for §8.6 (TESTNET_RUNS L1539–1544) |
| 9 | Latency: `tick_to_trade_ms` (recv→decision→send), `signal_to_hedge_send_ms`, `A_to_B_recv_ms` (sets `max_legging_time_ms` p99), `A_to_B_exch_ms`, `notify_lag_ms`; snapshot ages `book_age_ms` + `depth_age_ms` (two ages, D21) | L978–1033 | partial: send→reply only, from JSONL re-derivation |
| 10 | Ops counters: `orders_sent`, `cancels_sent`, `sweeps`, `catchup_escalations`, `unwinds`, `ignored_events`, `rejects_by_reason{}`, cancel-to-fill, `budget_per_usd_traded`, `skips{}` (exactly 10 labels, ROB-268/D37), `watchdog_fired`, `venue_dms_armed`, `crash_residue_usd` | L1037–1173 | skips emitted since ROB-268; `venue_dms_armed` = false measured |
| 13 | Aggregation: testnet never aggregates into a performance number; n ≥ 30 for a headline, ≥ 100 for a p99 | L1392–1440, L1643–1648 | — |

Worked example (§14): synthetic HYPE parent reproduces the pipeline; ROB-99 addendum: time-weighted avg basis +25.18 bps vs sample-weighted +25.05, time-to-first-fill 784/901/1014 ms on 3 posted children (research/rob99_addendum_result.md).

---

## 6. Decisions list (DECISIONS.md, one line each; line = header)

- **D1** (L24) Legging integrand is `unhedged_usd = |qty_S − qty_P| × mid`, not `abs(delta_usd)`.
- **D2** (L55) Net achieved basis: `fees_actual_cbps = cbps(fee_total_usd, N_filled)`, independent of VWAPs.
- **D3** (L78) Three sign families: basis, edge (+ = favourable), cost (+ = worse).
- **D4** (L103) Denominator of per-parent bps = `mid_spot_arrival`, frozen at admission.
- **D5** (L121) Fixed point: Px/Qty i64 at 1e-8, notional i128 at 1e-16, bps as centi-bps.
- **D6** (L139) Markouts still taken at 30/60 s after a parent completes — property of the fill.
- **D7** (L158) Both pair markouts reported (mid-to-mid headline, from-fill labelled).
- **D8** (L183) TCA field names are the SCENARIOS contract; drift reconciled, TCA.md canonical.
- **D9 / D9-A** (L219, L266) No latency worth buying beyond Tokyo; re-baselined to the Vultr box: API is two edge classes, hold the near one.
- **D10** (L352) ROB-32 testnet mechanics pair = UETH/USDC @1137 ↔ ETH perp.
- **D11** (L403) CLOSE uses its own `close_threshold_bps`, forced on kill/horizon.
- **D12** (L453) `close_threshold_bps` default −11.5 = −(fees_mt 8.5 + hedge_slip 3.0).
- **D13** (L496) `entry_basis_mode = off` is OPEN-only; does not suppress the CLOSE threshold.
- **D14** (L531) Console's three undefined TCA numbers defined (+ schema addition).
- **D15** (L656) Client-side watchdog W1–W6 + resting caps replace the venue DMS HL refuses below $1M volume.
- **D16** (L773) 22a runs on CC/USDC @1216 ↔ CC perp (197); size = one `lot_eff`.
- **D17** (L875) ED §8.4 formulas R1/R2/R3 (unhedged cap, per-leg cap, liquidation buffer) and F1–F3 kill flatten.
- **D18** (L1001) v1 equity pairs: five HIP-3 names vs EXANTE spot, with a 4-part session rule.
- **D19** (L1128) 22b MT runnable on testnet only with `tt_enabled=false` (E_tt ≈ +29,430 bps); same pair as 22a.
- **D20** (L1220) Kill-flatten side comes from the venue's signed position; a reduce-only refusal stops the flatten.
- **D21** (L1283) `stale_halt_ms` = 9000 (min 8000, max 30000) after the 5.3 s `l2Book` tick; two ages per record.
- **D22** (L1389) Five SCENARIOS divergences resolved; `entry_threshold_bps` floor → −200.
- **D23** (L1681) S2 wait semantics, §8.4 rule-3 firing, reachable fixtures; `premium_guard_standdown` is testnet-only.
- **D24** (L2052) M3.5 limits to ask Robert, BTC @142 first, guards armed on mainnet.
- **D25** (L2157) Bybit `passive_leg = perp` on every pair and every published tier (fee gap 2.0–3.5 vs 0–1.5 bps).
- **D26** (L2283) 22a rerun was blocked by the card: cap 60, `--size-usd` 13.2; two engine follow-ups.
- **D27** (L2388) `delta_usd` = net signed base qty × hedge-leg mid (1:1 base hedge reads 0).
- **D28** (L2463) Bybit: ack ≠ fill ≠ live order; hedge on `cumExecQty` delta by `orderId`; requote = cancel+create; no reduceOnly on spot.
- **D29** (L2570) Run-1 silence: completion test must include the `min_notional` disjunct; an at-target S1 parent must publish a wake.
- **D30** (L2653) Hedge the base the venue *credited* (net of the in-kind spot fee), option (a).
- **D31** (L2737) 22b runs 4–5 (2× clip) dropped — per-order ceiling binds on leg P; ceiling change is a Robert ask.
- **D32** (L2809) ED §3P: perp-passive quoter/hedge on Bybit, fee-in-base gross-up, residue inversion.
- **D33** (+follow-up L3060) Re-value OPEN scenarios for D30, pin runner fees to 0, fix S8 wording.
- **D34** (L3160) Rule-3 trigger = `hedge_size(...).qty == 0`; kill-flatten dust band on HL is `hedge_size`'s two gates on the floored size.
- **D35** (L3370) SC-09B re-quote is the floored child; `dust_qty` at parent end is the whole bucket.
- **D36** (L3470) Rule 3 applies only to a non-empty excess bucket.
- **D37** (L3537) `skips{}` has exactly ten emitted keys; `stale_depth`, `resting_cap`, `unhedged_gate`, `liq_buffer`, pull reasons are PROPOSED, not emitted.
- **D38** (L3607) A TT-only parent that never triggers records `BelowThreshold`.
- **D39** (L3668) Bybit testnet run card: ETHUSDT, postable-child rule, leg order, guards.

---

## 7. Competitor findings (docs/competitors/COMPETITOR.md, UX-PATTERNS.md)

Source: two screen recordings, 4m34s + 1m13s, 13 frames, no audio, brand not visible (COMPETITOR L3–6). **No execution latency or fill-rate measurement of the competitor exists** — only what the UI shows.

- Platform: institutional multi-venue (binance, bybit, okex, bitget, kraken, bitstamp, gdax, lighter, kucoinfutures, hyperliquid); spread trading is one order type among SMART/SWEEP/TWAP/SPREAD/PAIRS (L8–12, L47).
- Algo shape visible: `Execution Setting: Make / Make` (both legs passive), `Lead Aggression: Aggressive` / `Balancing Aggression: Far_peg`, `Reprice Increment`, `Lead/Balancing BPS Offset`, `Max Quote Distance`, `Max Leg Risk` (=our `max_imbalance`), `Cross Mode`, `Lead Reduce Only`, `Sweep Trigger`, `Min/Max Post Size` (L61–65, L84–88). State banner `target_wait (contra balancing)` (L74).
- One TCA screen sample (HOOD-USDT.PERP, binancefutures): 100% filled, Maker 100%, fees 0.0000 bps, Arrival Spread −0.0171%, Avg Market Spread −0.0667%, Executed −0.1092%, Slippage **+9.2123 bps** total; time-to-fill min 19 ms / avg 7.5 s / max 1.2 m; Fill Rate Taker 0.0% / Maker 73.6%; liquidity-adjusted spread at depth 0.01/0.005/0.001% (L96–111).
- An order shown with runtime 19h 9m and 200,000 LIT sell across okex/lighter (L73–83).
- What we take: dual book with live spread, spread-as-chart, MKT|TGT, Max Leg Risk on ticket, flip legs, TCA page kept as-is (UX-PATTERNS A1–A15, §C). What we add: legging exposure USD·s, markouts 1/5/30/60 s, tick-to-trade and fill→hedge p50/p99/p999 (§C L62–64).
- PLAN §1 quality target: slippage vs target spread **1–5 bps**, per-parent TCA (PLAN L11–12). PLAN §4: TCA-vs-competitor first report 10.10, parity ~15.10 (L55).

---

## 8. Open questions and known unknowns the team lists

**Latency / order path**
- Mainnet order-path latency unmeasured; only arithmetic over block cadence + [R] (LATENCY_PLAN L63–65). ROB-108 post-ack probe closes it.
- Software path (a)–(b) 0.03–0.12 ms is [R/U], unmeasured (CONNECTIVITY L13, L52–55).
- HL clock discipline not measured — one-way levels are upper bounds (LATENCY_PLAN L188–191).
- Whether `fast: true` / `nSigFigs` change `l2Book` cadence untested (VENUES L413–414).
- Whether two IOCs in one WS frame land in the same block and in what order (ED §10 Q6, L2011–2013); `tt_same_block` never run (LATENCY_PLAN L408).
- Does `modify` preserve queue priority and `cloid` (ED §10 Q2).
- Edge-class share 71/18/11% is a property of this resolver on 2026-09-29; re-measure per host (CONNECTIVITY L363–367).

**Execution quality**
- Legging p99 distribution (`A_to_B_recv_ms`) never measured; `max_legging_time_ms` 2000 is a research value (TCA L1012–1016; ED Q3).
- Passive fill rate and markouts on HL spot — zero maker orders posted; `fee_spot_maker_bps` 4.0 unverified (TESTNET_RUNS L661–662; ED Q4).
- No TCA record has ever been emitted by a runner (TESTNET_RUNS L777–787); §8.6 censoring family has no producer (L1539–1544); §2.6 liquidity-adjusted basis needs per-leg ladders (TCA L1683–1694).
- `ref.book_age_ms` on leg S routinely > 1000 ms? (D26 F3) — cannot be answered from logs (TESTNET_RUNS L777–781).
- Spot fill fee token (in-kind vs quote) confirmed only on testnet HL; Bybit fee tier and whether testnet charges VIP0 unknown (TCA L1625–1634; TESTNET_RUNS L2099–2101).

**Venue facts**
- HL DMS: per-address vs per-account counter, decay, mainnet-only? (VENUES L315). USDC/USDT rate never measured → wrapper premium not decomposable (L296–304, L509).
- Bybit: 8 order-path unknowns (rob190 L198–214), maintenance-margin rule, sub-minimum partial fills on our own resting perp (VENUES L1638).
- Exact HL reject strings for ALO-would-cross and rate-limit are `[unverified]` (ED Q11, L2028–2039).

**Risk parameters**
- `max_imbalance_usd` formula units inconsistent (σ in bps needs 1e4 factor): $196K vs $25K readings; deferred to M4 (MAINNET_RUNS L432–440). Six of nine HL pairs have no `max_imbalance_usd` row (VENUES L455–458).
- `entry_threshold_bps` / `close_threshold_bps` levels need a multi-day baseline and funding forecast (VENUES L512–513; ED Q8).
- `wrapper_premium_alert_bps` is dead code today (TESTNET_RUNS L1486–1487).
- +400 CC standing spot from the ROB-169 incident is still open on the testnet account (TESTNET_RUNS L682–683).

---

## 9. Current work in progress / milestone status (PLAN.md §4, §10, §11; as of 30.09 05:15)

| milestone | due | status per PLAN L43–55 and evidence above |
|---|---|---|
| M0 foundation | 28.09 | done (bench baseline p50 61 ns / p99 173 ns, PLAN §11 18:21) |
| M1 HL market data | 29.09 | done (bbo channel, hl-book, hl-meta merged) |
| M2 HL order entry | 30.09 | signing 11/11 SDK vectors (ROB-12); WS post + OMS on testnet — evidenced by 4 live parents |
| M3 HL-BASIS-MT | 30.09 | TT path proven live (4 parents); MT happy path in tests (ROB-200) but **never on venue**; 22b blocked on §8.6 producer |
| M3.5 HL mainnet small size | 01.10 | DRAFT card; awaiting Robert's limits (ROB-108), guard/pre-flight (ROB-110), allowlist replacing testnet asset-identity guard |
| M4 TCA + latency | 02.10 | TCA crate part 1 merged (ROB-23a, i128 USD fix); no runner emits TCA; latency plan ROB-272 delivered |
| M5 Bybit | 03.10 | books/fees/order-entry docs done (ROB-26/190/229/266); no keys, no runner, `mt_mode` blocker |
| M6 multi-venue, M7 Exante equities, M8 OKX/Lighter/Aster, M9 TCA vs competitor | 05–15.10 | research only (ROB-123 equity perps, D18) |

In work (PLAN L146–159, 30.09): w1 ROB-269 (D34 kill-flatten rule 3); w2/w3 idle waiting on the lead's ROB-115b OMS interface; quant ROB-272 latency plan (delivered), ROB-266 in review, ROB-273 skips vocabulary queued; lead: SC-09B follow-ups, `parent_admit` wiring, rule-3 arm, ROB-115b, ROB-110 after Robert's numbers.

Lead decisions of note (PLAN §11, L161+): custom msgpack encoder + k256 (28.09); `bbo` as the algo trigger feed; bench gate median-of-5 with p50 ×1.3 / p99 ×2.0 fail; spot pair pinned explicitly per env; UI served only on WireGuard 10.8.0.1:8090; PLAN §2 target: hedge on the first fill signal, < 1 block over exchange time, internal tick-to-trade 10–100 µs p99, no kernel bypass or priority fees (L16–25).

Robert's decisions (PLAN §7/7a, L88–119): pairs HYPE/BTC/ETH; everything parametrised from the console with scopes default/pair/parent; Tokyo box = this Vultr server (ROB-34 cancelled 29.09 08:33); multi-venue mode in scope (one venue per leg, ROB-100), leg splitting backlog (ROB-101).

---

## 10. Design assumptions — validated vs not (reviewer's scorecard)

| assumption | status | evidence |
|---|---|---|
| Our software path is negligible vs venue | **validated** (structurally; software itself unmeasured) | LATENCY_PLAN §1.1; CONNECTIVITY §1 |
| ~700 ms per HL leg is blocks, not us | **validated** on testnet (6.8 blocks × 102 ms; 717–769 ms venue-stamped) | LATENCY_PLAN §0–1 |
| Mainnet will be faster on the order path | **not validated; predicted no** (feed 65–70 ms faster only) | LATENCY_PLAN L31–46 |
| Hedge on earliest of reply/update/stream saves time | **falsified as a saving** (reply wins 4/4); fusion kept as tail insurance | LATENCY_PLAN §2 |
| Perp IOC hedge is free | **validated** (0.00 bps walk 4/4 + ROB-104/171/205 probes) | TESTNET_RUNS L639–641 |
| Passive spot leg on HL is worth it (MT edge) | **not tested** — zero maker orders; edge = the 11–26 bps ladder walk + 3 bps fee delta on a testnet grid that does not exist on mainnet | TESTNET_RUNS L830–835 |
| Spot books on HL are wide (passive-on-spot thesis) | **questioned** — majors 0.06–0.12 bps | VENUES L86–88; PLAN §11 |
| Bybit passive leg = spot | **reversed** to perp by fees + fill probability (D25); markout-robust | VENUES §5.3–5.4 |
| Venue DMS as cleanup path | **falsified** ($1M volume gate) | VENUES §1.11 |
| `l2Book` is a sub-second book feed | **falsified** (~5.3 s tick) | VENUES §1.12 |
| 1:1 base hedge leaves the pair flat | **falsified** on OPEN (in-kind spot fee, 7 bps short) | TESTNET_RUNS L663–677; D30 |
| $100 clip fills inside the touch on mainnet | **modelled only** (0/1,389 depth samples below clip; no order sent) | LATENCY_PLAN §3.3; MAINNET_RUNS L445–446 |
| `max_legging_time_ms` 2000 | **uncalibrated** (n=4 inside it) | TESTNET_RUNS L629–631 |
| Fee schedule 11.5 bps TT | **validated** on testnet; mainnet tier unconfirmed | TESTNET_RUNS L657–662 |
