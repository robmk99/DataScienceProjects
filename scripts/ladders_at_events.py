#!/usr/bin/env python3
"""Record the top-N levels of a Bybit book at the competitor's lead-order creation times.

Writes one row per (order, lag) with ask1..askN / bid1..bidN prices and sizes, so any
cap/size rule can be tested offline without replaying the dump again.
"""
import json, zipfile, io, sys, bisect, glob, urllib.request, shutil
from pathlib import Path
import pandas as pd, numpy as np
CR='/tmp/claude-0/-home-user-DataScienceProjects/2257be37-92d6-5246-b3d6-1e99f6af8862/scratchpad/cr/CR'
CASES={'1':('ETH-USDT','spot',['2026-09-29']),'2':('VVV-USDT.PERP','linear',['2026-09-29']),
       '3':('AERO-USDT.PERP','linear',['2026-09-29']),'5':('LIT-USDT.PERP','linear',['2026-09-28','2026-09-29'])}
N=10; LAGS=[0,250,500,1000]
out=Path('data/ladders'); out.mkdir(parents=True,exist_ok=True); tmp=Path('/tmp/obraw2'); tmp.mkdir(exist_ok=True)
for case,(pair,cat,days) in CASES.items():
    sym=pair.replace('.PERP','').replace('-','')
    cr=pd.read_csv(glob.glob(f'{CR}/{case}/*.csv')[0]); cr['created_at']=pd.to_datetime(cr.created_at).dt.tz_localize('UTC')
    g=cr[cr.exchange=='bybit']; lead=g[g.bookstats_bid.isna()]
    if len(lead)<30: lead=g
    L=lead[lead.quantity>0].sort_values('created_at')
    ev_ms=sorted({int(t.timestamp()*1000)+lag for t in L.created_at for lag in LAGS})
    want=set(ev_ms); rows={}
    bids={}; asks={}; T=[]; S=[]
    for d in days:
        raw=tmp/f'{d}_{sym}_ob200.data'
        if not raw.exists():
            url=f'https://quote-saver.bycsi.com/orderbook/{cat}/{sym}/{d}_{sym}_ob200.data.zip'
            z=tmp/(raw.name+'.zip'); print('downloading',url,flush=True)
            with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=1800) as r, open(z,'wb') as f: shutil.copyfileobj(r,f,1<<20)
            with zipfile.ZipFile(z) as zz: zz.extractall(tmp)
            z.unlink()
        print('replaying',raw.name,flush=True)
        for line in open(raw):
            m=json.loads(line); ts=m['ts']; dd=m['data']
            if m['type']=='snapshot':
                bids={float(p):float(s) for p,s in dd['b'] if float(s)>0}; asks={float(p):float(s) for p,s in dd['a'] if float(s)>0}
            else:
                for p,s in dd['b']:
                    p,s=float(p),float(s); bids.pop(p,None) if s==0 else bids.__setitem__(p,s)
                for p,s in dd['a']:
                    p,s=float(p),float(s); asks.pop(p,None) if s==0 else asks.__setitem__(p,s)
            T.append(ts); S.append((sorted(asks.items())[:N], sorted(bids.items(),reverse=True)[:N]))
    T=np.array(T)
    recs=[]
    for _,r in L.iterrows():
        base=int(r.created_at.timestamp()*1000)
        for lag in LAGS:
            i=np.searchsorted(T, base+lag, side='right')-1
            if i<0: continue
            a,b=S[i]; rec={'case':case,'created_at':r.created_at,'lag_ms':lag,'book_ts':int(T[i]),'quantity':r.quantity,'limit_price':r.limit_price,'side':r.side,'status':r.exchange_status}
            for k in range(N):
                rec[f'ask{k+1}_px']=a[k][0] if k<len(a) else np.nan; rec[f'ask{k+1}_sz']=a[k][1] if k<len(a) else np.nan
                rec[f'bid{k+1}_px']=b[k][0] if k<len(b) else np.nan; rec[f'bid{k+1}_sz']=b[k][1] if k<len(b) else np.nan
            recs.append(rec)
    df=pd.DataFrame(recs); df.to_parquet(out/f'case{case}_bybit_{pair}_ladders.parquet',index=False)
    print(f'[ok] case {case}: {len(df)} rows',flush=True)
    T=None; S=None
