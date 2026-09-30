import pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',600)
df=pd.read_csv('sor.csv')
for c in ['created_at','finished_at']: df[c]=pd.to_datetime(df[c])
df=df.sort_values(['created_at','id']).reset_index(drop=True)
ev=df[df.exchange_filled_qty>0][['finished_at','exchange','exchange_filled_qty']].sort_values('finished_at')
ev['I']=np.where(ev.exchange=='bybit',ev.exchange_filled_qty,-ev.exchange_filled_qty).cumsum()
def I_before(t):
    x=ev[ev.finished_at<t]; return x.I.iloc[-1] if len(x) else 0.0
df['I_before']=df.created_at.apply(I_before)
hl=df[df.exchange=='hyperliquid']; bb=df[df.exchange=='bybit']
print("HL qty==8.13: I_before distribution:", hl[hl.quantity>=8.129].I_before.round(2).describe().round(2).to_dict())
print(pd.cut(hl[hl.quantity>=8.129].I_before,[-9,-0.01,0.01,4,8.12,8.14,13]).value_counts().sort_index())
print("HL qty<8.13: I_before:", pd.cut(hl[hl.quantity<8.129].I_before,[-9,-0.01,0.01,4,8.12,8.14,13]).value_counts().sort_index())
print("HL qty<8.13: qty - I_before within 0.02:", ((hl[hl.quantity<8.129].quantity-hl[hl.quantity<8.129].I_before).abs()<0.02).mean().round(3))
print("Bybit qty==8.13: I_before:", pd.cut(bb[bb.quantity>=8.129].I_before,[-9,-0.01,0.01,4,8.12,8.14,13]).value_counts().sort_index())
print("Bybit qty<8.13: I_before:", pd.cut(bb[bb.quantity<8.129].I_before,[-9,-0.01,0.01,4,8.12,8.14,13]).value_counts().sort_index())
# idle periods: no open order on either exchange
t=df.created_at.min(); end=df.finished_at.max()
grid=pd.date_range(t,end,freq='1s'); openc=np.zeros(len(grid),dtype=int); openb=np.zeros(len(grid),dtype=int)
for _,r in df.iterrows():
    if r.exchange_status=='rejected': continue
    i0=int((r.created_at-t).total_seconds()); i1=int((r.finished_at-t).total_seconds())
    if r.exchange=='hyperliquid': openc[i0:i1+1]+=1
    else: openb[i0:i1+1]+=1
print("\nshare of seconds with an open HL order:", (openc>0).mean().round(3), " bybit:", (openb>0).mean().round(3), " both none:", ((openc==0)&(openb==0)).mean().round(3))
print("HL open-order count distribution (s):", pd.Series(openc).value_counts().sort_index().to_dict())
print("Bybit open-order count distribution (s):", pd.Series(openb).value_counts().sort_index().to_dict())
# idle runs > 20s
idle=(openc==0)&(openb==0); runs=[]; i=0
while i<len(idle):
    if idle[i]:
        j=i
        while j<len(idle) and idle[j]: j+=1
        if j-i>=20: runs.append((grid[i],j-i))
        i=j
    else: i+=1
print("idle runs >=20s:", runs)
