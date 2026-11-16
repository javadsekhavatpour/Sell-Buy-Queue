import argparse
import pandas as pd
from config import MIN_HISTORY, SELL_WEIGHTS, BUY_WEIGHTS
from engines.features import build_features
from engines.adaptive import score_frame
from engines.alerts import tier, classify

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--input",required=True)
    ap.add_argument("--output",default="گزارش_موتور_خرید_فروش.xlsx")
    args=ap.parse_args()
    raw=pd.read_csv(args.input,encoding="utf-8-sig")
    f=build_features(raw)
    s=score_frame(f,SELL_WEIGHTS,MIN_HISTORY)
    b=score_frame(f,BUY_WEIGHTS,MIN_HISTORY)
    summary=pd.DataFrame({"timestamp":f.timestamp,"sell_score":s.score,"buy_score":b.score,
        "sell_status":s.engine_status,"buy_status":b.engine_status})
    summary["sell_tier"]=summary.sell_score.apply(lambda x:tier(x) if pd.notna(x) else "نامشخص")
    summary["buy_tier"]=summary.buy_score.apply(lambda x:tier(x) if pd.notna(x) else "نامشخص")
    summary["alert"]=[classify(x if pd.notna(x) else None,y if pd.notna(y) else None)
                      for x,y in zip(summary.sell_score,summary.buy_score)]
    detail=f.copy()
    for k in SELL_WEIGHTS:
        detail[k+"_score"]=s[k+"_score"]; detail[k+"_status"]=s[k+"_status"]
    for k in BUY_WEIGHTS:
        detail[k+"_score"]=b[k+"_score"]; detail[k+"_status"]=b[k+"_status"]
    detail["sell_total"]=s.score; detail["buy_total"]=b.score; detail["alert"]=summary.alert
    with pd.ExcelWriter(args.output,engine="openpyxl") as w:
        summary.to_excel(w,sheet_name="خلاصه هشدار",index=False)
        detail.to_excel(w,sheet_name="جزئیات شاخص‌ها",index=False)
    print("گزارش ساخته شد:",args.output)
    print("تعداد نمونه‌های ۳۰ ثانیه‌ای:",len(f))
    print("برای امتیاز رسمی، حداقل ۳۰ مشاهده تاریخی برای هر شاخص لازم است.")

if __name__=="__main__": main()
