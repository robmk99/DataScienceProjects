#!/usr/bin/env python3
"""Test what the competitor's lead order size is a function of, using venue tape."""
import pandas as pd, numpy as np, glob, sys
pd.set_option('display.width',250)

CR='/tmp/claude-0/-home-user-DataScienceProjects/2257be37-92d6-5246-b3d6-1e99f6af8862/scratchpad/cr/CR'
LEAD={'1':('bybit','ETH-USDT',8.13),'2':('bybit','VVV-USDT.PERP',65),'3':('bybit','AERO-USDT.PERP',1600),
      '5':('bybit','LIT-USDT.PERP',272.14),'6':('binancefutures','PUMP-USDT.PERP',400000),
      '15':('binancefutures','PONS-USDT.PERP',2000)}

def tape(case, ex, pair):
    f=f'data/case{case}_{ex}_{pair}_trades.parquet'
    t=pd.read_parquet(f)
    col=next(c for c in ('size','volume','quantity') if c in t.columns)  # bybit linear / bybit spot / binance
    q=t[col].astype(float)
    return pd.DataFrame({'ts':pd.to_datetime(t.ts,utc=True),'q':q}).sort_values('ts').reset_index(drop=True)

rows=[]
for case,(ex,pair,mlr) in LEAD.items():
    cr=pd.read_csv(glob.glob(f'{CR}/{case}/*.csv')[0])
    for c in ['created_at','finished_at']: cr[c]=pd.to_datetime(cr[c]).dt.tz_localize('UTC')
    cr=cr.sort_values(['created_at','id'])
    exname={'bybit':'bybit','binancefutures':'binancefutures'}[ex]
    lead=cr[(cr.exchange==exname)&(cr.bookstats_bid.isna())].copy()   # lead role: no contra bookstats
    if len(lead)<30: lead=cr[cr.exchange==exname].copy()
    tp=tape(case,ex,pair)
    tsec=tp.set_index('ts').q.resample('1s').sum().fillna(0)
    # rolling traded volume ending at order creation
    feats={}
    for w in [5,10,30,60,300]:
        roll=tsec.rolling(f'{w}s').sum()
        feats[f'vol{w}s']=roll.reindex(lead.created_at, method='ffill').values
    F=pd.DataFrame(feats, index=lead.index)
    F['qty']=lead.quantity.values; F['mlr']=mlr
    F=F[F.qty>0].dropna()
    r={'case':case,'venue':ex,'pair':pair,'n':len(F),'qty_med':round(F.qty.median(),4),'qty/MLR':round(F.qty.median()/mlr,3)}
    for w in [5,10,30,60,300]:
        c_=F.qty.corr(F[f'vol{w}s']); r[f'corr{w}s']=round(c_,2)
        ratio=(F.qty/F[f'vol{w}s'].replace(0,np.nan))
        r[f'frac{w}s']=round(ratio.median(),4)
        r[f'cv{w}s']=round(ratio.std()/ratio.mean(),2) if ratio.mean() else np.nan
    # compare against the constant-fraction-of-MLR model
    r['cv_MLR']=round((F.qty/mlr).std()/(F.qty/mlr).mean(),2)
    rows.append(r)
R=pd.DataFrame(rows)
print(R[['case','venue','pair','n','qty_med','qty/MLR','corr5s','corr10s','corr30s','corr60s','corr300s']].to_string(index=False))
print()
print("Dispersion of qty/X (lower = better explanation). cv_MLR is the 'fixed share of Max Leg Risk' model:")
print(R[['case','pair','cv_MLR','cv5s','cv10s','cv30s','cv60s','cv300s']].to_string(index=False))
print()
print("Median qty as a share of traded volume in the window:")
print(R[['case','pair','frac5s','frac10s','frac30s','frac60s','frac300s']].to_string(index=False))
