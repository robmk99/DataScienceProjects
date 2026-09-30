import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_columns',40); pd.set_option('display.max_rows',600)
df=pd.read_csv('sor.csv')
for c in ['created_at','finished_at','updated_at','exchange_timestamp','bookstats_updated_at']: df[c]=pd.to_datetime(df[c])
df=df.sort_values(['created_at','id']).reset_index(drop=True)
df['dur']=(df.finished_at-df.created_at).dt.total_seconds()
df['role']=np.where(df.exchange=='bybit', np.where(df.bookstats_bid.notna(),'balancing','leading'), np.where(df.quantity>=8.129,'leading','balancing'))
print(pd.crosstab([df.exchange,df.role],df.exchange_status))
print(df.groupby(['exchange','role']).agg(n=('id','size'),qty_mean=('quantity','mean'),qty_med=('quantity','median'),filled=('exchange_filled_qty','sum'),dur_med=('dur','median'),dur_mean=('dur','mean')))
# HL quantity check: is HL 'leading' qty always 8.13 and 'balancing' qty = imbalance?
# reconstruct exposure using finished_at as fill time (closed orders)
ev=[]
for _,r in df.iterrows():
    if r.exchange_filled_qty>0:
        ev.append((r.finished_at, 'spot' if r.exchange=='bybit' else 'perp', r.exchange_filled_qty, r.exchange_executed_avg_price, r.role, r.id))
ev=pd.DataFrame(ev,columns=['t','leg','q','px','role','id']).sort_values('t')
ev['spot_cum']=np.where(ev.leg=='spot',ev.q,0).cumsum(); ev['perp_cum']=np.where(ev.leg=='perp',ev.q,0).cumsum()
ev['imb']=ev.spot_cum-ev.perp_cum
print("\n=== imbalance (spot-perp filled, ETH) at fill events: ", ev.imb.describe().round(3).to_dict())
print("max |imb| =", ev.imb.abs().max(), " share of time... events with |imb|>8.13:", (ev.imb.abs()>8.13+1e-6).sum())
# at each order creation, compute imbalance just before
def imb_at(t):
    x=ev[ev.t<t]
    return (x.spot_cum.iloc[-1]-x.perp_cum.iloc[-1]) if len(x) else 0.0
df['imb_before']=df.created_at.apply(imb_at)
# outstanding resting qty on same exchange at creation (orders created earlier, finished later)
def resting(r):
    x=df[(df.exchange==r.exchange)&(df.created_at<r.created_at)&(df.finished_at>r.created_at)]
    return len(x), (x.quantity-x.exchange_filled_qty).sum()
rr=df.apply(resting,axis=1,result_type='expand'); df['open_n']=rr[0]; df['open_qty']=rr[1]
print("\n=== concurrent open orders on same exchange at creation"); print(pd.crosstab([df.exchange,df.role],df.open_n))
# Leading bybit qty vs 8.13 - imb_before - open_qty
lb=df[(df.exchange=='bybit')&(df.role=='leading')].copy()
lb['pred']=8.13-lb.imb_before.clip(lower=0)-lb.open_qty
lb['diff']=lb.quantity-lb['pred']
print("\nBybit leading: quantity - (8.13 - imb+ - open_qty):", lb['diff'].describe().round(4).to_dict())
print((lb['diff'].abs()<0.02).mean(), "within 0.02")
# HL balancing qty vs imbalance before
hb=df[(df.exchange=='hyperliquid')&(df.role=='balancing')].copy()
hb['diff']=hb.quantity-hb.imb_before+hb.open_qty
print("\nHL balancing: quantity - (imb_before - open_qty):", hb['diff'].describe().round(4).to_dict(), (hb['diff'].abs()<0.02).mean())
hl_lead=df[(df.exchange=='hyperliquid')&(df.role=='leading')].copy()
hl_lead['pred']=8.13+hl_lead.imb_before.clip(upper=0)-hl_lead.open_qty
print("HL leading qty - (8.13 - imb- - open):", (hl_lead.quantity-hl_lead.pred).describe().round(4).to_dict())
bbal=df[(df.exchange=='bybit')&(df.role=='balancing')].copy()
bbal['diff']=bbal.quantity-(-bbal.imb_before)+bbal.open_qty
print("Bybit balancing qty - (-imb_before - open):", bbal['diff'].describe().round(4).to_dict())
# hedge latency: lead fill -> balancing order create on other exchange
lat=[]
for _,f in ev[ev.role=='leading'].iterrows():
    other='hyperliquid' if f.leg=='spot' else 'bybit'
    nxt=df[(df.exchange==other)&(df.role=='balancing')&(df.created_at>=f.t)]
    if len(nxt): lat.append((nxt.created_at.iloc[0]-f.t).total_seconds())
print("\nlead fill -> next balancing create (s):", pd.Series(lat).describe().round(2).to_dict())
# time from balancing create to its fill (closed only)
for ex in ['hyperliquid','bybit']:
    x=df[(df.exchange==ex)&(df.role=='balancing')]
    print(ex,'balancing status', x.exchange_status.value_counts().to_dict(), 'closed dur', x[x.exchange_status=='closed'].dur.describe().round(1).to_dict())
# cancelled orders: what happened to the touch between create and finish?
c=df[df.exchange_status=='cancelled'].copy()
c['far_move_ticks']=np.where(c.side=='sell',(c.exchange_bid-(c.limit_price-df.exchange.map({'hyperliquid':0.1,'bybit':0.01})[c.index]))/df.exchange.map({'hyperliquid':0.1,'bybit':0.01})[c.index], ((c.limit_price)-c.exchange_bid)/df.exchange.map({'hyperliquid':0.1,'bybit':0.01})[c.index])
print("\ncancelled: relation of limit to touch at finish"); print(c[['exchange','role','side','dur','limit_price','exchange_bid','exchange_ask']].to_string())
