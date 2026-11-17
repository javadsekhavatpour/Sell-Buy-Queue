"""
تشخیص بازار و ساعت معاملات ۴ نماد (سرود، دابور، اهرم، ریتون)
و ذخیره در config/symbols.json.
"""
import sys, json
from pathlib import Path

BASE = Path("/home/z/my-project/download/TSE_Screener")
sys.path.insert(0, str(BASE))
import os; os.chdir(BASE)

from early_warning.data_collector import MarketDataCollector
from early_warning.market_detector import detect_market, in_trading_window

cfg = json.load(open("config/warning_thresholds.json", encoding="utf-8"))
collector = MarketDataCollector(cfg)

# ۴ نماد هدف با کدهای شناسایی‌شده
TARGETS = [
    ("\u0633\u0631\u0648\u062f", "11964419322927535"),   # سرود — سیمان شاهرود
    ("\u062f\u0627\u0628\u0648\u0631", "61332057061846617"),  # دابور — داروسازی ابوریحان
    ("\u0627\u0647\u0631\u0645", "17914401175772326"),   # اهرم — صندوق سهامی کاریزما
    ("\u0631\u06cc\u062a\u0648\u0646", "14035144070182412"),  # ریتون — صندوق کالای پاسارگاد
]

results = []
print("=" * 70)
print("تشخیص بازار و ساعت معاملات ۴ نماد")
print("=" * 70)
for name, code in TARGETS:
    print(f"\n--- {name} (code={code}) ---")
    m = detect_market(collector, code)
    if m["ok"]:
        print(f"  symbol:       {m['symbol']}")
        print(f"  full_name:    {m['full_name']}")
        print(f"  isin:         {m['isin']}")
        print(f"  flow:         {m['flow']}")
        print(f"  market_type:  {m['market_type']}")
        print(f"  market_label: {m['market_label']}")
        print(f"  pre_open:     {m['trading_hours']['pre_open']}")
        print(f"  continuous:   {m['trading_hours']['continuous']}")
        print(f"  session:      {m['session_minutes']} min")
        # تست in_trading_window برای چند زمان
        for t in ["08:00", "09:30", "11:00", "12:30", "14:00", "17:00"]:
            ok, msg = in_trading_window(m["trading_hours"], t)
            print(f"    {t} -> {'\u2713' if ok else '\u2717'} {msg}")
        results.append({
            "name": name,
            "ticker": m["symbol"],
            "ins_code": code,
            "isin": m["isin"],
            "flow": m["flow"],
            "full_name": m["full_name"],
            "market_type": m["market_type"],
            "market_label": m["market_label"],
            "instrument_type": m["instrument_type"],
            "trading_hours": m["trading_hours"],
            "session_minutes": m["session_minutes"],
            "days": m["days"],
        })
    else:
        print(f"  FAIL: {m.get('error')}")
        results.append({"name": name, "ins_code": code, "ok": False, "error": m.get("error")})

# ذخیره در config/symbols.json
out = {
    "description": "\u0644\u06cc\u0633\u062a ۴ \u0646\u0645\u0627\u062f \u0628\u0631\u0627\u06cc \u062c\u0645\u0639\u200c\u0622\u0648\u0631\u06cc \u062f\u0627\u062f\u0647 \u0628\u0627 \u062a\u0634\u062e\u06cc\u0635 \u0628\u0627\u0632\u0627\u0631 \u0648 \u0633\u0627\u0639\u062a \u0645\u0639\u0627\u0645\u0644\u0627\u062a",
    "symbols": results,
}
Path("config/symbols.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\n{'=' * 70}")
print(f"\u2713 ذخ062e\u064a\u0631\u0647 \u062f\u0631 config/symbols.json ({len(results)} \u0646\u0645\u0627\u062f)")
print("=" * 70)
