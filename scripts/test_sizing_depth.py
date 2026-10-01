#!/usr/bin/env python3
"""Does the competitor size its lead order off the order book?"""
import pandas as pd, numpy as np, glob, os
pd.set_option('display.width',260)
CR='/tmp/claude-0/-home-user-DataScienceProjects/2257be37-92d6-5246-b3d6-1e99f6af8862/scratchpad/cr/CR'
LEAD={'1':('bybit','ETH-USDT',8.13),'2':('bybit','VVV-USDT.PERP',65),
      '3':('bybit','AERO-USDT.PERP',1600),'5':('bybit','LIT-USDT.PERP',272.14),
      '8':('bybit','MON-USDT.PERP',20000),'9':('okex','ZEC-USDT.PERP',14),
      '11':('okex','TAO-USDT.PERP',4),'12':('okex','ZEC-USDT.PERP',7.854)}
BANDS=[1,2,5,10,25]
rows=[]
for case,(ex,pair,mlr) in LEAD.items():
    bf=f'data/book/case{case}_{ex}_{pair}_book.parquet'
    if not os.path.exists(bf): continue
    b=pd.read_parquet(bf).sort_values('ts'); b['ts']=b.ts.astype('datetime64[ns, UTC]')
    cr=pd.read_csv(glob.glob(f'{CR}/{case}/*.csv')[0])
    cr['created_at']=pd.to_datetime(cr.created_at).dt.tz_localize('UTC').astype('datetime64[ns, UTC]')
    g=cr[cr.exchange==ex].copy()
    lead=g[g.bookstats_bid.isna()]
    if len(lead)<30: lead=g
    lead=lead[lead.quantity>0].sort_values('created_at')
    side=lead.side.mode()[0]
    j=pd.merge_asof(lead[['created_at','quantity','side']], b, left_on='created_at', right_on='ts',
                    direction='backward', tolerance=pd.Timedelta('2s')).dropna(subset=['bid'])
    if len(j)<30: continue
    # own-side depth is what a resting order competes with; the other side is what can hit it
    own  = 'bid' if side=='buy' else 'ask'
    opp  = 'ask' if side=='buy' else 'bid'
    r={'case':case,'pair':pair,'n':len(j),'med_qty':round(j.quantity.median(),4)}
    cands={'touch_own':j[f'{own}_sz'], 'touch_opp':j[f'{opp}_sz']}
    for bd in BANDS:
        cands[f'own_d{bd}']=j[f'{own}_d{bd}']; cands[f'opp_d{bd}']=j[f'{opp}_d{bd}']
    best=None
    for k,v in cands.items():
        c=j.quantity.corr(v); ratio=(j.quantity/v.replace(0,np.nan))
        cv=ratio.std()/ratio.mean() if ratio.mean() else np.nan
        r[f'c_{k}']=round(c,2); r[f'f_{k}']=round(ratio.median(),3)
        if best is None or (cv==cv and cv<best[1]): best=(k,cv,ratio.median(),c)
    r['best_ref']=best[0]; r['best_cv']=round(best[1],2); r['best_frac']=round(best[2],3); r['best_corr']=round(best[3],2)
    r['cv_MLR']=round((j.quantity/mlr).std()/(j.quantity/mlr).mean(),2)
    rows.append(r)
R=pd.DataFrame(rows)
cc=[c for c in R.columns if c.startswith('c_')]
print("Correlation of the lead order size with book depth at the moment it was placed")
print(R[['case','pair','n','med_qty']+cc].to_string(index=False))
print()
print("Best-fitting reference per case (lowest dispersion of qty/reference), against the fixed-share-of-MLR model")
print(R[['case','pair','best_ref','best_corr','best_frac','best_cv','cv_MLR']].to_string(index=False))
