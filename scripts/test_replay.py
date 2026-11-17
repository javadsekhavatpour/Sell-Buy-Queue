"""
تست web_replay.py: بازسازی snapshot + بازپخش موتورها + ساختار timeline.
داده واقعی: Archive/data/early_warning.sqlite (دابور، ۱۴۰۳-۰۸-۱۹، ۲۲۶ نمونه).
"""
import sys, os, json, py_compile
from pathlib import Path

BASE = Path("/home/z/my-project/download/TSE_Screener")
os.chdir(BASE)
sys.path.insert(0, str(BASE))

print("=" * 60)
print("۱. SYNTAX CHECK")
print("=" * 60)
py_compile.compile("web_replay.py", doraise=True)
print("  ✓ syntax صحیح")

print()
print("=" * 60)
print("۲. IMPORT + بازسازی snapshot")
print("=" * 60)
import web_replay as rp
from early_warning import MarketDataStorage
storage = MarketDataStorage(Path("Archive/data/early_warning.sqlite"))
rows = storage.get_snapshots_for_symbol("دابور", limit=3)
snap = rp.snapshot_from_db_row(rows[1])  # ردیف دوم (continuous)
print(f"  symbol: {snap.symbol}")
print(f"  tehran_time: {snap.tehran_time}")
print(f"  last_price: {snap.last_price}")
print(f"  market_phase: {snap.market_phase}")
print(f"  buy_rows: {len(snap.buy_rows)} ردیف")
print(f"  sell_rows: {len(snap.sell_rows)} ردیف")
if snap.buy_rows:
    print(f"  bid_1: price={snap.buy_rows[0].price}, vol={snap.buy_rows[0].volume}")
if snap.sell_rows:
    print(f"  ask_1: price={snap.sell_rows[0].price}, vol={snap.sell_rows[0].volume}")
print("  ✓ بازسازی snapshot موفق")

print()
print("=" * 60)
print("۳. بازپخش کامل روز دابور ۱۴۰۳-۰۸-۱۹")
print("=" * 60)
cfg = json.load(open("config/warning_thresholds.json", encoding="utf-8"))
result = rp.replay_day(storage, cfg, "دابور", "1403-08-19")
print(f"  ok: {result['ok']}")
print(f"  symbol: {result['symbol']}")
print(f"  count: {result['count']} نمونه")
print(f"  continuous: {result['continuous_count']} نمونه")
print(f"  alerts: {len(result['alerts'])} لحظه هشدار")

# بررسی timeline
tl = result["timeline"]
cont = [t for t in tl if t["sell_score"] is not None]
print(f"  timeline با امتیاز: {len(cont)} نمونه")
if cont:
    # نمونه با بالاترین sell score
    top = max(cont, key=lambda t: t["sell_score"] or 0)
    print(f"  اوج sell_score: زمان={top['time']}, score={top['sell_score']}, tier={top['sell_tier']}")
    top_buy = max(cont, key=lambda t: t["buy_score"] or 0)
    print(f"  اوج buy_score : زمان={top_buy['time']}, score={top_buy['buy_score']}, tier={top_buy['buy_tier']}")
    # طبقه‌بندی یکتا
    classes = set(t["classification"] for t in cont)
    print(f"  طبقه‌بندی‌ها: {classes}")

# نمایش چند هشدار
if result["alerts"]:
    print(f"  --- ۵ هشدار اول ---")
    for a in result["alerts"][:5]:
        print(f"    {a['time']} | {a['type']} | sell={a['sell_score']} buy={a['buy_score']} | {a['classification']} | قیمت={a['price']}")
else:
    print("  هشداری ثبت نشد (ممکن است آستانه‌ها بالاتر از امتیازها باشد)")

storage.close()

print()
print("=" * 60)
print("✓ بازپخش کار می‌کند")
print("=" * 60)
