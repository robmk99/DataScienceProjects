#!/usr/bin/env python3
"""Second batch of lead-sizing hypotheses: adaptive, randomised, notional, volatility, split."""
import pandas as pd, numpy as np, glob, os
pd.set_option('display.width',260); pd.set_option('display.max_columns',40)
CR='/tmp/claude-0/-home-user-DataScienceProjects/2257be37-92d6-5246-b3d6-1e99f6af8862/scratchpad/cr/CR'
LEAD={'1':('bybit','ETH-USDT',8.13),'2':('bybit','VVV-USDT.PERP',65),'3':('bybit','AERO-USDT.PERP',1600),
      '5':('bybit','LIT-USDT.PERP',272.14),'6':('binancefutures','PUMP-USDT.PERP',400000),
      '15':('binancefutures','PONS-USDT.PERP',2000),'8':('hyperliquid','MON-USD.PERP',20000),
      '9':('hyperliquid','ZEC-USD.PERP',14),'11':('hyperliquid','TAO-USD.PERP',4),'7':('lighter','LIT-USD.PERP',400)}

def load(case):
    cr=pd.read_csv(glob.glob(f'{CR}/{case}/*.csv')[0])
    for c in ['created_at','finished_at']: cr[c]=pd.to_datetime(cr[c])
    return cr.sort_values(['created_at','id']).reset_index(drop=True)

def lead_orders(cr, ex):
    g=cr[cr.exchange==ex].copy(); lead=g[g.bookstats_bid.isna()]
    if len(lead)<30: lead=g
    lead=lead[lead.quantity>0].sort_values('created_at').copy()
    lead['dur']=(lead.finished_at-lead.created_at).dt.total_seconds()
    lead['fillfrac']=lead.exchange_filled_qty/lead.quantity
    lead['full']=lead.fillfrac>=0.999
    lead['cancel']=lead.exchange_status=='cancelled'
    lead['rej']=lead.exchange_status=='rejected'
    return lead

out=[]
for case,(ex,pair,mlr) in LEAD.items():
    cr=load(case); L=lead_orders(cr,ex)
    if len(L)<60: continue
    q=L.quantity.values; lq=np.log(q)
    r={'case':case,'pair':pair,'n':len(L)}
    # A. notional vs base dispersion
    px=L.limit_price.values; notional=q*px
    r['cv_qty']=round(q.std()/q.mean(),2); r['cv_usd']=round(notional.std()/notional.mean(),2)
    # B. multiplicative update: log(q_t/q_{t-1}) by what happened to the previous order
    dl=pd.Series(np.diff(lq)); prev=L.iloc[:-1].reset_index(drop=True)
    r['dlog|prev_full']=round(dl[prev.full.values].median(),2) if prev.full.any() else np.nan
    r['dlog|prev_partial']=round(dl[(~prev.full.values)&(prev.fillfrac.values>0)].median(),2) if ((~prev.full)&(prev.fillfrac>0)).any() else np.nan
    r['dlog|prev_cancel']=round(dl[prev.cancel.values].median(),2) if prev.cancel.any() else np.nan
    r['dlog|prev_rej']=round(dl[prev.rej.values].median(),2) if prev.rej.any() else np.nan
    # C. adaptive to recent fill speed: size vs mean duration of the previous k filled orders
    d=L.dur.where(L.full)  # time-to-fill only for full fills
    for k in [3,10]:
        rm=d.shift(1).rolling(k,min_periods=2).mean()
        r[f'corr_prevfill_dur{k}']=round(pd.Series(lq,index=L.index).corr(np.log(rm+1)),2)
    # recent fill fraction of lead orders
    ff=L.fillfrac.shift(1).rolling(10,min_periods=3).mean()
    r['corr_prev_fillfrac10']=round(pd.Series(lq,index=L.index).corr(ff),2)
    # D. split across open lead orders: qty vs (room / n_open)
    open_n=[]; 
    for i,row in L.iterrows():
        o=L[(L.created_at<row.created_at)&(L.finished_at>row.created_at)]
        open_n.append(len(o))
    L['open_n']=open_n
    r['share_open_n>0']=round((L.open_n>0).mean(),2)
    r['qty_med|open0']=round(L[L.open_n==0].quantity.median()/mlr,3)
    r['qty_med|open1+']=round(L[L.open_n>0].quantity.median()/mlr,3) if (L.open_n>0).any() else np.nan
    # E. time-of-day structure: how much of variance is explained by 10-min bucket means
    b=L.created_at.dt.floor('10min'); gm=L.groupby(b).quantity.transform('mean')
    r['R2_10min_bucket']=round(1-((L.quantity-gm)**2).sum()/((L.quantity-L.quantity.mean())**2).sum(),2)
    r['n_10min']=b.nunique()
    out.append(r)
R=pd.DataFrame(out)
print("A. Is the clip tighter in USD than in coins?  (cv_usd < cv_qty would mean a notional rule)")
print(R[['case','pair','n','cv_qty','cv_usd']].to_string(index=False))
print("\nB. Multiplicative update: median log(q_t/q_{t-1}) conditioned on the previous order's outcome")
print(R[['case','dlog|prev_full','dlog|prev_partial','dlog|prev_cancel','dlog|prev_rej']].to_string(index=False))
print("\nC. Adaptive to own fill speed / fill rate (negative corr with duration = bigger after fast fills)")
print(R[['case','corr_prevfill_dur3','corr_prevfill_dur10','corr_prev_fillfrac10']].to_string(index=False))
print("\nD. Lead Max Order Count 2: is the size halved when another lead order is already resting?")
print(R[['case','share_open_n>0','qty_med|open0','qty_med|open1+']].to_string(index=False))
print("\nE. Share of size variance explained by 10-minute bucket means (slow regime vs per-order noise)")
print(R[['case','n_10min','R2_10min_bucket']].to_string(index=False))
