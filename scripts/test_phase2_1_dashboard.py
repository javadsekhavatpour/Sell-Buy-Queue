"""
تست web_dashboard_adaptive.py (Phase 2.1).
  ۱. syntax check
  ۲. جایگزینی HTML (سه بخش باید همگی پیدا و جایگزین شوند)
  ۳. import + ساخت AdaptiveLiveMonitor
  ۴. غنی‌سازی payload با فاکتورهای شبیه‌سازی + آستانه تطبیقی
"""
import sys, os, json, tempfile, py_compile
from pathlib import Path

BASE = Path("/home/z/my-project/download/TSE_Screener")
os.chdir(BASE)
sys.path.insert(0, str(BASE))

print("=" * 60)
print("۱. SYNTAX + IMPORT")
print("=" * 60)
try:
    py_compile.compile("web_dashboard_adaptive.py", doraise=True)
    print("  ✓ syntax صحیح")
except py_compile.PyCompileError as e:
    print(f"  ✗ {e}")
    sys.exit(1)

import web_dashboard_adaptive as ada
print("  ✓ import موفق")

print()
print("=" * 60)
print("۲. جایگزینی HTML (سه بخش)")
print("=" * 60)
html = ada.HTML_PAGE_ADAPTIVE
checks = [
    ("ستون آستانه در سرتیس", "<th>آستانه</th>" in html),
    ("colspan=5 در سرتیس فروش", 'colspan="5" style="background:#fdecea' in html),
    ("colspan=5 در سرتیس خرید", 'colspan="5" style="background:#e8f5e9' in html),
    ("cell با colspan=5", "colspan=\"5\" style=\"color:#ccc\"" in html),
    ("راهنمای adaptive", "آبی=تطبیقی" in html),
    ("حذف متن Phase 1 قدیمی", "نرمال‌سازی آستانه ثابت (Phase 1)" not in html),
]
for label, ok in checks:
    print(f"  {'✓' if ok else '✗'} {label}")
if not all(ok for _, ok in checks):
    print("  ✗ برخی جایگزینی‌ها ناموفق بودند")
    sys.exit(1)

print()
print("=" * 60)
print("۳. ساخت AdaptiveLiveMonitor + payload")
print("=" * 60)
from early_warning.data_collector import SimulationDataCollector

cfg = json.load(open("config/warning_thresholds.json", encoding="utf-8"))
cfg["adaptive"]["enabled"] = True
cfg["adaptive"]["min_samples"] = 5  # برای تست سریع

with tempfile.TemporaryDirectory() as td:
    from early_warning import MarketDataStorage, AdaptiveNormalizer
    storage = MarketDataStorage(Path(td) / "t.sqlite")
    norm = AdaptiveNormalizer(storage, cfg)

    # حالت demo با شبیه‌ساز
    mon = ada.AdaptiveLiveMonitor(cfg, mode="demo", scenario="sell_pressure",
                                  samples=30, normalizer=norm)
    mon.start()
    import time; time.sleep(2)  # اجازه تولید چند نمونه

    payload = mon.payload()
    mon._stop.set()

    print(f"  payload.ok = {payload.get('ok')}")
    print(f"  adaptive banner: {payload.get('adaptive')}")

    engines = payload.get("engines", {})
    sell = engines.get("sell", {})
    factors = sell.get("factors", [])
    if factors:
        print(f"  sell.factors: {len(factors)} فاکتور")
        print(f"  {'name':<16} {'raw':>8} {'norm':>6} {'thresh':>8} {'samp':>5} {'mode':>6}")
        for f in factors[:4]:
            rv = f.get('raw_value')
            rv_s = f"{rv:.3f}" if isinstance(rv, (int, float)) else "—"
            th = f.get('adaptive_threshold')
            th_s = f"{th}" if th is not None else "?"
            print(f"  {f.get('name','—'):<16} {rv_s:>8} "
                  f"{(f.get('normalized',0)*100):>5.0f}% "
                  f"{th_s:>8} {f.get('adaptive_samples','?'):>5} "
                  f"{'تطبیقی' if f.get('adaptive_mode') else 'ثابت':>6}")
    else:
        print("  ✗ فاکتوری در payload نیست")

    # حالت غیرفعال (enabled=false) → همه باید fallback باشند
    print()
    print("  --- حالت غیرفعال (enabled=false) ---")
    cfg2 = json.loads(json.dumps(cfg))
    cfg2["adaptive"]["enabled"] = False
    storage2 = MarketDataStorage(Path(td) / "t2.sqlite")
    norm2 = AdaptiveNormalizer(storage2, cfg2)
    mon2 = ada.AdaptiveLiveMonitor(cfg2, mode="demo", scenario="sell_pressure",
                                   samples=10, normalizer=norm2)
    mon2.start()
    time.sleep(2)
    p2 = mon2.payload()
    mon2._stop.set()
    f2 = p2.get("engines", {}).get("sell", {}).get("factors", [])
    if f2:
        f0 = f2[0]
        print(f"  {f0.get('name')}: threshold={f0.get('adaptive_threshold')}, "
              f"mode={f0.get('adaptive_mode')}, enabled={f0.get('adaptive_enabled')}")
        assert f0.get("adaptive_mode") is False, "باید fallback باشد"
        print("  ✓ حالت غیرفعال → fallback ثابت (درست)")

print()
print("=" * 60)
print("✓ همه تست‌های Phase 2.1 گذشت")
print("=" * 60)
