#!/usr/bin/env python3
"""Fine scan of opposite-side liquidity caps for the lead order size.

For each case and each candidate X (ask depth within k ticks, within x bps, or the
first k levels), fit c = median(q / X) on orders where the room is not binding, then
score the rule  q ~ min(room, c * X)  by (a) share of orders within ±10%, (b) Spearman
of q with X on the non-binding subset, (c) dispersion of q/X.
"""
import pandas as pd, numpy as np, glob, os, warnings
warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
from test_sizing_ladders import room_series, CR, N
CASES = {"1": ("ETH-USDT", 8.13, 0.01), "2": ("VVV-USDT.PERP", 65, 0.001),
         "3": ("AERO-USDT.PERP", 1600, 0.0001), "5": ("LIT-USDT.PERP", 272.14, 0.0001)}

def candidates(d, tick):
    asks_sz = np.stack([d[f"ask{k}_sz"].fillna(0).values for k in range(1, N + 1)], axis=1)
    asks_px = np.stack([d[f"ask{k}_px"].values for k in range(1, N + 1)], axis=1)
    out = {}
    cum = asks_sz.cumsum(axis=1)
    for k in [1, 2, 3, 4, 5, 7, 10]:
        out[f"L{k}"] = cum[:, k - 1]
    for kt in [1, 2, 3, 4, 5, 6, 8, 10, 15, 20, 30]:
        out[f"T{kt}"] = (asks_sz * (asks_px <= asks_px[:, [0]] + kt * tick + 1e-12)).sum(axis=1)
    for x in [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 7.5, 10]:
        out[f"B{x:g}"] = (asks_sz * (asks_px <= asks_px[:, [0]] * (1 + x / 1e4) + 1e-12)).sum(axis=1)
    # spread-relative: depth within one / two spread widths above the best ask
    spread = asks_px[:, [0]] - d[["bid1_px"]].values
    for m in [1, 2]:
        out[f"S{m}"] = (asks_sz * (asks_px <= asks_px[:, [0]] + m * spread + 1e-12)).sum(axis=1)
    return out

for case, (pair, mlr, tick) in CASES.items():
    f = f"data/ladders/case{case}_bybit_{pair}_ladders.parquet"
    if not os.path.exists(f):
        print(f"[missing] case {case}"); continue
    lad = pd.read_parquet(f); lad = lad[(lad.side == "buy") & (lad.lag_ms == 250)]
    rm = room_series(case, "bybit", mlr)
    d = lad.merge(rm, on=["created_at", "quantity"], how="left").dropna(subset=["room", "ask1_px"]).reset_index(drop=True)
    q = d.quantity.values; room = d.room.values
    rows = []
    for name, X in candidates(d, tick).items():
        X = np.asarray(X, float); ok = X > 0
        nb = ok & (q < 0.9 * room)                 # room not binding -> X should explain q
        if nb.sum() < 30: continue
        c = np.median(q[nb] / X[nb])
        pred = np.minimum(room, c * X)
        hit = np.mean(np.abs(q[ok] - pred[ok]) <= 0.10 * pred[ok])
        sp = pd.Series(q[nb]).corr(pd.Series(X[nb]), method="spearman")
        ratio = q[nb] / X[nb]
        rows.append((name, round(c, 3), round(hit, 3), round(sp, 2), round(float(np.log(ratio).std()), 2), int(nb.sum())))
    R = pd.DataFrame(rows, columns=["X", "c_fit", "hit10", "spearman_nb", "sd_log_ratio", "n_nb"]).sort_values("spearman_nb", ascending=False)
    nb_share = np.mean(q < 0.9 * room)
    print(f"\n=== case {case} {pair}  n={len(d)}  room not binding in {nb_share:.0%} of orders  (sd_log_ratio of q/room on those: {np.log(q[q<0.9*room]/room[q<0.9*room]).std():.2f})")
    print(R.head(10).to_string(index=False))
