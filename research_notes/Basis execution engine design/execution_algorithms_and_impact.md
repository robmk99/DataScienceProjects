# Optimal Trade Execution Algorithms and Market Impact Models (Crypto CEX/DEX focus)

Scope note: notes compiled 2026-09-30. Sources marked **[EQUITIES/FUTURES]** are from non-crypto markets and may not transfer. Sources marked **[CRYPTO]** are crypto-specific. Where a formula is canonical (Almgren-Chriss, Kyle-Obizhaeva) it is cited to the original paper.

---

## Q1. Canonical execution algorithms: decision rules and parameters

### Takeaway
The crypto practitioner stack (Talos, Anboto, Coinbase Prime, Hyperliquid native) is the same menu as equities: TWAP, VWAP, POV, IS/Almgren-Chriss, Iceberg, Pegged, Sniper. The concrete, publicly documented decision rules with actual parameters are Hyperliquid's native TWAP (straight-line target, 30 s minimum sub-interval, 3% slippage cap per suborder, 3x catch-up cap) and Anboto's IS (risk-adjusted cost = E[IS] + lambda * Vol[IS], Almgren-Chriss trajectory). Talos argues VWAP only beats TWAP when the intraday volume forecast is reliable (they report 65-75% R^2 for volume, ~80% for spreads, 25-35% for volatility across ~75 spot/perp assets).

### Cited Findings

**TWAP (Hyperliquid native, on-chain, concrete rules)** [CRYPTO]
- Suborders "sent at a fixed interval, calculated from the total size and running time inputs"; sub-interval as short as every 30 seconds for large/short orders; "Running time can be set from 5 minutes to 7 days, with a $100 minimum total order size." — [Hyperliquid docs: Order types](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)
- Each suborder targets elapsed_time / total_time * total_size (a straight-line schedule). — [Chainstack: Hyperliquid TWAP orders](https://docs.chainstack.com/docs/hyperliquid-twap-orders)
- "A suborder is constrained to have a max slippage of 3%." — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)
- Catch-up rule: if suborders underfill (wide spread, thin book), "the TWAP will try to catch up to this execution target during later suborders. These later suborders will be larger but subject to the constraint of 3 times the normal suborder size (defined as total TWAP size divided by number of suborders)"; if too many suborders fail, the TWAP may not fully complete. — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)
- TWAP and other suborders "do not fill during the post-only period of a network upgrade." — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)
- Hyperliquid later added trigger prices, dynamic intervals and week-long durations to TWAP. — [Crypto Briefing](https://cryptobriefing.com/hyperliquid-twap-orders-onchain-upgrade/)
- ALO (post-only): "An order that is added to the order book but doesn't execute immediately. It is only executed as a resting order." Chase orders (a post-only variant) "rest one tick above the best bid (for buys) or one tick below the best ask (for sells)." — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)

**TWAP vs VWAP decision rule (Talos)** [CRYPTO]
- TWAP "distributes execution evenly over time, assumes that slicing risk linearly reduces signaling and footprint, is robust and simple, but is agnostic to the intraday liquidity curve"; VWAP "accelerates in periods where predicted market volume is higher." — [Talos: VWAP or TWAP for crypto execution](https://www.talos.com/insights/vwap-or-twap-for-crypto-execution-a-market-impact-perspective)
- "When volume predictive power is weak or unstable across regimes, a VWAP can systematically overweight the wrong time windows, in which case a liquidity-naive TWAP can be the superior algo." "A VWAP schedule is only as good as its volume forecast." — [Talos](https://www.talos.com/insights/vwap-or-twap-for-crypto-execution-a-market-impact-perspective)
- Talos forecast accuracy across ~75 spot/perp assets over one year: volume 65-75% R^2, spreads ~80% R^2, volatility 25-35% R^2; daily recalibration materially improves vs 5-day fixed forecasts; percent of daily volume "can nearly double during the US open versus typical periods". — [Talos: Execution alphas in crypto](https://www.talos.com/insights/execution-alphas-in-crypto-markets-predicting-volume-volatility-and-spreads-to-reduce-slippage)

**Coinbase Prime** [CRYPTO]
- Prime offers TWAP, VWAP, iceberg, "basis" and adaptive strategies via a Smart Order Router aggregating exchanges, OTC desks and market makers; "A TWAP order type will execute roughly the same quantity in each given timeframe, while the VWAP order type will execute dynamically different quantities across timeframes based on the historical volume profile." — [Coinbase Prime](https://www.coinbase.com/prime); [Coinbase Help: VWAP algo](https://help.coinbase.com/en/prime/trading-and-funding/vwap-order-type)

**Talos algo menu** [CRYPTO]
- Talos lists Iceberg, Pegged, Sniper and TWAP (plus TCA benchmarks vs TWAP/VWAP/IS). — [Talos Trading](https://www.talos.com/our-solutions/trading)

**Anboto IS (Almgren-Chriss in crypto)** [CRYPTO]
- Anboto suite: TWAP, VWAP, Iceberg, IS and POV across CeFi and DeFi. — [Anboto](https://www.anboto.xyz/)
- IS objective: "Risk adjusted cost = Average impact cost + Urgency * risk = Expected(IS) + lambda * Volatility(IS)"; higher lambda -> shorter horizon. Worked crypto example: lambda=0.13 -> optimal horizon 0.52 days, 30 bps risk-adjusted cost; lambda=0.01 -> 0.32 days, 35 bps (as extracted; the lambda/urgency labelling in the article is internally odd, treat the numbers as illustrative). Uses arrival mid at submission as benchmark; runs 24/7 with no market breaks. — [Anboto: Introducing IS](https://medium.com/@anboto_labs/introducing-is-to-our-algo-suite-1ee0b36285e9)
- Anboto's IS "adapts the AC framework to the crypto market by using real-time market data for key parameters and making adjustments to address the limitations of the AC model." — [Anboto: Deep dive into IS / Almgren-Chriss](https://medium.com/@anboto_labs/deep-dive-into-is-the-almgren-chriss-framework-be45a1bde831)

**RL / adaptive vs TWAP/VWAP on BTC** [CRYPTO]
- RL-Exec (BTC-USD LOB replays, train Jan 2020, test Feb 2020, with endogenous transient impact/resilience, partial fills, maker/taker fees, latency): outperforms TWAP and a top-20-level book-liquidity VWAP by +2-3 bps at 30-min horizon, +7-8 bps at 60 min, +23 bps at 120 min (Wilcoxon signed-rank, BH-FDR). "TWAP/VWAP remain ubiquitous for capacity and simplicity but are state-agnostic and typically realize negative expected P&L once spreads and impact are counted." — [arXiv 2511.07434](https://arxiv.org/abs/2511.07434)
- Safe RL cross-market execution paper: VWAP IS about -2.45 bps vs TWAP; safe RL agent about -2.15 bps. — [arXiv 2510.04952](https://arxiv.org/html/2510.04952v1)

### Inferences
- The straight-line target + catch-up cap in Hyperliquid's TWAP is a good minimal template for a crypto TWAP: target_qty(t) = Q * t/T; child = max(0, target - filled), capped at 3x nominal child; skip/limit child when book slippage exceeds cap.
- Given Talos's R^2 numbers, a VWAP profile is defensible for BTC/ETH majors (volume predictable, "US open" doubling), but for thin alts TWAP is safer.
- IS/AC is only as good as impact/vol calibration; Anboto's approach of feeding real-time sigma and volume into AC each day is the practical route.

### Gaps
- No public source gives Talos/Coinbase Prime/Anboto child-order sizing, randomization, or passive/aggressive switching rules in detail (Anboto TWAP deep-dive article returned 403).
- No public documentation found for Binance/Bybit/OKX native TWAP algo parameters (they exist as "TWAP"/"algo order" endpoints; not fetched here).

---

## Q2. Market impact models and crypto-measured coefficients

### Takeaway
Square-root law I = Y * sigma * (Q/V)^delta with delta ~ 0.5 is confirmed on Bitcoin (MtGox 2011-2013, 1M+ metaorders with true trader IDs, Y ~ 0.9 in daily-vol/daily-volume units) and is the base of Talos's production impact model (with a sigmoid exponent modulation). A 2025 Binance BTC/ETH study using *reconstructed* metaorders found exponents ~0.1, but the authors flag this may be an artifact of reconstruction. Post-metaorder decay: ~1/3 of peak impact reverts (permanent ~2/3) for correlated flow; near-zero permanent impact for isolated/uninformed metaorders. Direct measurements of Binance order-book refill time after a sweep were not found; equity results give ~20 best-limit updates / ~20 s, and Amberdata reports 30-60 min reversion of depth after extreme imbalance breaks on Binance BTC/FDUSD.

### Cited Findings

**Square-root law on Bitcoin (Donier & Bonart 2014)** [CRYPTO]
- Data: MtGox BTC/USD, Aug 2011 - Nov 2013, all 13-14M trades with complete trader IDs; >1M metaorders. Peak impact I(Q) ~ +/- Y * sigma * (Q/V_D)^delta, delta ~ 0.5 "over 4 decades"; Y ~ 0.9 (sigma = daily volatility, V_D = daily volume); mean Y0 = 0.9, std 0.35, approx Gaussian; raw (un-normalized) prefactor ~4.5e-2. — [arXiv 1412.4503 (ar5iv)](https://ar5iv.labs.arxiv.org/html/1412.4503)
- Impact path: "the square-root impact holds during the whole trajectory of a metaorder and not only for the final execution price": I_path(r,Q,mu) = I(rQ,mu), i.e. I(t) = f(mu) t^delta. — [arXiv 1412.4503](https://arxiv.org/abs/1412.4503)
- Execution-rate dependence: I_exec(Q, mu_V) ~ Q^delta / mu_V^delta' with delta ~ 0.5, delta' ~ 0.4; slower execution measured *larger* impact because "slower execution gives other market participants opportunity to detect the same signal". — [arXiv 1412.4503 (ar5iv)](https://ar5iv.labs.arxiv.org/html/1412.4503)
- Decay: permanent component ~2/3 of peak for typical (correlated) trades; for isolated "uninformed" metaorders the mechanical permanent impact is "close to zero", i.e. "almost complete long-term decay of impact". Non-stationarity is mostly absorbed by the ratio sigma_D / sqrt(V_D). — [arXiv 1412.4503 (ar5iv)](https://ar5iv.labs.arxiv.org/html/1412.4503)

**Talos production impact model (TMI)** [CRYPTO]
- Three components: (1) spread cost = c1 * S (linear in bid-ask spread, independent of size/duration); (2) physical impact ~ sigma * pi^phi_p(pi), where pi = Q/(V*T) is participation over the horizon, sigma intraday vol, and phi_p(pi) a sigmoid that equals ~0.5 (square-root) in the mid range and transitions with participation; (3) time risk from volatility and duration. — [Talos: Understanding market impact in crypto](https://www.talos.com/insights/understanding-market-impact-in-crypto-trading-the-talos-model-for-estimating-execution-costs)
- Talos claims the plain square-root law underestimates impact by ~4 bps in the 0-0.5% participation regime; "over 26%" of validation samples fall in the 0-5 bps actual-slippage range. Example inputs: $10M BTC buy over 4 hours = 2% participation, 0.9 bps spread, 2.8% daily vol, $500M expected volume. No fitted coefficients disclosed. — [Talos](https://www.talos.com/insights/understanding-market-impact-in-crypto-trading-the-talos-model-for-estimating-execution-costs)

**2025 Binance study contradicting sqrt law (reconstructed metaorders)** [CRYPTO]
- Binance aggTrades BTC/USDT and ETH/USDT; calm regime Aug-Sep 2025, stress regime Nov 2025 (-36% from ATH); 44.4M trades / 921K reconstructed metaorders (BTC calm), 79.0M / 1.76M (ETH calm); metaorders reconstructed with the Maitrier-Loeper-Bouchaud (2025) heuristic since Binance gives no trader IDs. OLS size exponent 0.098-0.129 in all four asset/regime cells; "The square-root law is absent in all four experiments"; sigma rose 2.3x (BTC) and 1.3x (ETH) in stress. Caveat by the author: "without ground-truth trader IDs, whether low exponents reflect genuine market structure or the reconstruction heuristic remains indeterminate." — [GitHub SLMolenaar/crypto-market-impact](https://github.com/SLMolenaar/crypto-market-impact); contrasts with [Donier & Bonart](https://arxiv.org/abs/1412.4503)

**Kyle-Obizhaeva invariance (dimensional form)** [EQUITIES, but dimensionally generic]
- Impact G = (1/L) f(Z), L = (P V / (sigma^2 C))^(1/3), Z = (Q^3 P^2 sigma^2 / (V C^2))^(1/3); "Given the dollar size of a bet |PQ|, the only asset characteristic needed to measure market impact is the ratio of returns variance to dollar volume sigma^2/(PV)." Worked example: benchmark stock sigma = 200 bps/day, a bet of 1/4 daily volume costs 200/sqrt(4) = 100 bps; a stock with 8x volume, bet = 1/16 V costs 50 bps = 100 * 8^(-1/3). — [Kyle & Obizhaeva slides (Imperial)](https://www.imperial.ac.uk/media/imperial-college/research-centres-and-groups/cfm-imperial-institute-of-quantitative-finance/events/20160511-Kyle-Obizhaeva-Invariance-SLIDES-Imperial-45.pdf); [The Market Impact Puzzle (SSRN)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3124502)

**Propagator / transient impact** [EQUITIES/FUTURES]
- Propagator model (Bouchaud et al. 2004, Gatheral 2010): price = convolution of memory kernel G with instantaneous impact of trading rate; empirically G(t-s) ~ (t-s)^(-beta), 0 < beta < 1; single-trade response concave (approx square root) in size and decays as a power law. — [Lillo UCL lecture](http://www.cs.ucl.ac.uk/fileadmin/user_upload/lilloUCL2019.pdf); [arXiv 2510.06879](https://arxiv.org/pdf/2510.06879); [priceprop calibration library](https://github.com/felixpatzelt/priceprop)
- Resilient LOB models (Obizhaeva-Wang style): resilience modeled as exponential recovery of limit-order volume or of the bid-ask spread; optimal strategies match the resilience rate (block-shaped and general-shape LOB versions). — [arXiv 0708.1756](https://arxiv.org/abs/0708.1756); [arXiv 1409.7269](https://arxiv.org/pdf/1409.7269)

**Order-book resilience / refill speed**
- [EQUITIES] After an aggressive order, "spread and depth can return to their sample average within twenty best-limit updates"; a separate equity study finds replenishment within ~20 seconds. — [arXiv 1602.00731](https://arxiv.org/pdf/1602.00731); [Emergent Mind: Order Book Resiliency](https://www.emergentmind.com/topics/order-book-resiliency)
- [CRYPTO] Binance BTC/FDUSD, Jul 1-Aug 12 2025 (50,526 minutes): depth within 10 bps of mid peaks $3.86M at 11:00 UTC, troughs $2.71M at 21:00 UTC (1.42x ratio); reversion time of depth after extreme imbalance breaks: 30-60 minutes; "Seven of the ten worst liquidity periods occur at 21:00 UTC". — [Amberdata: Rhythm of liquidity](https://blog.amberdata.io/the-rhythm-of-liquidity-temporal-patterns-in-market-depth)
- [CRYPTO] In the Oct 2025 liquidation event (~$19B liquidated) "top-of-book depth in Bitcoin fell more than 90 percent intraday on some venues". — [HFT Advisory Substack](https://hftadvisory.substack.com/p/before-during-and-after-the-fill)

**Visible depth on major venues (for sizing Q/depth)** [CRYPTO]
- CoinGecko 2025: BTC depth within +/-$100 of mid ~ $8M per side on Binance (32% of a $20-25M median cumulative across top exchanges), Bitget ~$4.6M, OKX ~$3.7M; within +/-$10 only Binance exceeds $1M per side. ETH within +/-$2 (~0.1%): $15-16M cumulative across eight exchanges. — [CoinGecko Crypto Liquidity Report 2025](https://www.coingecko.com/research/publications/crypto-liquidity-report-2025)
- Kaiko: Binance 1% market depth for BTC exceeded $600M at the Oct 2025 ATH and fell below $400M by Dec 2025; Kaiko has moved away from 2% depth because it is "more frequently gamed", preferring 0.1% and 1%. — [CryptoSlate citing Kaiko](https://cryptoslate.com/bitcoin-struggles-to-reclaim-90000-amid-plummeting-liquidity-and-waning-market-depth/); [Kaiko liquidity concentration](https://research.kaiko.com/insights/the-crypto-liquidity-concentration-report)
- Kaiko: on 5 Aug 2024, "slippage for BTC-USD on major US exchanges tripled within hours"; $100k sell slippage on Coinbase peaks at 15:00 and 20:00 UTC. Average daily volumes: Binance $19B, Bybit $4B, Coinbase $2.8B. — [Kaiko: Moving markets](https://www.kaiko.com/resources/moving-markets-liquidity-and-large-sell-orders)

### Inferences
- Practical impact formula for crypto majors: I_bps ~ Y * sigma_daily_bps * sqrt(Q / ADV) with Y ~ 0.5-1 (Bitcoin-measured 0.9), then apply Talos-style floor of a few bps at very low participation (spread cost + the ~4 bps underestimation they report). Example: sigma=2.8%/day, Q/ADV=2%: 0.9 * 280 * sqrt(0.02) ~ 36 bps peak impact, of which ~1/3 reverts if flow is uninformed-like; conservatively budget the full number.
- The 2025 Binance exponent-0.1 result should not be used for sizing: it likely reflects the reconstruction heuristic; the true-ID MtGox result and Talos's validated model both support sqrt.
- Time-of-day sizing: for BTC on Binance, 10-bps depth of $2.7-3.9M means single child orders should be well under ~$0.5-1M to stay inside the first 10 bps; execute >$3M clips during 08:00-16:00 UTC (Amberdata's "golden hours").

### Gaps
- No public per-venue estimates of Y for Binance/Bybit/OKX spot or perps with true trader IDs (exchanges do not expose IDs); Talos does not disclose coefficients.
- No direct measurement found of "seconds to refill after a sweep" on a crypto venue; only the equity ~20-update/~20 s result and Amberdata's 30-60 min depth-band reversion (which measures imbalance normalization, not post-sweep refill).
- Webster's market-impact review (arXiv 2205.07385) could not be fetched beyond the abstract.

---

## Q3. Speed vs impact trade-off; horizon rule of thumb

### Takeaway
Almgren-Chriss formalizes the trade-off as minimizing E[cost] + lambda * Var[cost], giving a sinh-shaped schedule with characteristic time 1/kappa, kappa^2 = lambda sigma^2 / eta. Practitioner rules cluster around participation caps (Talos cites 5% baseline participation, 8-9% as an aggressive alternative; Anboto's IS examples land at 0.3-0.5 day horizons), and Kyle-Obizhaeva gives the scaling: cost grows like sqrt(Q/V) while timing risk grows like sigma * sqrt(T), so horizon T* scales with order size relative to ADV.

### Cited Findings
- Almgren-Chriss (2000): temporary impact h(v) = epsilon*sgn(v) + eta*v, permanent g(v) = gamma*v; objective min E(x) + lambda V(x); optimal trajectory x_j = X sinh(kappa (T - t_j)) / sinh(kappa T) with kappa^2 ~ lambda sigma^2 / eta_tilde; Anboto states this is the basis of their IS algo. — [Almgren & Chriss, Optimal execution of portfolio transactions (NYU)](https://www.math.nyu.edu/~almgren/papers/optliq.pdf) (PDF could not be fetched in this session; formulas as stated by Anboto's summary at [Anboto](https://medium.com/@anboto_labs/introducing-is-to-our-algo-suite-1ee0b36285e9) and the volume-dependent AC extension [arXiv 1701.08972](https://arxiv.org/pdf/1701.08972))
- Anboto IS: "Risk adjusted cost = Expected(IS) + lambda * Volatility(IS)"; examples: 0.52-day horizon at 30 bps risk-adjusted cost, 0.32-day at 35 bps. — [Anboto](https://medium.com/@anboto_labs/introducing-is-to-our-algo-suite-1ee0b36285e9)
- Talos TCA case: 1000+ parent orders, $1B notional, average duration 100 minutes, 5% baseline participation (8-9% under a more aggressive alternative), paid ~13 bps from arrival while market moved 42 bps on average during execution; 75% maker fills; strategy net buyer 85% of notional in an uptrend. — [Talos TCA](https://www.talos.com/insights/execution-insights-through-transaction-cost-analysis-tca-benchmarks-and-slippage)
- Talos model: time risk "captures the risk of missing the arrival price over the execution horizon", "particularly important for long-duration, low-participation trades"; example $10M BTC / 4h = 2% participation with $500M expected volume. — [Talos impact model](https://www.talos.com/insights/understanding-market-impact-in-crypto-trading-the-talos-model-for-estimating-execution-costs)
- Bitcoin metaorders: impact I ~ Q^0.5 / mu^0.4 -- faster execution (higher mu) had *lower* measured impact in the MtGox data, attributed to signal leakage during slow execution. — [arXiv 1412.4503 (ar5iv)](https://ar5iv.labs.arxiv.org/html/1412.4503)
- Kyle-Obizhaeva: cost of a bet of size Q/V daily volume ~ sigma_daily * sqrt(Q/V) (their 1/4-ADV example = 100 bps at sigma = 200 bps/day). — [Kyle-Obizhaeva slides](https://www.imperial.ac.uk/media/imperial-college/research-centres-and-groups/cfm-imperial-institute-of-quantitative-finance/events/20160511-Kyle-Obizhaeva-Invariance-SLIDES-Imperial-45.pdf)
- Hyperliquid TWAP hard limits: 5 min to 7 days; suborders no faster than every 30 s. — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)
- Amberdata sizing thresholds (Binance BTC, 10-bps depth): under $3M "adequate" at any hour (75th-percentile depth $3.69M); $3-5M target hours with depth > $4M; over $5M only 10 hour-slots reliably exceed $4M. — [Amberdata](https://blog.amberdata.io/the-rhythm-of-liquidity-temporal-patterns-in-market-depth)

### Inferences
- Rule of thumb for a sqrt-impact market with participation cap p: horizon T = (Q/ADV)/p days of volume; at Talos's 5% participation an order of 1% ADV takes ~0.2 day (~5 h in 24h crypto), 5% ADV takes a full day. Anboto's IS examples (0.3-0.5 day) are consistent with a few-percent-of-ADV order.
- Relative to visible depth: keep each child <= ~10-25% of the depth inside your slippage tolerance (e.g. for BTC on Binance, <$0.5-1M per clip inside 10 bps), and space clips longer than the refill time (equity ~20 s; crypto unknown but the 30 s Hyperliquid minimum is a reasonable floor).
- AC's kappa: with lambda chosen so the risk term equals impact at T*, T* ~ 1/kappa; Anboto's examples imply 1/kappa of order 0.3-0.5 day for their sample crypto order.

### Gaps
- No source gives an explicit crypto-validated table of "bps per % ADV". Talos and Anboto disclose only anecdotal totals (13 bps at 5% participation over 100 min; -0.58 bps average arrival slippage).
- Anboto's lambda units and the sign convention in their example were not verifiable (the article's numbers are odd: lower lambda paired with shorter horizon).

---

## Q4. Practitioner reports and slippage numbers in crypto

### Takeaway
Published crypto slippage numbers are sparse and mostly marketing-grade: Anboto reports -0.58 bps average arrival slippage (vs -10 to -15 bps for TradFi brokers), Talos reports ~13 bps arrival cost on $1B of TWAP parent orders in a trending market with 75% maker fills, and Kaiko/Amberdata report that $100k-size BTC slippage on Coinbase is a few bps and that timing alone changes cost by ~67% (3 vs 5 bps). OTC desks (Wintermute, GSR, B2C2, Cumberland) are the default for nine-figure tickets; they publish volumes and shares, not slippage curves.

### Cited Findings
- Anboto: "arrival slippage of -0.58bps compares favorably to the slippage of -10bps to -15bps by TradFi brokers", with "efficient volume participation and a high rate of passive execution". — [Anboto TCA article](https://medium.com/@anboto_labs/slippage-benchmarks-and-beyond-transaction-cost-analysis-tca-in-crypto-trading-2f0b0186980e)
- Talos TCA benchmarks: arrival = "the median 1-second mid-point top-of-book quoted price at the parent order submission time"; market TWAP/VWAP computed on the Talos consolidated book over the parent duration; case study: 1000+ parents, $1B notional, ~13 bps from arrival, beat both interval TWAP and VWAP, market moved 42 bps average, 75% maker fills, 100-min average duration, 5% participation. — [Talos TCA](https://www.talos.com/insights/execution-insights-through-transaction-cost-analysis-tca-benchmarks-and-slippage)
- Kaiko: $100k BTC-USD sell slippage on Coinbase "tends to increase at the start and end of U.S. market hours (15:00 UTC and 20:00 UTC)"; on 5 Aug 2024 slippage on major US exchanges tripled; stablecoin pairs on BitMEX and Binance US rose by more than 3 bps; KuCoin BTC-EUR exceeded 5%. Kaiko collects two order-book snapshots per minute and computes slippage for a hypothetical $100k buy/sell. — [Kaiko: Moving markets](https://www.kaiko.com/resources/moving-markets-liquidity-and-large-sell-orders); [Kaiko: CEX liquidity data](https://www.kaiko.com/resources/understanding-centralized-exchange-liquidity-data)
- The Block publishes a "Slippage for $100k sell order (BTC/USD, bps)" series. — [The Block](https://www.theblock.co/data/crypto-markets/spot/slippage-for-100k-sell-order-btc-usd)
- Amberdata: "A trade that costs 3 basis points in slippage at one hour might cost 5 basis points at another - a 67% difference in execution cost based solely on timing" (Binance BTC/FDUSD, Jul-Aug 2025); US session (16:00-24:00 UTC) depth 8% below European session; weekend depth slightly higher than weekdays ($3.68M Sat vs $3.46M weekdays). — [Amberdata](https://blog.amberdata.io/the-rhythm-of-liquidity-temporal-patterns-in-market-depth)
- OTC: institutions were 72% of Wintermute's spot OTC volume in H1 2026; the four desks moving most nine-figure stablecoin tickets are B2C2, Wintermute, Cumberland (DRW), GSR; GSR markets OTC as a way "to avoid slippage and minimize market impact"; mid-cap tokens "face wider spreads and higher slippage than the headline market cap figures might suggest". — [TradingView/NewsBTC](https://www.tradingview.com/news/newsbtc:d72713420094b:0-wintermute-says-institutions-drove-72-of-its-spot-otc-volume-in-h1-2026/); [GSR OTC](https://www.gsr.io/services/otc-trading); [eco.com OTC desks](https://eco.com/support/en/articles/15426770-top-stablecoin-otc-desks-2026-b2c2-wintermute-cumberland-gsr)
- Cross-venue: Makarov-Schoar (2020) found crypto cross-exchange arbitrage "often persist[s] for weeks" and a common signed-volume factor explains "up to 85 percent of Bitcoin return variation" (relevant to multi-venue execution and to the informed-flow component of impact). — [HFT Advisory Substack](https://hftadvisory.substack.com/p/before-during-and-after-the-fill)

### Inferences
- The realistic all-in cost for a patient (5% participation, mostly passive) institutional BTC/ETH execution on aggregated CEX liquidity appears to be low-single-digit to low-teens bps vs arrival depending on trend; -0.58 bps (Anboto) implies mostly-passive execution capturing spread, which is only possible in non-trending conditions.
- For sizes above a few percent of 1%-depth (hundreds of $M for BTC on Binance) OTC/RFQ is the practitioner default rather than algorithmic sweeping.

### Gaps
- No published "bps per % of ADV" curve from Wintermute, Jump, GSR, Caladan, Flow Traders or Coinbase Prime; these firms publish volume/flow reports, not TCA curves.
- Anboto's -0.58 bps is self-reported without sample size, period or market-direction control.
- No perp-specific slippage numbers (Binance/Bybit/OKX/Hyperliquid perps) beyond Hyperliquid's mechanical 3% cap were found.

---

## Q5. Maker vs taker: fill probability, queue value, adverse selection, passive-then-cross

### Takeaway
Theory (Moallemi & Yuan; "market maker's dilemma") says queue value = spread capture minus adverse selection, both increasing with queue position, plus an option value of improving position; orders at the back of the queue tend to have negative expected markouts. In crypto practice, Talos reports 75% maker fills in its TWAP case study, and RL-Exec's BTC results show gains grow with horizon (more time to be passive). A concrete crypto-calibrated fill-probability model was not found.

### Cited Findings
- [EQUITIES/FUTURES] Queue position value "has two important components: a static component relating to the trade-off between earning a spread and incurring adverse selection costs (which are increasing with queue position), and a dynamic component capturing the optionality of improving queue position over time." — [Moallemi & Yuan, A Model for Queue Position Valuation](https://moallemi.com/ciamac/papers/queue-value-2016.pdf) (via [Semantic Scholar summary](https://www.semanticscholar.org/paper/A-Model-for-Queue-Position-Valuation-in-a-Limit-Moallemi-Yuan/4281c40e05cd5de6b0c6c37ecca3ce39b351a5ba))
- Fill vs post-fill return trade-off: "Orders with queue position near 1 [back] are likely to generate negative returns regardless of queue sizes, while orders with queue position near 0 [front] may generate positive returns if the near-side queue size is sufficiently large"; "a limit order submitted at the front of the queue is less likely to undergo adverse selection." — [arXiv 2502.18625, The Market Maker's Dilemma](https://arxiv.org/pdf/2502.18625)
- "Queue position of a limit order influences its adverse selection risk and inhibits inventory risk management"; price-time priority creates "a technological arms race ... to establish early positions in the FIFO queue." — [ScienceDirect: Queuing and inventories in limit order markets](https://www.sciencedirect.com/science/article/pii/S1386418125000229)
- Model-free passive placement benchmark (Shadow-PPOV, CME ES): shadow observed third-party orders at the same price, cancel when the shadowed order ends; proposed as "a model-free benchmark for passive-order placement". — [arXiv 2609.18019](https://arxiv.org/abs/2609.18019)
- [CRYPTO] Talos TWAP case: 75% maker fills while net buyer 85% in an uptrend, ~13 bps arrival cost. — [Talos TCA](https://www.talos.com/insights/execution-insights-through-transaction-cost-analysis-tca-benchmarks-and-slippage)
- [CRYPTO] RL-Exec simulator includes partial fills, maker/taker fees and latency; RL edge over TWAP/VWAP rises from +2-3 bps (30 min) to +23 bps (120 min). — [arXiv 2511.07434](https://arxiv.org/abs/2511.07434)
- Practitioner note: fee-only post-only modules "have no model of fill probability, queue position, or adverse selection, and should be paired with adverse-selection measurement and queue-position modeling." — [Algo-Trading-Skills: post-only and maker-taker fee optimization](https://skills.himanshujangir.com/skills/post-only-and-maker-taker-fee-optimization/)
- [CRYPTO] Hyperliquid "Chase" post-only variant re-pegs one tick inside the touch (rests one tick above best bid for buys). — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)

### Inferences
- Passive-then-cross logic that is consistent with the sources: post at the touch (or one tick inside on wide-spread venues), track queue-ahead; if the schedule falls behind by more than one child, cross for the shortfall (mirrors Hyperliquid's catch-up rule at algorithm level and Talos's ~75% maker share).
- Adverse-selection markout should be measured per venue/pair (e.g. mid change 1-10 s after passive fills) because none of the crypto sources publish it; the equity finding that back-of-queue fills are negative-EV should be assumed to transfer.

### Gaps
- No crypto-specific empirical fill-probability or queue-value numbers (e.g. expected markout of a passive BTC fill on Binance in bps) were found in public sources.
- Moallemi-Yuan full PDF could not be rendered (no poppler); magnitudes of queue value relative to tick are therefore not quoted.

---

## Q6. Price-time priority, queue estimation, post-only on crypto CEX matching engines

### Takeaway
OKX and Bybit document price-time (FIFO) priority; post-only orders are cancelled if they would match immediately; OKX's default self-trade-prevention cancels the resting maker order. Depth at the top of book is thin relative to 10-bps depth (Binance BTC: >$1M per side within +/-$10, ~$8M within +/-$100), so queue position at the touch matters and turns over quickly. Hyperliquid documents ALO/post-only and a "chase" variant but not queue mechanics.

### Cited Findings
- OKX: "advanced price-time priority matching algorithm where for the same price, orders submitted earlier get executed first, and for different prices, better prices ... are prioritized"; Post Only "guaranteed to enter the order book with the user being a market maker, and if a Post Only order is able to match with an existing order instantly, it will be canceled"; default STP mode: "the maker order will be canceled, then the taker order will continue to match with the next order in the price-time priority." — [OKX API guide](https://www.okx.com/docs-v5/trick_en/); [OKX basic order types](https://www.okx.com/en-us/help/x-basic-order-types)
- Bybit: "Post Only orders will be cancelled if the order would be filled immediately when submitted." — [Bybit API v5 place order](https://bybit-exchange.github.io/docs/v5/order/create-order)
- Coinbase: exchange trading rules published (price-time priority is standard); not fetched in detail. — [Coinbase Markets Trading Rules](https://www.coinbase.com/legal/trading_rules)
- Hyperliquid ALO = post-only resting order; Chase = post-only pegged one tick inside best bid/ask; TWAP suborders capped at 3% slippage. — [Hyperliquid docs](https://hyperliquid.gitbook.io/hyperliquid-docs/trading/order-types)
- Top-of-book thickness (Binance BTC): only Binance exceeds $1M per side within +/-$10 of mid; Bybit, Bitget, OKX, HTX, Crypto.com range $100K-$500K within +/-$10. — [CoinGecko 2025](https://www.coingecko.com/research/publications/crypto-liquidity-report-2025)
- Kaiko snapshots order books twice per minute (so queue position cannot be inferred from Kaiko-type data; requires L2/L3 diff streams). — [Kaiko](https://www.kaiko.com/resources/understanding-centralized-exchange-liquidity-data)

### Inferences
- Queue-position estimation on Binance/Bybit/OKX must be done from L2 diff streams: on placement, queue_ahead = displayed size at the level; decrement by trades at that price and by observed size reductions (attributing cancels ahead vs behind is the standard ambiguity; conservative estimators assume cancels come from behind).
- Because top-of-book ($10-wide) depth on non-Binance venues is only $100-500K for BTC, a $200K passive child can be a large fraction of the queue, so posting one tick inside (Hyperliquid "chase" style) buys priority at the cost of a tick.

### Gaps
- No source found documenting Binance's matching-engine tie-break rules or any pro-rata/size-priority element (all evidence points to plain FIFO, but not verified from Binance docs in this session).
- No published crypto data on queue turnover rate at the touch (fills + cancels per second) which is needed to calibrate a fill-probability model.
