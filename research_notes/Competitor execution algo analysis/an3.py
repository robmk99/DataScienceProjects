import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_columns',40); pd.set_option('display.max_rows',600)
df=pd.read_csv('sor.csv')
for c in ['created_at','finished_at','updated_at','exchange_timestamp','bookstats_updated_at']: df[c]=pd.to_datetime(df[c])
df=df.sort_values(['created_at','id']).reset_index(drop=True)
df['dur']=(df.finished_at-df.created_at).dt.total_seconds()
df['tk']=df.exchange.map({'hyperliquid':0.1,'bybit':0.01})
ev=df[df.exchange_filled_qty>0][['finished_at','exchange','exchange_filled_qty','exchange_executed_avg_price','id','funding_currency_cross_rate']].sort_values('finished_at')
ev['I']=np.where(ev.exchange=='bybit',ev.exchange_filled_qty,-ev.exchange_filled_qty).cumsum()
def I_before(t):
    x=ev[ev.finished_at<t]; return x.I.iloc[-1] if len(x) else 0.0
df['I_before']=df.created_at.apply(I_before)
def open_qty(r):
    x=df[(df.exchange==r.exchange)&(df.created_at<r.created_at)&(df.finished_at>r.created_at)&(df.exchange_status!='rejected')]
    return (x.quantity-x.exchange_filled_qty).sum()
df['open_qty']=df.apply(open_qty,axis=1)
df['bs']=df.bookstats_bid.notna()
print("=== HL: I_before sign vs bookstats presence"); print(pd.crosstab(df[df.exchange=='hyperliquid'].I_before>0.005, df[df.exchange=='hyperliquid'].bs))
print("=== Bybit: I_before sign vs bookstats presence"); print(pd.crosstab(np.sign(df[df.exchange=='bybit'].I_before.round(3)), df[df.exchange=='bybit'].bs))
# sizing hypotheses
hl=df[df.exchange=='hyperliquid'].copy(); bb=df[df.exchange=='bybit'].copy()
hl['pred']=np.minimum(hl.I_before,8.13)-hl.open_qty
print("\nHL qty - min(I,8.13)+open:", (hl.quantity-hl.pred).round(3).describe().to_dict()); print(" exact(<0.02):", ((hl.quantity-hl.pred).abs()<0.02).mean().round(3))
hl['pred2']=np.minimum(hl.I_before,8.13)
print(" HL qty - min(I,8.13):", ((hl.quantity-hl.pred2).abs()<0.02).mean().round(3))
bb['pred']=np.where(bb.I_before>=0, 8.13-bb.I_before, -bb.I_before)-bb.open_qty
print("Bybit qty - pred(open-adjusted):", ((bb.quantity-bb.pred).abs()<0.02).mean().round(3))
bb['pred2']=np.where(bb.I_before>=0, 8.13-bb.I_before, -bb.I_before)
print("Bybit qty - pred(no open adj):", ((bb.quantity-bb.pred2).abs()<0.02).mean().round(3))
bb['pred3']=8.13-bb.I_before-bb.open_qty
print("Bybit qty - (8.13-I-open):", ((bb.quantity-bb.pred3).abs()<0.02).mean().round(3))
mm=bb[(bb.quantity-bb.pred).abs()>=0.02]
print(mm[['created_at','finished_at','quantity','exchange_filled_qty','exchange_status','I_before','open_qty','pred','bs']].head(40).to_string())
# HL price: does target ever bind?  bid+tick vs target
hl['best_post']=hl.exchange_bid+0.1
hl['target_binds']=hl.best_post<hl.bookstats_target-1e-9
print("\nHL rows where bid+1tick < target:", hl.target_binds.sum(), "of", len(hl)); print(hl[hl.target_binds][['created_at','quantity','exchange_status','limit_price','exchange_bid','exchange_ask','bookstats_target','dur']].to_string())
# bookstats depth: relation of (bid - bs_bid) to quantity
hl['bid_gap']=hl.exchange_bid-hl.bookstats_bid; hl['ask_gap']=hl.bookstats_ask-hl.exchange_ask
print("\nHL corr(bid_gap, qty)=",hl.bid_gap.corr(hl.quantity).round(3), " corr(ask_gap, qty)=",hl.ask_gap.corr(hl.quantity).round(3))
print(hl.groupby(pd.cut(hl.quantity,[0,1,3,6,8.2]))[['bid_gap','ask_gap']].median())
bbb=bb[bb.bs]; bbb=bbb.assign(bid_gap=bbb.exchange_bid-bbb.bookstats_bid, ask_gap=bbb.bookstats_ask-bbb.exchange_ask)
print("Bybit corr(bid_gap,qty)=",bbb.bid_gap.corr(bbb.quantity).round(3), bbb.ask_gap.corr(bbb.quantity).round(3))
print(bbb.groupby(pd.cut(bbb.quantity,[0,1,3,6,8.2]))[['bid_gap','ask_gap']].median())
# bookstats_updated_at vs created_at
print("\nbookstats age at create (s):", ((df.created_at-df.bookstats_updated_at).dt.total_seconds()).describe().round(2).to_dict())
# bybit balancing price: limit vs bid / target
bbb=bbb.assign(best_post=bbb.exchange_ask-0.01)
print("\nBybit balancing: limit - bid ticks:", ((bbb.limit_price-bbb.exchange_bid)/0.01).round().value_counts().sort_index().to_dict())
print("Bybit balancing: limit vs target: limit<=target share", (bbb.limit_price<=bbb.bookstats_target+1e-9).mean().round(3), (bbb.limit_price-bbb.bookstats_target).describe().round(3).to_dict())
# hedge latency: spot fill -> next HL create
lat=[]; 
for _,f in ev[ev.exchange=='bybit'].iterrows():
    nxt=hl[hl.created_at>=f.finished_at]
    if len(nxt): lat.append((nxt.created_at.iloc[0]-f.finished_at).total_seconds())
print("\nspot fill -> next HL order create (s):", pd.Series(lat).describe().round(2).to_dict(), " share<=1s:", (pd.Series(lat)<=1).mean().round(3))
# time to hedge completion: for each spot fill, time until cumulative perp fills catch up
lat2=[]
for _,f in ev[ev.exchange=='bybit'].iterrows():
    target=f.I  # need perp cum to reach spot cum at that time => I<=0 later... use I<=I_now-f.qty? simpler: first later time when I <= f.I - f.exchange_filled_qty
    later=ev[(ev.finished_at>f.finished_at)&(ev.I<=f.I-f.exchange_filled_qty+1e-9)]
    lat2.append((later.finished_at.iloc[0]-f.finished_at).total_seconds() if len(later) else np.nan)
print("spot fill -> fully hedged (s):", pd.Series(lat2).describe().round(1).to_dict())
# exposure time series: time-weighted |I| in ETH and USD
ev2=ev.copy(); ev2['dt']=ev2.finished_at.shift(-1)-ev2.finished_at; ev2['dts']=ev2.dt.dt.total_seconds()
tw=(ev2.I.abs()*ev2.dts).sum()/ev2.dts.sum(); print("time-weighted |I| ETH:", round(tw,3), "USD:", round(tw*2681,0), " max I:", ev.I.max(), ev.I.min())
print("share of time I>8.13:", (ev2.dts[ev2.I>8.13+1e-6].sum()/ev2.dts.sum()).round(3), " I<0:", (ev2.dts[ev2.I<-1e-6].sum()/ev2.dts.sum()).round(3))
# realized spread vs cross rate
print("\ncross rates over time:", df.groupby(df.created_at.dt.floor('10min')).funding_currency_cross_rate.agg(['min','max']))
