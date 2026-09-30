# basis-engine: what the execution algorithm actually does today (code audit)

Audit date: 2026-09-30. Scope: `crates/algo/src/{lib,parent,quote,hedge,risk,basis,config}.rs`, engine wiring in
`crates/engine/src/{runner,market,watchdog}.rs`, cross-checked against `docs/quant/EXECUTION_DESIGN.md` (ED),
`docs/quant/PARAMS.md`, `docs/SPEC.md`. All line references are to the repo at
`scratchpad/be/basis-engine`. Read-only audit; nothing was modified.

**Headline.** The code is a faithful, defensively-engineered implementation of ED v1's *plumbing* (state
machine, fixed-point arithmetic, lot/min-notional handling, dust/residue rules, hedge ladder, kill flatten).
The *quant* content is thin and several of ED's own signal/scheduling features are stubbed out at the call
site: no TWAP envelope, no participation cap, no baseline EWMA (so `relative_to_baseline` silently degrades to
`absolute`), no imbalance-quantity cap on child size, no CLOSE escape hatches, no request-budget throttle in the
quoter, no REST refresh of a stale reference, and the ED §8.4 pre-trade risk gate (`risk::admit`) is not wired
into the engine at all. There is no order-book imbalance, microprice, queue-position, fill-probability,
volatility-scaled sizing or markout feedback anywhere on the decision path.

---

## 0. Architecture in one paragraph

`Parent` (lib.rs:539) wraps a private `parent::Fsm` (parent.rs:145) that holds fills, one `Quoter`
(quote.rs:898) for the passive leg and one `Hedger` (hedge.rs:642) for the aggressive leg. The engine feeds
`AlgoInput::{Start, Book{leg}, Trade{leg,px,qty}, Oms(&OmsEvent), Timer, Operator, Feed, Kill}` (lib.rs:345)
through `Parent::on_input` (lib.rs:599 → parent.rs:255). The parent reads books through the `MarketView` trait
(`top`, `depth_within`, `depth_recv_ns`; lib.rs:280) and acts through `Io` (`place`, `cancel`, `sweep`,
`schedule_cancel`, `record`; lib.rs:297). Quoter and Hedger are pure decision objects ("decide, never act").
All arithmetic is i64/i128 fixed point (`Px`/`Qty` 1e-8, `Cbps` = centi-bps, `Ppm`); no f64. One typed
`AlgoConfig` (config.rs:96) carries every PARAMS.md row; `Switches` (config.rs:67) carries the logic toggles.

---

## 1. Parent order state machine and modes

### 1.1 States and dispatch

Eleven states, `ParentState` (lib.rs:244): Created(0), Quoting(1), Hedging(2), TakerTaker(3), CatchingUp(4),
Unwinding(5), Paused(6), Reconciling(7), Completed(8), Failed(9), Killed(10). Dispatch table in
`Fsm::on_input` (parent.rs:295-335):

| Input | S0 | S1 | S2 | S3 | S4 | S5 | S6/S7 |
|---|---|---|---|---|---|---|---|
| `Book` | `start` | `tick_s1` | `tick_s2` | ignored | `tick_s2` | ignored | ignored |
| `Timer` | `start` | `tick_s1(timed)` | `tick_s2` | `timer_s3` | `tick_s2` | ignored | ignored |
| `Trade` | ignored+counted in every state (only feeds the median-trade ring, parent.rs:334) |
| `Oms` | routed by slot to `oms_s1/oms_s2/oms_s3/oms_s5` (parent.rs:918) |
| `Feed`, `Operator`, `Kill` | handled in every non-terminal state (parent.rs:297-299) |

Every market input first calls `feed_quoter` (parent.rs:897): a `Book` on **either** leg feeds the perp mid to
`VolEwma` and `LeadLag`; a leg-S `Trade` feeds `MedianTrade`. Nothing else consumes trades.

### 1.2 Admission (S0 → S1), `start` (parent.rs:412-527)

1. Both tops required, else decline `StaleReference` and stay S0 (retry on next book).
2. ED §7.3 guard 2: `|B_mid| > wrapper_premium_alert_bps` → `AdmissionFailed` → S9 unless
   `switches.premium_guard_standdown` (then a `GuardStoodDown` record). parent.rs:437-456.
3. `lot_eff` (quote.rs:484): `need = min_notional_usd × min_notional_cushion` ($12.50);
   `lot_eff = ceil(max(need/mid_s, need/mid_p) / lot_coarse) × lot_coarse`, `lot_coarse = max(lot_S, lot_P)`;
   must be `is_valid_sz` on both legs, else `NotExpressible` → S9.
4. `target_qty = floor_to_lot_eff(qty or notional/mid_s)`; a notional target that floors to 0 but was ≥ the
   cushioned minimum is promoted to one `lot_eff` (D26; parent.rs:472-501).
5. `horizon_ns = now + horizon_ms` fixed at admission (not moved by hot-apply; parent.rs:3121).
6. Transition `Admitted` → S1, then **immediately evaluates the TT entry** (`tt_enter`, parent.rs:526).

Note: ED §1.1's "no other parent open on the same pair" and the ED §8.4 R1–R3 risk gate are *not* run here.
`Parent::new` only runs `cfg.validate()` (lib.rs:552). The engine's pre-trade check is
`hl_testnet_exp::guard::RunGuard` + `Core::preflight` (runner.rs:986), see §6.

### 1.3 S1 Quoting — the deciding state, `tick_s1` (parent.rs:534-580)

Order of checks on every Book/Timer in S1:

1. `timed && expired()` → `Completed(HorizonExpired)` (only on a Timer, not on a Book).
2. Deferred operator Pause/Cancel applied.
3. D29 residue re-check: at target, nothing live, `now ≥ residue_recheck_ns` → complete if `flat()` or
   (hedger settled ∧ residue carriable), else re-arm at `+requote_ttl_ms`.
4. **`tt_enter` first** (TT has precedence over quoting, parent.rs:575).
5. `quote_tick` (MT path).

### 1.4 Taker-Taker mode, `tt_enter` (parent.rs:588-744)

Triggers actually implemented (parent.rs:631-643):
- `force_urgent` (operator `Urgent` command, or ALO-reject streak ≥ `alo_reject_streak_max` raised from
  `quote_done`, parent.rs:1248-1255), or `cfg.urgency == Urgent`;
- else `E_tt = B_touch − fees_tt ≥ threshold(dir) + tt_edge_bps` (basis.rs:134, threshold basis.rs:140).

**Not implemented** (ED §6.1): TWAP-behind (`behind_pct`), CLOSE hatches (`close_blowout_bps`,
`close_timeout_s` — grep shows them only frozen in `apply_config`, lib.rs:583, and in runcard loading),
"S4/S5 could not complete on leg P → cross the remainder".

TT mechanics:
- Both touches must be `fresh` (≤ `ref_max_age_ms`) and both ladders `depth_fresh` (≤ `stale_halt_ms`).
- Each leg limit: `taker_limit_px(ref, anchor=ref, payup=max_slippage_bps, extra=0, max=max_slippage_bps)`
  (hedge.rs:131) — i.e. the TT IOC is always priced the full `max_slippage_bps` (10 bps) through the touch.
- Slice: `qty = floor_lot_eff( min(depth_S(within lim_s), depth_P(within lim_p)) × tt_depth_frac )`, capped
  by `floor_lot_eff(remaining)` (parent.rs:687-695). Zero → decline `BelowMinNotional`, stay S1.
- If a quote child rests: cancel it, park `pending_tt`, send the IOC on its `Done` (parent.rs:704-710).
- Leg S IOC first (`ChildRole::TakerTaker`); S3. On `tt_leg_s_done` (parent.rs:1483): zero fill →
  `tt_attempts += 1`, ≥ `tt_max_attempts` → **S9 Failed** (not the ED §5.5 escalation), else back to S1;
  positive fill → leg-P IOC for `floor_sz_P(credited_S)` at `max_slippage_bps` off the *current* perp touch
  (`tt_leg_p_limit`, parent.rs:1820), remainder (`credited − p_qty`) into the hedger's dust bucket.
- `tt_leg_p_done` (parent.rs:1608): P filled > S → S7 Reconciling; P < sized → shortfall to hedger, S2 if
  hedgeable; else complete if at target ∧ (flat ∨ carriable), else S1 for the next slice.

### 1.5 S2 Hedging / S4 CatchingUp

`tick_s2` (parent.rs:1853): (a) if the in-flight IOC passed `hedge_ack_wait_ms`, cancel it once;
(b) `hedge_tick` → `Hedger::decide` → `hedge_act`. **No horizon check in S2** (parent.rs:1873): an expired
horizon with live exposure keeps hedging. S4 is driven by exactly the same `tick_s2`; the only difference is
which ED event is recorded on exit (parent.rs:1906-1911).

`hedge_act` (parent.rs:1984-2121) maps `HedgeAction`:
- `Hedge{..}` → `place_child(Leg::P, IOC, reduce_only from HedgeSize)`; `hedger.on_sent`.
- `RefreshReference` → **no-op** (parent.rs:1999); nothing in the engine performs a REST refresh and
  `Hedger::on_refresh_failed` is never called (grep: no engine call sites). See §8.
- `Unwind{why}`: from S2 with `LadderExhausted` ∧ `switches.catch_up` → S4 (`catch_up_enter`, no decision
  this tick; the retry clock owns the next attempt). Otherwise → `unwind_enter` (S5) for
  `ImbalanceHard`/`LeggingTimeout`/S4-`CatchUpFailed`; any other reason → S9.
- `StopQuoting(ImbalanceSoft)` / `Chase` → S4 (`catch_up_enter`: cancel resting quote, then decide now).
  With `switches.catch_up=false` → straight to unwind (`catch_up_unwinding`, parent.rs:2172).
- `GiveUp` → S9 Failed + sweep.

### 1.6 S5 Unwinding (parent.rs:2231-2450)

Reverse leg-S IOC: `qty = floor_lot_eff(hedger.unhedged())`, limit `taker_limit_px(S touch, anchor = touch,
unwind_payup_bps, max_slippage_bps)`. `UnwindPartial` re-arms with `payup = unwind_payup_bps × attempt` off
the *current* touch, still bounded by `max_slippage_bps` from the first unwind's anchor, up to
`hedge_max_attempts` (parent.rs:2349-2392). `UnwindFilled` if bucket empty ∨ `flat()` ∨ remainder < 1 lot →
S8 if at target, S8(HorizonExpired) if expired, else S1. Otherwise `UnwindFailed` → **S10 Killed**
(parent.rs:2449). `switches.unwind=false`: hard breach kills, other escalations fail (parent.rs:2270-2277).

### 1.7 S6/S7/terminal

`feed` (parent.rs:2676-2797): `Disconnected` in S1 → sweep → S7; in S2/S3/S4 → S7 with the in-flight IOC
left alone; in S5 → S7 with a *sent* unwind left and a *parked* one dropped. `Reconciled` → S2 if the hedger
has anything hedgeable, else S8 if at target ∧ (flat ∨ carriable), else S1. `ReconcileFailed` → S10.
Kill from any state → cancel all children + sweep → S10 (`kill_with`, parent.rs:2808); the flatten itself is
the engine's (`runner.rs:849` → `risk::flatten_plan`). Late fills for terminal parents are booked and, if
leg S, alarmed as `Declined::RiskGate` (parent.rs:267-288).

### 1.8 TWAP envelope

**Not implemented in the algo.** `quote_tick` hands `twap_room: Qty(i64::MAX)` and
`max_imbalance_qty: Qty(i64::MAX)` to the quoter (parent.rs:775-781). `twap_threshold_usd`, `ahead_pct`,
`behind_pct`, `participation_cap_pct`, `funding_blackout_s` are parsed/validated but never read on the decision
path (workspace grep: only `tca/src/metrics.rs:211-240` recomputes `allowed_cum_qty` *after the fact* for
reporting, and explicitly notes the participation cap is not computed). `Switches::twap` is dead.

### 1.9 Timers

`next_wake_ns` (parent.rs:354-390): S1 = min(horizon, quoter TTL/stale deadline, D29 residue re-check);
S2/S4 = hedger (ack-wait, retry, legging deadline); S3/S5/S6/S7 = none. The engine polls `Timer` at that
instant.

---

## 2. Entry test: executable basis after fees

Source: basis.rs (pure functions), quote.rs `Quoter::decide` step 4.

Definitions (basis.rs:59-120), all in centi-bps of **spot mid**, integer division truncating toward zero:

```
mid_S = (bid_S + ask_S)/2 ;  mid_P = (bid_P + ask_P)/2            basis.rs:23
OPEN : B_touch = (bid_P − ask_S)/mid_S ;  B_exec_mt = (bid_P − q_post)/mid_S
CLOSE: B_touch = (bid_S − ask_P)/mid_S ;  B_exec_mt = (q_post − ask_P)/mid_S
B_mid = (mid_P − mid_S)/mid_S                                     (direction-free)
fees_mt = fee_spot_maker + fee_perp_taker (8.5) ; fees_tt = fee_spot_taker + fee_perp_taker (11.5)
E_mt = B_exec_mt − fees_mt − hedge_slip_est_bps (3.0)             basis.rs:123
E_tt = B_touch  − fees_tt                                          basis.rs:134
threshold = entry_threshold_bps (OPEN, +12) | close_threshold_bps (CLOSE, −11.5)   basis.rs:140
```

Book sides: OPEN reads `perp_bid` and our own `q_post` (a spot bid); CLOSE reads `perp_ask` and our `q_post`
(a spot ask). The touch on the passive leg enters only via the quote-price construction (§3), never directly
in `E_mt`.

`entry_test` (basis.rs:160-185):
- CLOSE: always `absolute` against `close_threshold_bps` regardless of `entry_basis_mode`.
- OPEN `Off` → Enter; `Absolute` → `E_mt ≥ entry_threshold_bps`;
  `RelativeToBaseline` with `Some(b)` → `E_mt − b ≥ entry_threshold_bps ∧ E_mt ≥ min_absolute_basis_bps`;
  with `None` → absolute fallback if `baseline_fallback_absolute` (default true) else `BaselineCold`.
- **The baseline is always `None`**: `quote_tick` passes `baseline: None` (parent.rs:790, comment "the
  baseline estimator … is not built yet"). With the default config (`relative_to_baseline`,
  `baseline_fallback_absolute=true`) the live behaviour is therefore **absolute at +12 bps**, and
  `baseline_halflife_s`, `baseline_warmup_s`, `min_absolute_basis_bps` are inert (D21's concern that the mode
  would "silently degrade to absolute" is exactly what happens, by construction).

Hysteresis: `should_pull` (basis.rs:198): pull the resting quote when `E_mt(at resting px) <
threshold − cancel_hysteresis_bps` (1 bp). Entry is `≥ threshold`, pull is `< threshold − h`: a 1 bp band.
Note the entry test is evaluated at `q_post` (the price about to be posted) and the pull test at `r.px` (the
price that rests), so a reprice can be pulled-and-reposted rather than held when the two straddle the band.

Staleness gating of the entry decision (quote.rs:967-985): perp touch age > `ref_max_age_ms` (1 s) or spot
touch age > `passive_max_age_ms` (1 s) → `Pull{Stale}`/`Decline(StaleReference)`; a cold `VolEwma`
(`sigma() == None`) also declines (`stale_buffer` returns `None`, quote.rs:1029).

---

## 3. Passive leg quote logic (quote.rs)

### 3.1 Price selection, `reservation_px` + `quote_px` (quote.rs:195-308)

```
stale_buffer = lambda_vol × sigma_cbps × sqrt(perp_age_ms/1000)          quote.rs:209   (2 × σ × √age)
x = threshold + fees_mt + hedge_slip_est + stale_buffer                   quote.rs:195   (may be negative)
OPEN : R = bid_P / (1 + x/1e4)                                            quote.rs:226
       q = min(R, bid_S + improve) ; q_post = round_down_tick(q)          quote.rs:278-280
       post iff q_post ≥ bid_S  ∧  R ≥ bid_S  ∧  q_post < ask_S
CLOSE: R = ask_P × (1 + x/1e4)
       q = max(R, ask_S − improve) ; q_post = round_up_tick(q)
       post iff q_post ≤ ask_S  ∧  R ≤ ask_S  ∧  q_post > bid_S
improve = improve_ticks × tick_S  only if  (ask_S − bid_S) > tick_S, else 0   (A1 guard)
```

So the posted price is **join-or-improve-by-one-tick, capped by the reservation price**. Since
`R ≥ bid_S ⟺ E_mt ≥ threshold + stale_buffer` (ED §3.1 identity), the quote sits at the touch (or one tick
inside) whenever the entry passes, and is *never* deeper in the book than that: the reservation price only
ever binds *downward* toward the touch guard, never pushes the quote inside. There is no notion of layering,
of quoting behind the touch to harvest queue priority, or of skewing by inventory.

`sigma` (`VolEwma`, quote.rs:613-679): EWMA of `r²/dt` in cbps²/s, weight `dt/(dt + halflife)` with
`vol_halflife_s` = 60; warm after 2 mids spanning ≥ 1 s; fed with the perp mid on **every book event of either
leg** (`feed_quoter`), so quiet books push σ → 0 (documented in ED §3.1). At `lambda_vol` 2, σ ≈ 0.6 bps/√s,
age 100 ms → 0.38 bps.

### 3.2 Requote / cancel-replace (`Quoter::decide` steps 5-6, quote.rs:1097-1125)

- Nothing resting: `Place` unless `now < last_place + requote_min_ms` (300 ms) → `Decline(Throttled)`.
- Resting: `Reprice` iff (`|q_post − r.px| ≥ requote_ticks` (2) ticks ∧ age ≥ `requote_min_ms`) ∨
  age ≥ `requote_ttl_ms` (10 s); else `Hold`.
- Reprice is **cancel-then-place** (parent.rs:798-801, `PendingQuote::Reprice` placed on the cancel's
  `Done`), not a venue `modify` as ED §3.3 specifies. The comment in ED about `modify` preserving one action
  is not what runs; every reprice costs two actions and a round trip with nothing resting in between.
- Partial fill keeps the remainder resting with the original `placed_ns` (quote.rs:1162-1169).

### 3.3 Pull rules (quote.rs:987-1025, 1080-1095), first-wins order

1. Stale: perp age > `ref_max_age_ms` or spot age > `passive_max_age_ms`, or not `md_warm` → `Pull{Stale}`.
2. Lead-lag: `LeadLag::adverse` → `Pull{LeadLag}`, then `pull_cooldown_ms` (500 ms) of `Decline(Throttled)`.
3. Basis decay: `should_pull(E_mt at r.px)` → `Pull{BasisDecay}`.
4. Depth loss: `depth_P(within hedge_slip_max_bps) < r.qty` → `Pull{DepthLoss}` (a stale ladder reads as
   zero depth, so an `l2Book` older than `stale_halt_ms` also pulls).
5. Any later failure to price/size (`R` unpriceable, `q_post` None, entry fails, size 0) with a quote resting
   → `Pull{BasisDecay}` / `Pull{DepthLoss}` (`no_post`, quote.rs:1141).

### 3.4 Lead-lag / cross-venue signal, `LeadLag` (quote.rs:743-835)

The only "signal" beyond the basis itself: a 256-entry ring of **HL perp mids** (same venue); adverse if the
move from the window extreme (max for OPEN, min for CLOSE) to the latest mid, in cbps of the extreme, exceeds
`pull_bps` (3 bps) within `pull_window_ms` (200 ms), *and* the latest mid is itself inside the window. There is
**no external venue price** (no CEX perp, no Bybit) on the decision path; `md-binance`/`md-bybit` crates exist
but nothing feeds the quoter from them. ED §3.3's "or a tracked CEX mid" is unimplemented.

### 3.5 Absent microstructure inputs

`Top` carries `bid_qty`/`ask_qty` (lib.rs:270) and `depth_within` walks the ladder, but **no order-book
imbalance, microprice, queue-position estimate, trade-flow sign, or fill-probability** is computed anywhere
(grep for `imbalance` hits only the *delta_usd* risk imbalance). Spot trades are used solely for the median size.

### 3.6 Staleness / warm-up (parent.rs:878-894, quote.rs:161-166)

`md_warm`: both books ready ∧ both ages ≤ `stale_halt_ms` (9 s) ∧ feed up, for ≥ `md_warmup_ms` (1 s) since
first live. Touch ages (`ref_max_age_ms`, `passive_max_age_ms`) gate pricing; snapshot age
(`depth_recv_ns`, i.e. last `l2Book`, engine market.rs:83) ≤ `stale_halt_ms` gates every depth read
(`depth_fresh`). ED §3.4's REST refresh at `ref_max_age_ms/2` (`ref_rest_refresh_ms`) is not implemented
(no consumer of that parameter outside config).

### 3.7 Watchdog W6 (engine, not algo)

`maker_child_max_rest_ms` (15 s) is enforced by `engine::watchdog` (`CancelChild`, watchdog.rs:12) as a
cancel-without-reprice. ED §3.3's `requote_ttl_ms` (10 s) normally fires first.

---

## 4. Child sizing (quote.rs:538-606)

```
if 0 < remaining < lot_eff:                                     # sub-lot rule
    gap = floor_sz_S(remaining)
    return gap  if gap > 0 ∧ gap×mid_S ≥ min_notional ∧ gap×mid_S ≥ need_usd   else lot_eff   (overshoot < 1 lot)
child = floor_to_lot_eff( min(
    child_alpha × depth_P(within hedge_slip_max_bps of mid_P, on the side the hedge crosses)   # 0.4 × depth
  , child_beta  × median|trade_S|(median_trade_window_s)   (i64::MAX if no trades)              # 2.0 × median
  , max_imbalance_qty      = i64::MAX   (parent.rs:778 — never binds)
  , twap_room              = i64::MAX   (parent.rs:780 — never binds)
  , remaining
  , clip_usd / mid_S                                                                             # $1000
))
```

- `depth_P` limit: `hedge_limit` = `mid_P × (1 ∓ hedge_slip_max_bps)` rounded toward mid (quote.rs:135),
  summed over resting levels no worse than that (engine `depth_within`, market.rs:54); reads zero if the
  ladder is stale.
- Median: lower-middle of the newest ≤ 256 trades inside the window (quote.rs:710-729); even count →
  lower value.
- `child == 0` → `Decline(BelowMinNotional)` (or `AheadOfSchedule` if the TWAP term bound — unreachable
  today), and pulls any resting quote.
- Dust handling on the hedge side (§5.3) is what makes the sub-lot rule's overshoot safe.

Effective sizing on the MVP pairs: with `max_imbalance_qty` and `twap_room` inert, the child is
`min(0.4·depth_P(5 bps), 2·median_trade_S, remaining, $1000/mid)` floored to `lot_eff`. On BTC/ETH mainnet
depth (ED §3 table) `clip_usd` binds; on HYPE the median-trade term is likely to bind.

---

## 5. Hedge logic (hedge.rs)

### 5.1 Trigger source

The hedger is fed by `Hedger::on_leg_s_fill(qty, fill_ts, p_touch)` from: MT quote fills (`quote_fill`,
parent.rs:1183/1202), TT leg-S fills (`tt_leg_s_done`), TT leg-P shortfalls, late fills (`late_fill`), and
reconciled fills. The OMS emits `OmsEvent::Filled` deltas from **post replies, `orderUpdates` and `userFills`**
alike, de-duplicated by `tid` (`OmsEvent::DuplicateFill`, oms/src/lib.rs:30, 257, 715), so the effective trigger
is "earliest OMS-observed fill delta". `Switches::hedge_trigger` (`EarliestSignal | UserFillsOnly`) is
**not consumed anywhere** (grep: config.rs only); `UserFillsOnly` is a no-op.

Quantity hedged = **credited** base (`credited_base`, hedge.rs:304): for a spot *buy* `fill − ceil(fill ×
fee_rate)` with the maker rate for ALO children and the taker rate for IOC children; spot sells and perp fills
unchanged. Risk (`delta_usd`) is measured on `credited_s`, target progress on `filled_s` (parent.rs:157-162).

### 5.2 Sizing, `hedge_size` (hedge.rs:202-269)

```
q = floor_sz_P(unhedged)                       # unhedged = fill deltas + dust bucket
if q > 0 ∧ q×mid_P ≥ min_notional_usd: send q; dust = unhedged − q        # venue minimum, NOT lot_eff
else if !final_residue: send 0; dust = unhedged
else (parent at target):
    OPEN : send 0 (long-spot dust is G1-safe; carried)
    CLOSE: send max(lot_eff, ceil_to_lot_eff(unhedged)) reduce-only  (§8.4 rule 3), dust = 0
```

The hedge fires on the venue $10 minimum, not on a whole `lot_eff`. Dust is capped by `max_residue_usd`
($50): `dust × mid_P > max_residue_usd` → `ResidueBreach` escalation (hedge.rs:960-973).

### 5.3 IOC pricing and pay-up ladder (hedge.rs:99-172, 1090-1156)

```
attempt k: payup_k = 0 (k=1) | hedge_payup_bps[min(k−2, rungs−1)] (k≥2)        {2, 5, 10} bps, rungs=3
reference = perp touch on the crossing side (ask for buy, bid for sell), read NOW
anchor    = perp touch when the first unhedged fill of this episode landed (or first decide that saw a book)
extra     = stale_buffer if perp age > ref_max_age_ms else 0
limit     = reference × (1 ± (payup_k + extra)/1e4), bounded to anchor × (1 ± max_slippage_bps), rounded toward reference
if payup_k + extra > max_slippage_bps or stale_buffer is None → RefreshReference (no order)
```

- `hedge_max_attempts` = 4 → touch, +2, +5, +10 bps. Rung price is relative to the *current* touch, but the
  hard bound is `max_slippage_bps` (10 bps) from the *anchor* touch; if the market ran away, later rungs are
  clamped at the anchor bound (which then feeds the "clamped chase is less fillable" tie-break).
- Retry: `on_child_done(filled_any=false)` → `attempt += 1`, `retry_at = now + hedge_retry_ms` (300 ms);
  `filled_any=true` → `attempt = 1`. A partial fill restarts the ladder from the touch for the remainder
  (hedge.rs:1232). `hedge_ack_wait_ms` (250 ms) without a `Done` → the parent cancels the IOC once
  (parent.rs:1869).
- One IOC in flight at a time (`in_flight`), hold on a dead feed.

### 5.4 Imbalance accounting (hedge.rs:395-433)

```
delta_usd = (credited_S_signed + filled_P_signed) × mid_P        # D27: hedge-leg mid, zero when base-hedged
soft = max_imbalance_usd × imbalance_soft_pct (50%) ;  hard = max_imbalance_usd × imbalance_hard_mult (2.0)
|delta| > hard → Hard ; > soft → Soft ; else Within
```

`max_imbalance_usd` default 5000 (HYPE row); PARAMS' "derive from σ·√T" is a documented formula only
(`risk_z`, `risk_budget_usd` are never read — grep). The per-pair table is applied by the config store, not
by the algo.

### 5.5 Escalation, `Hedger::decide` (hedge.rs:912-1157) and `escalate_to` (hedge.rs:475-576)

Order per decision: (1) feed down or IOC in flight → Hold. (2) `ResidueBreach` if dust > `max_residue_usd`.
(3) `over_legging` (`now − oldest_fill_ns > max_legging_time_ms`, 2 s), `Hard`, or ladder exhausted → escalate;
but a CLOSE residue short the package with nothing sendable first gets the once-per-parent rule-3 reduce-only
over-hedge at the touch (hedge.rs:994-1043). (4) `Soft` → `StopQuoting` once per episode. (5) nothing sendable
→ Hold. (6) retry timer. (7) price attempt k.

Legging clock (D23 R2): armed only when `unhedged > 0 ∧ (CLOSE ∨ an ordinary hedge is sendable)`; origin =
the venue fill timestamp of the fill that made it actionable (never "now"; adopted reconcile fills keep their
age). OPEN sub-minimum dust arms nothing.

`escalate_to` chooses between chasing leg P at the terminal rung (+ stale buffer, bound from anchor) and
unwinding leg S at `unwind_payup_bps` (10 bps) off the leg-S touch: `LadderExhausted` → Unwind if priceable;
one book missing → trade the visible one; chase clamped while unwind not → Unwind; else compare each limit's
cbps distance from its **own leg's mid** and pick the smaller, ties → Unwind. A chase that comes back
unfilled sets `chase_failed` so the next escalation goes straight to Unwind.

### 5.6 Catch-up and unwind rules as wired

- `Soft` breach: S4, cancel the resting quote, continue the same ladder (`hedge_act`, parent.rs:2094-2116).
- `LadderExhausted` in S2: S4 (catch-up = ladder terminal rung), next attempt after `hedge_retry_ms`; a second
  exhaustion in S4 → `CatchUpFailed` → S5.
- `Hard` or `LeggingTimeout`: S5 unwind (§1.6) — or Kill/Fail if `switches.unwind` is off.
- `ResidueBreach` reaching the unwind arm → S9 Failed (parent.rs:2262-2266), i.e. a large OPEN dust bucket
  is a *failure*, not an unwind.

---

## 6. Risk (risk.rs and engine)

### 6.1 Pre-trade gate, `risk::admit` (risk.rs:169-243) — implemented but **not wired**

R1: `unhedged_now + Σ worst_case(live) + min(clip_usd | tt_slice, notional) ≤ min(max_unhedged_notional_usd,
E/(liq_buffer_pct + maint_margin_frac))`. R2: leg-S committed ≤ `min(max_leg_notional_usd_s, E/2)`, leg-P ≤
`min(max_leg_notional_usd_p, E/rate)`. R3: `liqPx = (E + N·mark)/(N·(1+mm))`, `dist = (liqPx − mark)/mark ≥
liq_buffer_pct` (40%), cross-checked against venue `liquidationPx` (trust the smaller if >5% of mark apart).
CLOSE parents pass unconditionally. `maint_margin_frac = 0.5/max_leverage`.

Engine grep: `risk::admit`, `Exposure`, `MarginView` have **no call sites in `crates/engine`**. What runs
instead is `hl_testnet_exp::guard::RunGuard` (`Limits{size_usd, max_order_usd, max_notional_usd,
max_loss_usd, max_actions, min_notional_cushion_pct, action_budget_floor_pct}`, guard.rs:107) per order, plus
`Core::preflight` (runner.rs:986): worst-price notional `touch × (1 ± max_slippage_bps) × qty ≤ max_order_usd`
and, for TT runs, a leg-S depth check of 1.25 × `lot_eff`. This is a testnet spend guard, not ED §8.4.

### 6.2 Kill switch flatten, `flatten_plan` (risk.rs:404-619) — wired (runner.rs:849)

Per leg: skip if `notional ≤ flat_tolerance_usd`; leg S only ever *sells* a long residue (never a spot buy);
leg P reduce-only, side from the sign of `filled_p`; touch missing or older than `ref_max_age_ms` → `NoTouch`
(no markPx fallback — ED §8.1 F3(ii) is described as the runner's job but the runner grep shows no `markPx`
use in flatten). Postability = `floor_sz > 0 ∧ meets_min_notional`, else `Dust`; a **short** perp dust is sized
up to `max(lot_eff, ceil_to_lot_eff)` reduce-only (D34). F2: if P has an unsent residue, S is `BlockedByP`.
Limit = `touch × (1 ± kill_flatten_slippage_bps)` (25 bps), rounded toward the touch, IOC; the runner retries
up to `kill_flatten_max_attempts` (3).

### 6.3 Max unhedged notional / time

- Per parent: `max_legging_time_ms` (2 s) via the hedger clock (§5.5); `max_unhedged_time_ms` (engine-wide)
  is **never read**.
- `imbalance_soft/hard` per parent (§5.4). `legging_tolerance_usd_s` never read (KPI only in TCA).
- Engine-wide `max_unhedged_notional_usd` only via the unwired `risk::admit`.

### 6.4 Stale halt and watchdog (engine/src/watchdog.rs)

W1 disconnect event, W2 any of the three feeds silent > `stale_halt_ms` (9 s; union of l2Book/bbo/trades per
coin as the runner feeds `on_feed_msg`), W3 `CancelUnconfirmed` (`cancel_confirm_ms`, 1 s), W4/W5 signal/panic
(`shutdown_cancel_budget_ms`, 2 s), W6 resting age. Halt = cancel all + sweep + stop admitting; the runner
routes it as a kill to the parent (runner tests `stale_book_halts_and_kills_parent`). Resting caps
(`maker_max_resting_notional_usd`, `max_resting_notional_usd`, `resting_equity_frac`) live in `RestingCaps`.
`schedule_cancel` is deliberately never called (venue DMS unavailable, parent.rs:62-64).

### 6.5 Request budget

`hl-budget` implements HL's nonce/budget model (address budget 10 000 + 1/USDC, cancel cap, IP weight, WS
message caps). `quote_budget_per_hour`, `action_budget_floor_pct`, `budget_throttle_mult` are **not consumed by
the quoter**: `requote_min_ms`/`requote_ticks` are never widened. The only budget floor is `RunGuard`'s
`action_budget_floor_pct` refusal (guard.rs:254). ED §8.5's throttle is unimplemented.

---

## 7. Inputs consumed vs ignored

| Input | Consumed by | Notes |
|---|---|---|
| HL `l2Book` (both legs) | `top()`, `depth_within`, `depth_recv_ns`; perp mid → `VolEwma`, `LeadLag` | 20 levels kept; ladder age gates depth |
| HL `bbo` (both legs) | `top()` only (L1 overlay), also feeds `VolEwma`/`LeadLag` via the perp mid | keeps touch young, not depth |
| HL `trades` leg S | `MedianTrade` (child_beta term) | only |
| HL `trades` leg P | **ignored** (parent.rs:334, `feed_quoter` matches `Leg::S` only) | |
| `orderUpdates` / `userFills` / post replies | OMS → `Filled` deltas → hedger; `Rejected` → ALO streak | fee amounts from `userFills` are *not* used for `credited_base` (static PARAMS rate) |
| funding rate / predicted funding | **ignored** | `funding_blackout_s` unread; no carry model |
| mark price / oracle | **ignored** on the algo path (only in `MarginView` for the unwired R3) | |
| external venue (Binance/Bybit) prices | **ignored** | crates exist, not wired to the quoter |
| account equity / margin | **ignored** by the algo (unwired `risk::admit`) | |
| own queue position / book imbalance / trade sign | **not computed** | |
| realised markouts (TCA) | offline only (`tca/src/quality.rs`); no feedback into any parameter | |

---

## 8. Quant assessment: weaknesses, hard-coding, missing feedback, doc/code mismatches

### 8.1 Design-doc vs code mismatches (ED says X, code does Y)

1. **TWAP envelope / participation cap absent** (ED §1.4, §3.2): `twap_room`, `max_imbalance_qty` = `i64::MAX`
   (parent.rs:778-780). `Switches::twap` and five parameters are dead. Large parents therefore front-run their
   own schedule and have no participation bound other than `clip_usd` and `child_beta × median`.
2. **Baseline EWMA absent** (ED §2.4): `baseline: None` (parent.rs:790). Default mode `relative_to_baseline`
   is in practice `absolute`. `min_absolute_basis_bps` never applies.
3. **CLOSE escape hatches absent** (ED §3.5): `close_blowout_bps`, `close_timeout_s` never read. A CLOSE that
   cannot post waits until `horizon_ms` (15 min), not `min(horizon, close_timeout_s)` = 5 min, and never
   crosses on a blow-out.
4. **Reprice is cancel+place, not `modify`** (ED §3.3): two actions per reprice, a window with nothing resting,
   and full loss of queue priority every `requote_ticks` move (parent.rs:798-801, 1235-1240).
5. **REST refresh of a stale reference absent** (ED §3.4, §5.2): `RefreshReference` is a no-op
   (parent.rs:1999), `ref_rest_refresh_ms` unread, `on_refresh_failed` never called. A stale-but-alive perp
   reference with a cold σ, or with `payup + buffer > max_slippage_bps`, leaves the hedge **un-sent until the
   next perp frame** (potentially ~5 s on a `bbo`-silent coin) while the legging clock runs.
6. **Pre-trade risk gate (R1–R3) not wired** (ED §8.4): `risk::admit` has no caller; ED §1.1 "no other parent
   open on the same pair" not checked in the algo. The engine's `RunGuard` is a spend cap.
7. **Request-budget throttle absent** (ED §8.5): `budget_throttle_mult`, `quote_budget_per_hour`,
   `action_budget_floor_pct` unused on the quote path.
8. **Lead-lag reference is HL perp only** (ED §3.3 "or a tracked CEX mid"): no external venue.
9. **TT after `tt_max_attempts` zero fills → S9 Failed** (parent.rs:1500-1503), not ED §5.5 escalation;
   `tt_leg_s_done` comment admits it.
10. **Kill flatten F3(ii) markPx fallback** not visible in the runner; a stale touch simply yields `NoTouch`.
11. **`hedge_trigger` switch is decorative**; `max_unhedged_time_ms`, `legging_tolerance_usd_s`, `risk_z`,
    `risk_budget_usd`, `priority_fee_bps`, `dms_*`, `funding_blackout_s` are parsed but never read by any
    decision (grep over `crates/**/src`).
12. **Fee used for credited base is the static PARAMS rate**, not the venue's per-fill `fee` (hedge.rs:296-299
    acknowledges this): any tier/discount mismatch leaks directly into G1 as a systematic long-spot (or, if the
    real fee is higher than configured, short-the-package) residue of `(fee_real − fee_cfg) × fill`.

### 8.2 Quant weaknesses in what *is* implemented

**Passive leg (the alpha-bearing decision).**
- The quote is a pure "join/improve-one-tick if the edge clears a static threshold" rule. No inventory skew,
  no fill-probability or queue model, no book-imbalance/microprice conditioning, no adverse-selection estimate
  beyond a 3 bps/200 ms perp-mid pull. The passive-vs-aggressive choice is binary (`E_tt ≥ threshold +
  tt_edge_bps`), with `tt_edge_bps` a hard constant (2 bps) rather than a function of expected time-to-fill or
  realised maker markouts.
- The stale buffer `2σ√age` is the only volatility-adaptive term, and σ is an EWMA of *perp mid returns
  sampled at every book event of either leg*, so it is a function of feed cadence: a busy spot book with a
  static perp drives σ → 0 (ED §3.1 acknowledges). It is not a clock-time realised-vol estimator and it does
  not scale any *size* or *limit*: `max_imbalance_usd`, `clip_usd`, `max_slippage_bps`, `hedge_payup_bps`,
  `pull_bps` are all static.
- Improve-one-tick is unconditional when the spread > 1 tick; on a 3-tick ETH spot spread the engine gives
  up one tick of edge on every quote regardless of queue depth ahead of it.
- Pull hysteresis is a fixed 1 bp with entry evaluated at `q_post` and pull at `r.px`; there is no dwell time
  or minimum resting age before a basis-decay pull, so a resting quote can be pulled and re-posted at the
  300 ms floor on basis noise around the threshold (each pull/place = 2 actions).
- No re-entry cool-down after a fill, no "don't reload the same price into the same adverse move" beyond the
  500 ms lead-lag cooldown.

**Sizing.**
- `child_alpha × depth_P(5 bps)` is a *static* instantaneous depth read of the top-20 ladder at a ≥5 s cadence
  on HL (bbo does not refresh depth); no depth-refill / resilience model, no trade-rate model, no time-of-day.
- `child_beta × median_trade` uses a 60 s lower-median of a ring of ≤ 256 trades, so on a quiet spot book the
  term either does not bind (no trades) or binds at a single stale print.
- No participation cap and no schedule ⇒ no impact control for large parents beyond `clip_usd`.

**Hedge.**
- Ladder rungs {0, 2, 5, 10} bps + 300 ms retry are constants; the escalation is not conditioned on observed
  perp depth, on σ, or on the distance the touch has already moved since the anchor (only clamped by it).
- The chase-vs-unwind tie-break compares *limit distance from own mid* (a price-cost proxy), not expected
  fill probability or the basis P&L of each outcome; the ED note "against its own fair value" is implemented
  as "against its own mid".
- Hedge IOCs are sized to exactly the fill delta with no aggregation window: a burst of small maker fills
  yields a burst of ≥$10 IOCs (each an action, each paying the spread) — there is no "wait up to N ms to batch"
  option other than the venue minimum.
- `max_imbalance_usd` is a fixed USD number per pair; the ED formula `risk_budget/(z·σ·√T)` is not evaluated.

**Feedback loops.** None. TCA (`crates/tca`) computes arrival/target basis, slippage decomposition, per-leg
and pair markouts at `markout_horizons_ms`, mode mix, legging integral and ops counters *offline* from the
JSONL; nothing feeds `improve_ticks`, `pull_bps`, `tt_edge_bps`, `hedge_slip_est_bps`, `child_alpha/beta`,
`entry_threshold_bps` or the passive-leg choice. `hedge_slip_est_bps` (3 bps) enters both the entry test and
the reservation price as a constant although the realised hedge cost is measured on every fill.

### 8.3 Hard-coded constants on the decision path (outside `AlgoConfig`)

- `RING = 256` (quote.rs:23) trade/mid ring; `MAX_PAYUP_RUNGS = 8` (config.rs:21).
- `VolEwma` warm-up "2 updates spanning ≥ 1 s" (quote.rs:666-671) and the weight form `dt/(dt+hl)`.
- Lead-lag "latest mid must be inside the window" (quote.rs:790) — a 200 ms window on a 5 s feed rarely arms.
- 5% mark disagreement threshold in R3 (risk.rs:308-314); `E/2` leg-S equity cap (risk.rs:220).
- Preflight `1.25 × lot_eff` depth requirement and `max_slippage_bps` worst-price rule (runner.rs:1043).
- `unwind_payup_bps × attempt` linear escalation (parent.rs:2367) — not in PARAMS.
- Unwind retry bound reuses `hedge_max_attempts` (parent.rs:2441) — no dedicated parameter.
- `MAX_CHILDREN = 4`, `DONE_RING = 4` (parent.rs:82, 87).

### 8.4 Correctness-adjacent observations worth a second look

- S2 has no horizon check by design (parent.rs:1873) and `next_wake_ns` in S2 is only the hedger's clocks; with
  an OPEN residue that is neither sendable nor short the package, `hedger_settled`-based transitions keep it out
  of S2, but a *sendable* residue whose every rung is `RefreshReference` (stale reference, cold σ) publishes no
  wake and no order until the next book event.
- `tt_enter` prices both TT legs at the full `max_slippage_bps` through the touch (parent.rs:648-673); a TT
  slice sized to `tt_depth_frac × min(depth)` will typically fill at the touch, but the *limit* concedes 10 bps
  and the "never walk the book" guarantee rests on the depth read being fresh.
- The ALO-reject streak → TT trigger fires `tt_enter(force_urgent=true)` regardless of `E_tt`, i.e. three ALO
  rejects convert a maker parent into a crossing one at any basis (parent.rs:1254).

---

## 9. Test coverage character

`crates/algo/tests` (7 files, ~86 test fns) are scenario-numbered acceptance tests driven through the public
`Parent` API with a fake `MarketView` and a recording `Io` on the SCENARIOS.md §0 HYPE/ETH fixture: SC-04
(partial fill hedges the delta only), SC-06 (stale reference pull/decline and stale-buffer hedge), SC-07 (ALO
reject streak → TT), SC-14 (TT leg-S zero fill sends no leg P), SC-18/19 (pair mismatch, zero-px hard refusal),
SC-05 A/B/B2/C (dust bucket, carried long-spot residue, CLOSE rule-3 over-hedge incl. late/partial fills),
SC-08 (four-rung ladder then unwind, never beyond `max_slippage_bps`, switch permutations), SC-09 (soft breach
→ S4 catch-up, hard breach → S5 without walking the ladder, unwind-off kills), SC-11 (kill from every
non-terminal state, flatten is reduce-only P-first, never a net short perp), SC-16/20/22/24 (sizing in
`lot_eff`, sub-lot gap, close-side spot sell below minimum, D30 credited base), and the D27/D29 residue
completion rules. Unit tests inside `src/` cover the arithmetic (basis identities incl. the ED §2.4 mainnet
table, reservation/quote rounding, `VolEwma`, `MedianTrade`, `LeadLag`, `hedge_size`, `taker_limit_px`,
`escalate_to`, R1–R3 and flatten bands, plus "no f64 / no heap" source scans). `crates/engine/tests/runner.rs`
(60 tests) drives `Core` with scripted WS frames: start gating on both books + user feed, TT and MT end-to-end
paths (quote → fill → hedge IOC with the fill-price bound → completion), TCA row emission and ordering,
watchdog W1/W2/W3/W6 and panic/operator kill, guard refusals, preflight caps/depth, flatten retry/stop and
flatten-fill routing. `runcard.rs` pins the shipped TESTNET_RUNS card to config fields; `basis_run_bin.rs` is
offline CLI/prepare coverage. What the suite does **not** exercise: any statistical property (fill rates,
markouts, slippage vs a benchmark), replayed real market data, multi-parent interaction, the TWAP/baseline/
CLOSE-hatch/budget-throttle paths (absent), or `risk::admit` end-to-end (unwired). Tests are deterministic
invariant checks on hand-built books, i.e. they verify the plumbing, not execution quality.
