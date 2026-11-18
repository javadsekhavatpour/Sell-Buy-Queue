#!/usr/bin/env python3
"""تست امتیاز تجمعی از DB — سناریوی ری‌استارت داشبورد.

مراحل:
  ۱. LiveMonitor در حالت demo با storage اجرا می‌شود، چند نمونه جمع می‌کند (نوشته به DB).
  ۲. متوقف می‌شود (شبیه‌سازی ری‌استارت).
  ۳. LiveMonitor جدید با همان DB اجرا می‌شود، چند نمونه دیگر جمع می‌کند.
  ۴. بررسی: cumulative_samples باید برابر کل نمونه‌های DB باشد (نه فقط in-memory).
"""
import sys
import os
import time
import tempfile
from pathlib import Path

# مسیر پروژه
PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)

from web_dashboard_live import LiveMonitor, load_cfg
from early_warning.storage import MarketDataStorage


def run_phase(db_path, num_seconds, phase_label):
    """اجرای LiveMonitor برای num_seconds ثانیه و بازگشت payload."""
    cfg = load_cfg()
    storage = MarketDataStorage(db_path)
    m = LiveMonitor(
        cfg, mode="demo", scenario="sell_pressure", samples=15,
        interval=1, storage=storage,
    )
    m.start()
    time.sleep(num_seconds)
    payload = m.payload()
    m.stop()
    time.sleep(0.5)  # انتظار برای پایان thread پس‌زمینه
    storage.close()
    eng = payload.get("engines", {})
    print(f"  [{phase_label}] in-memory samples={payload.get('samples')} | "
          f"cumulative_samples={eng.get('cumulative_samples')} | "
          f"cumulative_sell={eng.get('cumulative_sell_score')} | "
          f"current_sell={(eng.get('sell') or {}).get('total_score')}")
    return eng


def main():
    # DB موقت
    tmpdir = tempfile.mkdtemp(prefix="cumtest_")
    db_path = Path(tmpdir) / "test.sqlite"
    print(f"DB: {db_path}")
    print()

    # فاز ۱: اجرای اول — ۵ نمونه
    print("=== فاز ۱: اجرای اول (۵ ثانیه → ~۵ نمونه) ===")
    eng1 = run_phase(db_path, 5, "فاز۱")

    # فاز ۲: ری‌استارت — ۳ نمونه جدید
    print()
    print("=== فاز ۲: ری‌استارت (۳ ثانیه → ~۳ نمونه جدید) ===")
    eng2 = run_phase(db_path, 3, "فاز۲")

    # بررسی نتیجه
    print()
    print("=== بررسی ===")

    # تعداد نمونه‌های DB
    storage = MarketDataStorage(db_path)
    db_count = storage.count_snapshots()
    today_count = storage.count_snapshots()  # کل (demo فقط امروز را تولید می‌کند)
    storage.close()
    print(f"  کل snapshot‌های در DB: {db_count}")

    cum_samples_2 = eng2.get("cumulative_samples")
    cum_sell_2 = eng2.get("cumulative_sell_score")
    cum_sell_1 = eng1.get("cumulative_sell_score")

    print(f"  فاز۱ cumulative_samples: {eng1.get('cumulative_samples')}")
    print(f"  فاز۲ cumulative_samples: {cum_samples_2}")
    print()

    # تست کلیدی: cumulative_samples فاز۲ باید ≥ فاز۱ باشد (DB تجمعی است)
    # و باید برابر کل DB باشد (نه فقط ۳ نمونه‌ی in-memory فاز۲)
    ok_restart = cum_samples_2 >= eng1.get("cumulative_samples", 0)
    ok_db_match = cum_samples_2 == db_count
    ok_growing = cum_sell_2 >= cum_sell_1  # امتیاز تجمعی باید رشد کند

    print(f"  ری‌استارت درست (cum_samples فاز۲ ≥ فاز۱): {'✓' if ok_restart else '✗'}")
    print(f"  cumulative_samples == تعداد DB: {'✓' if ok_db_match else '✗'} "
          f"({cum_samples_2} vs {db_count})")
    print(f"  امتیاز تجمعی رشد کرد (فاز۲ ≥ فاز۱): {'✓' if ok_growing else '✗'} "
          f"({cum_sell_2} vs {cum_sell_1})")

    if ok_restart and ok_db_match and ok_growing:
        print()
        print("  ✅ همه تست‌ها گذشت — امتیاز تجمعی از DB محاسبه می‌شود.")
        return 0
    else:
        print()
        print("  ❌ تست‌ها نرفت — مشکل وجود دارد.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
