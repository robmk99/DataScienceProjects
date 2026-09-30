import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_columns',40); pd.set_option('display.max_rows',600)
df=pd.read_csv('sor.csv')
for c in ['created_at','finished_at','updated_at','exchange_timestamp','bookstats_updated_at']: df[c]=pd.to_datetime(df[c])
df=df.sort_values(['created_at','id']).reset_index(drop=True)
df['dur']=(df.finished_at-df.created_at).dt.total_seconds()
hl=df[df.exchange=='hyperliquid'].copy(); bb=df[df.exchange=='bybit'].copy()
print("=== counts"); print(df.groupby(['exchange','exchange_status']).size())
print("filled qty per leg:", hl.exchange_filled_qty.sum(), bb.exchange_filled_qty.sum())
print("fill ratio per order (closed only):"); 
for name,x in [('hl',hl),('bb',bb)]:
    c=x[x.exchange_status=='closed']; print(name, 'closed n',len(c),'full fills',(c.exchange_filled_qty>=c.quantity-1e-9).sum(),'partial',((c.exchange_filled_qty<c.quantity-1e-9)&(c.exchange_filled_qty>0)).sum(),'zero',(c.exchange_filled_qty==0).sum())
    cc=x[x.exchange_status=='cancelled']; print(name,'cancelled n',len(cc),'with partial fill',(cc.exchange_filled_qty>0).sum(), 'qty filled in cancelled', cc.exchange_filled_qty.sum())
print("\n=== duration (s) by exchange/status"); print(df.groupby(['exchange','exchange_status']).dur.describe())
# limit vs touch
tick={'hyperliquid':0.1,'bybit':0.01}
df['tk']=df.exchange.map(tick)
df['spread_ticks']=((df.exchange_ask-df.exchange_bid)/df.tk).round()
def rel(r):
    if r.side=='sell':
        return round((r.limit_price-r.exchange_bid)/r.tk)   # ticks above bid
    else:
        return round((r.exchange_ask-r.limit_price)/r.tk)   # ticks below ask
df['ticks_from_far']=df.apply(rel,axis=1)
def rel2(r):
    if r.side=='sell': return round((r.exchange_ask-r.limit_price)/r.tk)
    else: return round((r.limit_price-r.exchange_bid)/r.tk)
df['ticks_from_near']=df.apply(rel2,axis=1)
print("\n=== HL sells: spread_ticks vs ticks above bid (limit)"); print(pd.crosstab(df[df.exchange=='hyperliquid'].spread_ticks, df[df.exchange=='hyperliquid'].ticks_from_far))
print("\n=== Bybit buys: spread_ticks vs ticks below ask"); print(pd.crosstab(df[df.exchange=='bybit'].spread_ticks, df[df.exchange=='bybit'].ticks_from_far))
print("\n=== Bybit buys: limit - bid in ticks (negative = below bid)"); print(df[df.exchange=='bybit'].ticks_from_near.value_counts().sort_index())
# bookstats target formula
b=df[df.bookstats_bid.notna()].copy()
b['frac']=(b.bookstats_target-b.bookstats_bid)/(b.bookstats_ask-b.bookstats_bid)
print("\n=== bookstats target fraction of (bs_ask-bs_bid) by side/exchange"); print(b.groupby(['exchange','side']).frac.describe())
b['bs_bid_vs_bid']=(b.bookstats_bid-b.exchange_bid); b['bs_ask_vs_ask']=(b.bookstats_ask-b.exchange_ask)
print(b.groupby('exchange')[['bs_bid_vs_bid','bs_ask_vs_ask']].describe().T)
# limit vs target for HL sells
h=b[b.exchange=='hyperliquid']
print("\nHL sells: limit - target (should be >= 0 if target is a floor):", ((h.limit_price-h.bookstats_target)).describe())
print("HL: rows where limit < target:", (h.limit_price<h.bookstats_target-1e-9).sum(), 'of', len(h))
# sequence semantics
print("\n=== sequence by exchange/status"); print(pd.crosstab([df.exchange,df.exchange_status],df.sequence))
print("\n=== quantity distribution per exchange"); print(df.groupby('exchange').quantity.describe())
print("bybit qty==8.13:", (bb.quantity==8.13).sum(), 'HL qty==8.13:', (hl.quantity==8.13).sum())
# time gaps between consecutive orders on same exchange
for name,x in [('hl',hl),('bb',bb)]:
    x=x.sort_values('created_at'); gap=(x.created_at.diff().dt.total_seconds()); print(name,'gap between consecutive creates (s):', gap.describe().round(2).to_dict())
    # gap between finish of previous and create of next
    g2=(x.created_at.values[1:]-x.finished_at.values[:-1])/np.timedelta64(1,'s'); print(name,'prev.finish->next.create (s):', pd.Series(g2).describe().round(2).to_dict())
# fee
print("\nfees:", df.groupby('exchange').exchange_filled_fee.sum(), "notional", df.groupby('exchange').exchange_executed_cost.sum())
print("fee bps hl:", hl.exchange_filled_fee.sum()/hl.exchange_executed_cost.sum()*1e4, 'bb:', bb.exchange_filled_fee.sum()/bb.exchange_executed_cost.sum()*1e4)
print("HL errors:"); print(hl.exchange_error.dropna().str.extract(r'error\\\":\\\"([^\\\\]+)')[0].value_counts())
