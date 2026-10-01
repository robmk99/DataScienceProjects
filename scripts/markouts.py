#!/usr/bin/env python3
"""Markout of the competitor's passive lead fills against the venue tape."""
import pandas as pd, numpy as np, glob
pd.set_option('display.width',250)
CR='/tmp/claude-0/-home-user-DataScienceProjects/2257be37-92d6-5246-b3d6-1e99f6af8862/scratchpad/cr/CR'
CASES={'1':('bybit','ETH-USDT','buy'),'2':('bybit','VVV-USDT.PERP','buy'),'3':('bybit','AERO-USDT.PERP','buy'),
       '5':('bybit','LIT-USDT.PERP','buy'),'6':('binancefutures','PUMP-USDT.PERP','buy'),
       '15':('binancefutures','PONS-USDT.PERP','buy'),'7':('bybit','LIT-USDT','sell'),'8':('bybit','MON-USDT.PERP','sell')}
HOR=[1,5,30,60]
rows=[]
for case,(ex,pair,side) in CASES.items():
    try: t=pd.read_parquet(f'data/case{case}_{ex}_{pair}_trades.parquet')
    except Exception: continue
    pcol='price'; t=t[['ts',pcol]].dropna().sort_values('ts').reset_index(drop=True)
    t['ts']=pd.to_datetime(t.ts,utc=True).astype('datetime64[ns, UTC]')
    cr=pd.read_csv(glob.glob(f'{CR}/{case}/*.csv')[0])
    cr['finished_at']=pd.to_datetime(cr.finished_at).dt.tz_localize('UTC').astype('datetime64[ns, UTC]')
    f=cr[(cr.exchange==ex)&(cr.exchange_filled_qty>0)].copy()
    f=f[['finished_at','exchange_executed_avg_price','exchange_filled_qty','side']].dropna()
    if not len(f): continue
    sgn=np.where(f.side=='buy',1,-1)
    r={'case':case,'pair':pair,'side':','.join(sorted(f.side.unique())),'fills':len(f)}
    for h in HOR:
        fut=pd.merge_asof(f.assign(tt=f.finished_at+pd.Timedelta(seconds=h)).sort_values('tt'),
                          t.rename(columns={'ts':'tt',pcol:'p_fut'}), on='tt', direction='forward',
                          tolerance=pd.Timedelta(seconds=30))
        fut=fut.dropna(subset=['p_fut'])
        s=np.where(fut.side=='buy',1,-1)
        mk=s*(fut.p_fut-fut.exchange_executed_avg_price)/fut.exchange_executed_avg_price*1e4
        w=fut.exchange_filled_qty
        r[f'mk{h}s']=round(float((mk*w).sum()/w.sum()),2)
        r[f'n{h}']=len(fut)
    rows.append(r)
R=pd.DataFrame(rows)
print("Size-weighted markout of the competitor's fills, bps, signed so negative = the price moved against them")
print(R[['case','pair','side','fills']+[f'mk{h}s' for h in HOR]].to_string(index=False))
print("\n(positive = the fill was followed by a favourable move; this is the adverse-selection cost their TCA does not report)")
