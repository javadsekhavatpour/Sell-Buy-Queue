import numpy as np
import pandas as pd

REQUIRED = ["timestamp","last_price","lower_limit","upper_limit","real_buy_count","real_sell_count",
"real_buy_value","real_sell_value","cumulative_volume"] + \
[f"{side}{i}_volume" for side in ("ask","bid") for i in range(1,6)]

def div(a,b):
    a=np.asarray(a,dtype=float); b=np.asarray(b,dtype=float)
    return np.divide(a,b,out=np.full(np.broadcast(a,b).shape,np.nan),where=b!=0)

def build_features(raw):
    missing=[c for c in REQUIRED if c not in raw.columns]
    if missing: raise ValueError("ستون‌های ضروری موجود نیستند: "+", ".join(missing))
    d=raw.copy()
    d["timestamp"]=pd.to_datetime(d["timestamp"],errors="coerce")
    d=d.dropna(subset=["timestamp","last_price"]).sort_values("timestamp").reset_index(drop=True)
    for c in REQUIRED:
        if c!="timestamp": d[c]=pd.to_numeric(d[c],errors="coerce")
    d["ask5"]=d[[f"ask{i}_volume" for i in range(1,6)]].sum(axis=1,min_count=5)
    d["bid5"]=d[[f"bid{i}_volume" for i in range(1,6)]].sum(axis=1,min_count=5)

    counts=d.real_buy_count+d.real_sell_count
    values=d.real_buy_value+d.real_sell_value
    d["sell_breadth"]=div(d.real_sell_count-d.real_buy_count,counts)
    d["buy_breadth"]=-d.sell_breadth
    d["sell_flow"]=div(d.real_sell_value-d.real_buy_value,values)
    d["buy_flow"]=-d.sell_flow

    avg_b=div(d.real_buy_value,d.real_buy_count)
    avg_s=div(d.real_sell_value,d.real_sell_count)
    d["sell_ticket"]=np.log(div(avg_s,avg_b))
    d["buy_ticket"]=-d.sell_ticket

    ret=np.log(d.last_price/d.last_price.shift(6))
    d["sell_price"]=-ret
    d["buy_price"]=ret
    d["sell_supply"]=d.ask5.pct_change()-d.bid5.pct_change()

    ask_depletion=(-d.ask5.diff()).clip(lower=0)
    traded=d.cumulative_volume.diff().clip(lower=0)
    d["buy_absorption"]=div(np.minimum(ask_depletion,traded),d.ask5.shift(1))

    day_range=d.upper_limit-d.lower_limit
    d["sell_lower"]=1-div(d.last_price-d.lower_limit,day_range)

    low=d.last_price.rolling(36,min_periods=6).min()
    recovery=div(d.last_price-low,low)
    proximity=1-div(low-d.lower_limit,day_range)
    d["buy_support"]=(recovery.clip(lower=0)*proximity.clip(lower=0)).clip(lower=0)

    # 6 samples = 30 seconds when raw sampling is exactly every 5 seconds.
    return d.iloc[::6].copy().reset_index(drop=True)
