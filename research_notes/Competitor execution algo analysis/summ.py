import pandas as pd, numpy as np, glob, os, json, re
pd.set_option('display.width',300); pd.set_option('display.max_columns',60); pd.set_option('display.max_rows',100)
rows=[]
for d in sorted(glob.glob('*/'), key=lambda s:int(s.strip('/'))):
    f=glob.glob(d+'*.csv')[0]; df=pd.read_csv(f)
    for c in ['created_at','finished_at']: df[c]=pd.to_datetime(df[c])
    df=df.sort_values(['created_at','id']).reset_index(drop=True)
    df['dur']=(df.finished_at-df.created_at).dt.total_seconds()
    legs=df.groupby(['exchange','currency_pair','side']).size().index.tolist()
    n=len(df); t0=df.created_at.min(); t1=df.finished_at.max(); mins=(t1-t0).total_seconds()/60
    otypes=df.order_type.value_counts().to_dict(); po=df.use_post_only.value_counts().to_dict()
    taker=(df.taker_quantity.fillna(0)>0).sum(); takerq=df.taker_quantity.fillna(0).sum(); makerq=df.maker_quantity.fillna(0).sum()
    oc=df[[c for c in df.columns if c.startswith('oc_')]].notna().sum().sum()
    st=df.exchange_status.value_counts().to_dict()
    rej=df[df.exchange_status=='rejected'].exchange_error.fillna('').astype(str).str.extract(r'error\\?"?:?\\?"?([A-Za-z][^,\\"]{0,60})')[0].value_counts().head(3).to_dict()
    per={}
    for ex,g in df.groupby('exchange'):
        per[ex]=dict(n=len(g), filled=round(g.exchange_filled_qty.sum(),4), notional=round(g.exchange_executed_cost.sum()), fee_bps=round(g.exchange_filled_fee.sum()/max(g.exchange_executed_cost.sum(),1e-9)*1e4,2), tier=g.account_fee_tier.iloc[0], rej=int((g.exchange_status=='rejected').sum()), canc=int((g.exchange_status=='cancelled').sum()), qty_med=round(g.quantity.median(),4), qty_max=round(g.quantity.max(),4), bs=int(g.bookstats_bid.notna().sum()), dur_med=g[g.exchange_status=='closed'].dur.median(), pairs=sorted(g.currency_pair.unique().tolist()), sides=sorted(g.side.unique().tolist()))
    rows.append(dict(id=d.strip('/'), parent=df.client_order_id.iloc[0][:8], start=str(t0), mins=round(mins,1), n=n, otypes=otypes, post_only=po, taker_orders=int(taker), taker_qty=round(takerq,4), maker_qty=round(makerq,4), oc_nonnull=int(oc), status=st, rej_reasons=rej, strategy=df.strategy.iloc[0], owner=df.owner.iloc[0], per=per))
for r in rows:
    print("="*100); print({k:v for k,v in r.items() if k!='per'})
    for ex,v in r['per'].items(): print("   ",ex,v)
