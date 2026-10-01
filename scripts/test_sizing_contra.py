#!/usr/bin/env python3
"""Is the competitor's LEAD order sized off the BALANCING venue's book?

The hedge has to be absorbed on the contra venue, so a natural rule is
   lead_qty = k * (depth available on the contra venue, on the side the hedge will cross)
This is the last candidate left after volume, own-book depth, risk room,
parent remaining and time pacing were all ruled out.
"""
import pandas as pd, numpy as np, glob, os
pd.set_option('display.width',260)
CR='/tmp/claude-0/-home-user-DataScienceProjects/2257be37-92d6-5246-b3d6-1e99f6af8862/scratchpad/cr/CR'
# case -> (lead venue, contra venue, contra pair, Max Leg Risk)
CASES={'7':('lighter','bybit','LIT-USDT',400),
       '8':('hyperliquid','bybit','MON-USDT.PERP',20000),
       '11':('hyperliquid','okex','TAO-USDT.PERP',4),
       '12':('bitget','okex','ZEC-USDT.PERP',7.854),
       '9':('hyperliquid','okex','ZEC-USDT.PERP',14)}
BANDS=[1,2,5,10,25]
rows=[]
for case,(leadex,conex,conpair,mlr) in CASES.items():
    bf=f'data/book/case{case}_{conex}_{conpair}_book.parquet'
    if not os.path.exists(bf):
        print(f"[skip case {case}] no contra book yet"); continue
    b=pd.read_parquet(bf).sort_values('ts'); b['ts']=b.ts.astype('datetime64[ns, UTC]')
    cr=pd.read_csv(glob.glob(f'{CR}/{case}/*.csv')[0])
    cr['created_at']=pd.to_datetime(cr.created_at).dt.tz_localize('UTC').astype('datetime64[ns, UTC]')
    g=cr[cr.exchange==leadex].copy()
    lead=g[g.bookstats_bid.isna()]
    if len(lead)<30: lead=g
    lead=lead[lead.quantity>0].sort_values('created_at')
    if len(lead)<30: continue
    lead_side=lead.side.mode()[0]
    # the hedge is the opposite side of the lead, and it crosses, so it eats the
    # contra book's ask when the hedge buys and its bid when the hedge sells
    hedge_side='sell' if lead_side=='buy' else 'buy'
    eats='bid' if hedge_side=='sell' else 'ask'
    j=pd.merge_asof(lead[['created_at','quantity']], b, left_on='created_at', right_on='ts',
                    direction='backward', tolerance=pd.Timedelta('3s')).dropna(subset=['bid'])
    if len(j)<30: continue
    r={'case':case,'lead':leadex,'contra':f'{conex} {conpair}','n':len(j),'eats':eats}
    best=None
    cands={'touch':j[f'{eats}_sz']}
    for bd in BANDS: cands[f'd{bd}']=j[f'{eats}_d{bd}']
    for k,v in cands.items():
        c=j.quantity.corr(v); ratio=j.quantity/v.replace(0,np.nan)
        cv=ratio.std()/ratio.mean() if ratio.mean() else np.nan
        r[f'c_{k}']=round(c,2); r[f'cv_{k}']=round(cv,2); r[f'f_{k}']=round(ratio.median(),3)
        if best is None or (cv==cv and cv<best[1]): best=(k,cv,ratio.median(),c)
    r['best']=best[0]; r['best_corr']=round(best[3],2); r['best_frac']=round(best[2],3); r['best_cv']=round(best[1],2)
    r['cv_MLR']=round((j.quantity/mlr).std()/(j.quantity/mlr).mean(),2)
    rows.append(r)
if not rows:
    print("no cases ready"); raise SystemExit
R=pd.DataFrame(rows)
print("Lead order size vs the depth the hedge will have to cross on the contra venue")
print(R[['case','lead','contra','n','eats']+[f'c_{k}' for k in ['touch']+[f'd{b}' for b in BANDS]]].to_string(index=False))
print()
print("Best contra reference per case, against the fixed-share-of-Max-Leg-Risk baseline")
print(R[['case','contra','best','best_corr','best_frac','best_cv','cv_MLR']].to_string(index=False))
