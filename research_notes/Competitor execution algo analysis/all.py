import pandas as pd, numpy as np, glob
pd.set_option('display.width',300); pd.set_option('display.max_columns',60); pd.set_option('display.max_rows',400)
meta={ '1':('ETH','bybit','Aggressive','Far_peg','Make/Make',8.13,None),'2':('VVV','bybit','Aggressive','Far_peg','Make/Make',65,None),'3':('AERO','bybit','Aggressive','Far_peg','Make/Make',1600,None),
 '4':('MORPHO aster','asterperps','Aggressive','Far_peg','Make/Make',375.1,None),'5':('LIT','bybit','Aggressive','Far_peg','Make/Make',272.14,None),'6':('PUMP','binancefutures','Aggressive','Far_peg','Make/Make',400000,None),
 '7':('LIT lighter','lighter','Aggressive','Far_peg','Make/Make',400,None),'8':('MON','hyperliquid','Aggressive','Far_peg','Make/Make',20000,None),'9':('ZEC hl/okx','hyperliquid','Aggressive','Far_peg','Make/Make',14,0.03),
 '10':('BTC bitget','bitget','Aggressive','Far_peg','Make/Make',0.25,0.1),'11':('TAO','hyperliquid','Aggressive','Far_peg','Make/Take',4,None),'12':('ZEC bitget/okx','bitget','Neutral','Far_peg','Make/Make',7.854,None),
 '13':('ETH bitget','bitget','Neutral','Far_peg','Make/Make',16,0.05),'14':('BTC bitget2','bitget','Neutral','Far_peg','Make/Make',0.24,0.05),'15':('PONS','binancefutures','Aggressive','Far_peg','Make/Make',2000,0.04)}
def tick(s):
    s=s.dropna().round(10); d=np.diff(np.sort(s.unique())); d=d[d>1e-12]
    if len(d)==0: return np.nan
    m=d.min()
    # snap to power of ten
    return 10**np.floor(np.log10(m)+1e-9)
rows=[]; pricing=[]
for k,(name,leadex,la,ba,es,mlr,mqd) in meta.items():
    f=glob.glob(f'{k}/*.csv')[0]; df=pd.read_csv(f)
    for c in ['created_at','finished_at']: df[c]=pd.to_datetime(df[c])
    df=df.sort_values(['created_at','id']).reset_index(drop=True); df['dur']=(df.finished_at-df.created_at).dt.total_seconds()
    df['role']=np.where(df.exchange==leadex,'lead','bal')
    if k=='4': df['role']=np.where(df.side=='buy','lead','bal')
    for ex,g in df.groupby('exchange'):
        tk=tick(pd.concat([g.limit_price,g.exchange_bid,g.exchange_ask]))
        df.loc[g.index,'tk']=tk
    df['spread_t']=((df.exchange_ask-df.exchange_bid)/df.tk).round()
    df['from_bid_t']=((df.limit_price-df.exchange_bid)/df.tk).round(); df['from_ask_t']=((df.exchange_ask-df.limit_price)/df.tk).round()
    df['mid_own']=np.where(df.side=='buy', np.floor((df.exchange_bid+df.exchange_ask)/2/df.tk+1e-9)*df.tk, np.ceil((df.exchange_bid+df.exchange_ask)/2/df.tk-1e-9)*df.tk)
    df['is_mid']=(df.limit_price-df.mid_own).abs()<df.tk*0.01
    df['is_join']=np.where(df.side=='buy', (df.limit_price-df.exchange_bid).abs()<df.tk*0.01, (df.limit_price-df.exchange_ask).abs()<df.tk*0.01)
    df['is_far1']=np.where(df.side=='buy', (df.limit_price-(df.exchange_ask-df.tk)).abs()<df.tk*0.01, (df.limit_price-(df.exchange_bid+df.tk)).abs()<df.tk*0.01)
    df['crosses']=np.where(df.side=='buy', df.limit_price>=df.exchange_ask-1e-12, df.limit_price<=df.exchange_bid+1e-12)
    fast=df[df.dur<=1]
    for (ex,role,po,ot),g in fast.groupby(['exchange','role','use_post_only','order_type']):
        wide=g[g.spread_t>=2]
        pricing.append(dict(order=k, name=name, ex=ex, role=role, post_only=po, otype=ot, n=len(g), n_wide=len(wide), join=round(g.is_join.mean(),2), mid=round(g.is_mid.mean(),2), far1=round(g.is_far1.mean(),2), crosses=round(g.crosses.mean(),2),
            wide_join=round(wide.is_join.mean(),2) if len(wide) else None, wide_mid=round(wide.is_mid.mean(),2) if len(wide) else None, wide_far1=round(wide.is_far1.mean(),2) if len(wide) else None, wide_cross=round(wide.crosses.mean(),2) if len(wide) else None,
            taker_share=round((g.taker_quantity.fillna(0)>0).mean(),2)))
    # exposure
    ev=df[df.exchange_filled_qty>0][['finished_at','role','exchange_filled_qty']].sort_values('finished_at'); ev['I']=np.where(ev.role=='lead',ev.exchange_filled_qty,-ev.exchange_filled_qty).cumsum()
    ev['dts']=(ev.finished_at.shift(-1)-ev.finished_at).dt.total_seconds()
    twI=(ev.I.abs()*ev.dts).sum()/max(ev.dts.sum(),1)
    lead=df[df.role=='lead']; bal=df[df.role=='bal']
    lat=[]; lat2=[]
    for _,fl in ev[ev.role=='lead'].iterrows():
        nxt=bal[bal.created_at>=fl.finished_at]
        if len(nxt): lat.append((nxt.created_at.iloc[0]-fl.finished_at).total_seconds())
        later=ev[(ev.finished_at>fl.finished_at)&(ev.I<=fl.I-fl.exchange_filled_qty+1e-9)]
        lat2.append((later.finished_at.iloc[0]-fl.finished_at).total_seconds() if len(later) else np.nan)
    t=df.created_at.min(); end=df.finished_at.max(); n=int((end-t).total_seconds())+1; oc=np.zeros(n)
    for _,r in df.iterrows():
        if r.exchange_status=='rejected': continue
        oc[int((r.created_at-t).total_seconds()):int((r.finished_at-t).total_seconds())+1]+=1
    notional=df.exchange_executed_cost.sum()/2
    rej=df.groupby('exchange').exchange_status.apply(lambda s:round((s=='rejected').mean(),2)).to_dict()
    fees=df.groupby('exchange').apply(lambda g: round(g.exchange_filled_fee.sum()/max(g.exchange_executed_cost.sum(),1e-9)*1e4,2)).to_dict()
    b=df[df.bookstats_bid.notna()]; frac=((b.bookstats_target-b.bookstats_bid)/(b.bookstats_ask-b.bookstats_bid)).groupby([b.exchange,b.side]).mean().round(2).to_dict()
    # MQD test: distance limit vs bookstats_target for orders with bookstats
    mq=None
    if len(b): mq=round(((b.limit_price-b.bookstats_target).abs()/b.bookstats_target*100).quantile(0.99),4)
    rows.append(dict(order=k,name=name,es=es,lead_aggr=la,mins=round((end-t).total_seconds()/60),notional_usd=round(notional),usd_per_min=round(notional/((end-t).total_seconds()/60)),mlr=mlr,lead_qty_med_over_mlr=round(lead.quantity.median()/mlr,2),
        twI_over_mlr=round(twI/mlr,2), share_I_neg=round(ev.dts[ev.I<-1e-9].sum()/max(ev.dts.sum(),1),2), share_I_gt_mlr=round(ev.dts[ev.I>mlr*1.001].sum()/max(ev.dts.sum(),1),2),
        hedge_create_med=np.nanmedian(lat) if lat else None, hedged_med=np.nanmedian(lat2) if lat2 else None, hedged_p90=np.nanpercentile(lat2,90) if lat2 else None, idle=round((oc==0).mean(),2), rej=rej, fees=fees, frac=frac, mqd=mqd, dist99pct=mq))
print(pd.DataFrame(rows).to_string())
print(); print(pd.DataFrame(pricing).to_string())
