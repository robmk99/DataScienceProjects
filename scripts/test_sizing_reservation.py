#!/usr/bin/env python3
"""Lead size vs contra depth available down to the reservation price lead*(1+target)."""
import pandas as pd, numpy as np, glob, os
pd.set_option('display.width',250)
CR='/tmp/claude-0/-home-user-DataScienceProjects/2257be37-92d6-5246-b3d6-1e99f6af8862/scratchpad/cr/CR'
BANDS=[0.5,1,1.5,2,3,4,5,6,8,10,12,15,20,25,30,40,50]
CASES={'8':('hyperliquid','buy','bybit','MON-USDT.PERP',-0.0012,20000),
       '9':('hyperliquid','buy','okex','ZEC-USDT.PERP',-0.0011,14),
       '11':('hyperliquid','buy','okex','TAO-USDT.PERP',-0.0005,4),
       '7':('lighter','buy','bybit','LIT-USDT',0.0005,400)}
def col(side,b): return f'{side}_d{float(b)}'
def depth_at(row, side, thr):
    xs=np.array(BANDS); ys=np.array([row[col(side,b)] for b in BANDS])
    if thr<=0: return 0.0
    if thr>=xs[-1]: return ys[-1]
    return float(np.interp(thr, xs, ys))
rows=[]
for case,(lex,lside,cex,cpair,tgt,mlr) in CASES.items():
    bf=f'data/book_fine/case{case}_{cex}_{cpair}_book.parquet'
    if not os.path.exists(bf): print('[missing]',bf); continue
    b=pd.read_parquet(bf).sort_values('ts'); b['ts']=b.ts.astype('datetime64[ns, UTC]'); b['mid']=(b.bid+b.ask)/2
    cr=pd.read_csv(glob.glob(f'{CR}/{case}/*.csv')[0]); cr['created_at']=pd.to_datetime(cr.created_at).dt.tz_localize('UTC').astype('datetime64[ns, UTC]')
    g=cr[cr.exchange==lex]; lead=g[g.bookstats_bid.isna()]
    if len(lead)<30: lead=g
    lead=lead[(lead.quantity>0)&(lead.side==lside)].sort_values('created_at')
    j=pd.merge_asof(lead[['created_at','quantity','limit_price','funding_currency_cross_rate']], b, left_on='created_at', right_on='ts', direction='backward', tolerance=pd.Timedelta('3s')).dropna(subset=['bid'])
    hs='bid' if lside=='buy' else 'ask'
    out={'case':case,'contra':f'{cex} {cpair}','n':len(j),'tgt_bps':tgt*1e4}
    cross=j.funding_currency_cross_rate.replace(0,np.nan).fillna(1.0)
    for name,pstar in [('lead_px',j.limit_price),('reserv',j.limit_price*(1+tgt)),('reserv_x',j.limit_price*(1+tgt)/cross)]:
        thr=np.where(hs=='bid',(j.mid-pstar)/j.mid*1e4,(pstar-j.mid)/j.mid*1e4)
        d=np.array([depth_at(r,hs,t) for (_,r),t in zip(j.iterrows(),thr)])
        ok=d>0
        out[f'thr_{name}']=round(float(np.median(thr)),1); out[f'n_{name}']=int(ok.sum())
        if ok.sum()>30:
            ratio=j.quantity[ok]/d[ok]
            out[f'corr_{name}']=round(float(np.corrcoef(j.quantity[ok],d[ok])[0,1]),2)
            out[f'cv_{name}']=round(float(ratio.std()/ratio.mean()),2); out[f'frac_{name}']=round(float(np.median(ratio)),3)
    out['cv_MLR']=round(float((j.quantity/mlr).std()/(j.quantity/mlr).mean()),2)
    rows.append(out)
R=pd.DataFrame(rows)
print("thr = how many bps below the contra mid the hedge may reach; corr/cv of lead size vs cumulative contra depth down to that price")
cols=['case','contra','n','tgt_bps']+[c for c in R.columns if c.startswith(('thr_','n_','corr_','cv_'))]
print(R[cols].to_string(index=False))
