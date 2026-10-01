#!/usr/bin/env python3
"""Which opposite-side liquidity measure caps the lead order?  Uses the per-event ladders.

For a BUY lead the candidates are, on the ASK side of the lead venue:
  L_k   = sum of the first k ask levels (k = 1..10)
  T_k   = ask depth within k ticks of the best ask
  B_x   = ask depth within x bps of the best ask
and the rule tested is  qty ~ min(room, c * X)  for c in {1, 2, 3}.
room = Max Leg Risk - imbalance - resting lead qty (reconstructed from the log).
"""
import pandas as pd, numpy as np, glob, os, warnings
warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
CR = "/tmp/claude-0/-home-user-DataScienceProjects/2257be37-92d6-5246-b3d6-1e99f6af8862/scratchpad/cr/CR"
CASES = {"1": ("ETH-USDT", 8.13, 0.01), "2": ("VVV-USDT.PERP", 65, 0.001),
         "3": ("AERO-USDT.PERP", 1600, 0.0001), "5": ("LIT-USDT.PERP", 272.14, 0.0001)}
N = 10

def room_series(case, ex, mlr):
    cr = pd.read_csv(glob.glob(f"{CR}/{case}/*.csv")[0])
    for c in ["created_at", "finished_at"]:
        cr[c] = pd.to_datetime(cr[c]).dt.tz_localize("UTC")
    cr = cr.sort_values(["created_at", "id"]).reset_index(drop=True)
    ev = cr[cr.exchange_filled_qty > 0][["finished_at", "exchange", "exchange_filled_qty"]].sort_values("finished_at")
    ev["I"] = np.where(ev.exchange == ex, ev.exchange_filled_qty, -ev.exchange_filled_qty).cumsum()
    g = cr[cr.exchange == ex]; lead = g[g.bookstats_bid.isna()]
    if len(lead) < 30: lead = g
    L = lead[lead.quantity > 0].copy()
    L["I"] = L.created_at.apply(lambda t: ev[ev.finished_at < t].I.iloc[-1] if (ev.finished_at < t).any() else 0.0)
    L["open_lead"] = [lead[(lead.created_at < t) & (lead.finished_at > t) & (lead.exchange_status != "rejected")].quantity.sum() for t in L.created_at]
    L["room"] = (mlr - L.I.clip(lower=0) - L.open_lead).clip(lower=0)
    return L[["created_at", "quantity", "room"]]

def close(a, b, tol=0.05):
    return float(((a - b).abs() <= tol * np.maximum(b, 1e-12)).mean())

def main():
    for case, (pair, mlr, tick) in CASES.items():
        f = f"data/ladders/case{case}_bybit_{pair}_ladders.parquet"
        if not os.path.exists(f):
            print(f"[missing] {f}"); continue
        lad = pd.read_parquet(f); lad = lad[lad.side == "buy"]
        rm = room_series(case, "bybit", mlr)
        lad = lad.merge(rm, on=["created_at", "quantity"], how="left").dropna(subset=["room"])
        best_rows = []
        for lag in sorted(lad.lag_ms.unique()):
            d = lad[lad.lag_ms == lag].copy()
            q = d.quantity
            cands = {}
            asks_sz = np.stack([d[f"ask{k}_sz"].fillna(0).values for k in range(1, N + 1)], axis=1)
            asks_px = np.stack([d[f"ask{k}_px"].values for k in range(1, N + 1)], axis=1)
            cum = asks_sz.cumsum(axis=1)
            for k in range(1, N + 1): cands[f"L{k}"] = cum[:, k - 1]
            for kt in [1, 2, 3, 5, 10, 20]:
                lim = asks_px[:, [0]] + kt * tick + 1e-12
                cands[f"T{kt}"] = (asks_sz * (asks_px <= lim)).sum(axis=1)
            for x in [0.5, 1, 2, 3, 5, 10]:
                lim = asks_px[:, [0]] * (1 + x / 1e4) + 1e-12
                cands[f"B{x:g}"] = (asks_sz * (asks_px <= lim)).sum(axis=1)
            for name, X in cands.items():
                X = pd.Series(X, index=d.index)
                for c in [1, 2, 3]:
                    pred = np.minimum(d.room, c * X)
                    best_rows.append((lag, name, c, close(q, pred), close(q, c * X), float((q / (c * X).replace(0, np.nan)).median()), float(q.corr(X, method="spearman"))))
        R = pd.DataFrame(best_rows, columns=["lag", "X", "c", "hit_min", "hit_X", "q/cX_p50", "spearman"]).sort_values("hit_min", ascending=False)
        print(f"\n=== case {case} {pair}: n={len(lad[lad.lag_ms==0])} lead orders; top rules by share of orders within ±5% of min(room, c*X)")
        print(R.head(8).to_string(index=False))
        print("baseline: q within ±5% of room alone:", round(close(lad[lad.lag_ms == 0].quantity, lad[lad.lag_ms == 0].room), 2))

if __name__ == "__main__":
    main()
