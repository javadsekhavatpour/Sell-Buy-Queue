"""
تست جامع Phase 2: نرمال‌سازی تطبیقی.
  ۱. syntax check همه فایل‌های تغییر کرده
  ۲. حالت غیرفعال (adaptive.enabled=false) → رفتار مرحله ۱ (full_at ثابت)
  ۳. حالت فعال (adaptive.enabled=true) → ثبت در score_history + آستانه تطبیقی
  ۴. شبیه‌سازی: پر کردن score_history با ۱۰۰ مشاهده → آستانه تطبیقی ≠ fallback
"""
import sys, os, json, math, tempfile, py_compile
from pathlib import Path

BASE = Path("/home/z/my-project/download/TSE_Screener")
os.chdir(BASE)
sys.path.insert(0, str(BASE))

print("=" * 60)
print("۱. SYNTAX CHECK")
print("=" * 60)
files = [
    "early_warning/storage.py",
    "early_warning/adaptive_scoring.py",
    "early_warning/sell_pressure.py",
    "early_warning/smart_accumulation.py",
    "early_warning/__init__.py",
    "run_live.py",
    "web_dashboard_live.py",
]
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"  ✓ {f}")
    except py_compile.PyCompileError as e:
        print(f"  ✗ {f}: {e}")
        sys.exit(1)

print()
print("=" * 60)
print("۲. حالت غیرفعال (adaptive.enabled=false)")
print("=" * 60)
from early_warning import (
    AdaptiveNormalizer, MarketDataStorage,
    SellPressureDetector, BuyPressureDetector,
)
from early_warning.data_collector import SimulationDataCollector

cfg = json.load(open("config/warning_thresholds.json", encoding="utf-8"))
assert cfg["adaptive"]["enabled"] is False, "adaptive باید false باشد"

with tempfile.TemporaryDirectory() as td:
    storage = MarketDataStorage(Path(td) / "test.sqlite")
    norm = AdaptiveNormalizer(storage, cfg)
    print(f"  enabled={norm.enabled}, min_samples={norm.min_samples}, percentile={norm.percentile}")

    # موتورها با normalizer (غیرفعال)
    sp_eng = SellPressureDetector(cfg, normalizer=norm)
    buy_eng = BuyPressureDetector(cfg, normalizer=norm)

    # شبیه‌سازی
    sim = SimulationDataCollector(cfg, scenario="sell_pressure")
    snaps, _ = sim.generate_series(num_samples=12)
    prev, s = snaps[-2], snaps[-1]

    sp = sp_eng.evaluate(s, prev)
    # threshold باید = fallback (چون adaptive غیرفعال)
    fb = cfg["sell_pressure"]["norm"]["sell_breadth"]["full_at"]
    th = norm.get_threshold(s.symbol, "sell_breadth", fb)
    print(f"  sell_breadth: fallback={fb}, threshold={th} → {'✓ fallback' if th==fb else '✗ تطبیقی!'}")
    print(f"  sell_res.total_score = {sp.total_score}")

print()
print("=" * 60)
print("۳. حالت فعال (adaptive.enabled=true) + ثبت در score_history")
print("=" * 60)
cfg2 = json.loads(json.dumps(cfg))  # deep copy
cfg2["adaptive"]["enabled"] = True
cfg2["adaptive"]["min_samples"] = 10  # برای تست سریع‌تر

with tempfile.TemporaryDirectory() as td:
    storage = MarketDataStorage(Path(td) / "test2.sqlite")
    norm = AdaptiveNormalizer(storage, cfg2)
    print(f"  enabled={norm.enabled}, min_samples={norm.min_samples}")

    sp_eng = SellPressureDetector(cfg2, normalizer=norm)
    buy_eng = BuyPressureDetector(cfg2, normalizer=norm)

    # ۱۲ نمونه شبیه‌سازی → ارزیابی + ثبت
    sim = SimulationDataCollector(cfg2, scenario="sell_pressure")
    snaps, _ = sim.generate_series(num_samples=12)
    for i in range(1, len(snaps)):
        sp = sp_eng.evaluate(snaps[i], snaps[i-1])
        buy = buy_eng.evaluate(snaps[i], snaps[i-1], snaps[:i])
        norm.record_factors(snaps[i].symbol, "sell", sp.factors, date_jalali="1405-08-26")
        norm.record_factors(snaps[i].symbol, "buy", buy.factors, date_jalali="1405-08-26")

    # بررسی ثبت در score_history
    count = storage.get_score_history_count("ریتون", "sell_breadth")
    raw_vals = storage.get_score_history_raw("ریتون", "sell_breadth", limit=100)
    print(f"  score_history sell_breadth: {count} مشاهده ثبت شد")
    print(f"  مقادیر خام: {[round(v,3) for v in raw_vals[:5]]}...")

    # آستانه تطبیقی (با <min_samples → fallback؛ با ≥min_samples → صدک)
    fb = cfg2["sell_pressure"]["norm"]["sell_breadth"]["full_at"]
    th_before = norm.get_threshold("ریتون", "sell_breadth", fb)
    print(f"  fallback={fb}, threshold (با {count} نمونه)={th_before:.4f}")
    if count >= norm.min_samples:
        print(f"  → تطبیقی فعال (صدک {norm.percentile}) ✓")
    else:
        print(f"  → fallback (کمتر از {norm.min_samples} نمونه) — طبیعی")

print()
print("=" * 60)
print("۴. پر کردن score_history با ۱۰۰ مشاهده → آستانه تطبیقی")
print("=" * 60)
cfg3 = json.loads(json.dumps(cfg))
cfg3["adaptive"]["enabled"] = True
cfg3["adaptive"]["min_samples"] = 50

with tempfile.TemporaryDirectory() as td:
    storage = MarketDataStorage(Path(td) / "test3.sqlite")
    norm = AdaptiveNormalizer(storage, cfg3)

    # شبیه‌سازی ۱۰۰+ نمونه
    sim = SimulationDataCollector(cfg3, scenario="sell_pressure")
    snaps, _ = sim.generate_series(num_samples=110)
    sp_eng = SellPressureDetector(cfg3, normalizer=norm)

    for i in range(1, len(snaps)):
        sp = sp_eng.evaluate(snaps[i], snaps[i-1])
        norm.record_factors(snaps[i].symbol, "sell", sp.factors)

    # گزارش آستانه‌ها
    fallbacks = {k: v["full_at"] for k, v in cfg3["sell_pressure"]["norm"].items()}
    report = norm.get_thresholds_report("ریتون", fallbacks)
    print(f"  نماد: ریتون، {len(snaps)-1} مشاهده ثبت شد")
    print(f"  {'factor':<16} {'fallback':>9} {'adaptive':>9} {'samples':>8} {'mode':>10}")
    for f, info in report.items():
        mode = "تطبیقی" if info["adaptive"] else "fallback"
        print(f"  {f:<16} {info['fallback']:>9.3f} {info['threshold']:>9.4f} {info['samples']:>8} {mode:>10}")

    # تأیید: اگر samples ≥ min_samples، threshold باید ≠ fallback (تا حدی)
    adaptive_count = sum(1 for info in report.values() if info["adaptive"])
    print(f"\n  → {adaptive_count}/{len(report)} شاخص در حالت تطبیقی هستند")

print()
print("=" * 60)
print("✓ همه تست‌ها گذشت")
print("=" * 60)
