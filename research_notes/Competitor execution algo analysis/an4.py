import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_columns',40); pd.set_option('display.max_rows',600)
df=pd.read_csv('sor.csv')
for c in ['created_at','finished_at','updated_at','exchange_timestamp','bookstats_updated_at']: df[c]=pd.to_datetime(df[c])
df=df.sort_values(['created_at','id']).reset_index(drop=True)
df['dur']=(df.finished_at-df.created_at).dt.total_seconds()
tk={'hyperliquid':0.1,'bybit':0.01}
# cancel -> replacement analysis
for ex in ['hyperliquid','bybit']:
    x=df[df.exchange==ex].reset_index(drop=True)
    rows=[]
    for i,r in x.iterrows():
        if r.exchange_status!='cancelled': continue
        nxt=x[(x.created_at>=r.finished_at-pd.Timedelta(seconds=1))&(x.id>r.id)]
        if len(nxt)==0: rows.append((r.id,r.dur,'none',None,None)); continue
        n=nxt.iloc[0]
        gap=(n.created_at-r.finished_at).total_seconds()
        same_qty=abs(n.quantity-r.quantity)<0.001
        dpx=round((n.limit_price-r.limit_price)/tk[ex])
        rows.append((r.id,r.dur,'resize' if not same_qty else 'reprice',dpx,gap))
    rr=pd.DataFrame(rows,columns=['id','dur','kind','dpx_ticks','gap_s'])
    print(f"=== {ex} cancels: kind"); print(rr.kind.value_counts().to_dict()); print(" reprice dpx ticks:", rr[rr.kind=='reprice'].dpx_ticks.value_counts().sort_index().to_dict()); print(" gap cancel-finish -> new create (s):", rr.gap_s.describe().round(1).to_dict())
    print(" dur by kind:", rr.groupby('kind').dur.median().to_dict())
# rejected -> retry
x=df[df.exchange=='hyperliquid'].reset_index(drop=True)
gaps=[]; dpx=[]
for i,r in x.iterrows():
    if r.exchange_status!='rejected': continue
    nxt=x[(x.id>r.id)]
    if len(nxt): n=nxt.iloc[0]; gaps.append((n.created_at-r.finished_at).total_seconds()); dpx.append(round((n.limit_price-r.limit_price)/0.1))
print("\nHL reject -> next HL create gap (s):", pd.Series(gaps).describe().round(1).to_dict()); print(" next limit - rejected limit ticks:", pd.Series(dpx).value_counts().sort_index().to_dict())
# rejects: bbo in error vs limit
err=x[x.exchange_status=='rejected'].copy()
err['bbo']=err.exchange_error.str.extract(r'bbo was ([0-9]+(?:\.[0-9]+)?)@([0-9]+(?:\.[0-9]+)?)').astype(float).apply(tuple,axis=1)
err['bid_err']=err.bbo.str[0]; err['ask_err']=err.bbo.str[1]
err['limit_vs_bid_err']=((err.limit_price-err.bid_err)/0.1).round()
print("rejects: limit - bid(at venue) ticks:", err.limit_vs_bid_err.value_counts().sort_index().to_dict())
print("rejects: bid_err - exchange_bid(logged) ticks:", ((err.bid_err-err.exchange_bid)/0.1).round().value_counts().sort_index().to_dict())
# overlapping HL orders both filled
h=x.copy(); over=[]
for i,r in h.iterrows():
    o=h[(h.id!=r.id)&(h.created_at<=r.created_at)&(h.finished_at>r.created_at)&(h.exchange_filled_qty>0)&(r.exchange_filled_qty>0)]
    if len(o): over.append((r.id, r.created_at, r.quantity, r.exchange_filled_qty, o.id.iloc[0], o.quantity.iloc[0], o.exchange_filled_qty.iloc[0]))
print("\nHL overlapping orders where both filled:", len(over)); print(pd.DataFrame(over,columns=['id','t','qty','filled','other','oqty','ofilled']).to_string())
# HL order lifetime for closed by fill
c=x[x.exchange_status=='closed']; print("\nHL closed (filled) dur:", c.dur.describe().round(1).to_dict())
# spread realized with cross
b=df[df.exchange=='bybit']; hh=df[df.exchange=='hyperliquid']
vs=(b.exchange_executed_cost.sum()/b.exchange_filled_qty.sum()); vp=(hh.exchange_executed_cost.sum()/hh.exchange_filled_qty.sum())
print("\nVWAP spot USDT", round(vs,3), "VWAP perp USD", round(vp,3), "gross spread raw bps", round((vp-vs)/vs*1e4,2))
cr=(b.exchange_executed_cost*b.funding_currency_cross_rate).sum()/b.exchange_filled_qty.sum()
print("spot VWAP in USD via cross", round(cr,3), "spread with cross bps", round((vp-cr)/cr*1e4,2))
# throughput
t0=df.created_at.min(); t1=df.finished_at.max(); print("\nrun", t0, t1, (t1-t0).total_seconds()/60, "min; ETH/min", 813/((t1-t0).total_seconds()/60))
# per 5-min fill volume
fills=df[df.exchange_filled_qty>0]; print(fills.groupby([fills.finished_at.dt.floor('5min'),'exchange']).exchange_filled_qty.sum().unstack().round(2))
# bybit lead: limit==bid at creation? use rejected-free: orders with dur<=1
bl=b[(b.bookstats_bid.isna())]
print("\nBybit lead limit - bid (ticks) for dur<=1s:", ((bl[bl.dur<=1].limit_price-bl[bl.dur<=1].exchange_bid)/0.01).round().value_counts().sort_index().to_dict())
print("Bybit lead: spread ticks at finish:", ((bl.exchange_ask-bl.exchange_bid)/0.01).round().value_counts().sort_index().head(5).to_dict())
print("sequence vs status/exchange/dur:"); print(df.groupby(['exchange','exchange_status','sequence']).dur.agg(['size','median']).head(40))
