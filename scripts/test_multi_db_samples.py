#!/usr/bin/env python3
"""تست fix مشکل تعداد نمونه — سناریوی run_live.py.

شبیه‌سازی: run_live.py (از طریق run_multi) snapshot‌ها را با فرمت date_jalali
با اسلش (مثل '1405/08/27') در data/multi/{symbol}.sqlite ذخیره می‌کند.
قبلاً داشبورد از data/early_warning_live.sqlite می‌خواند و با فرمت خط تیره
فیلتر می‌کرد → نمونه‌ها پیدا نمی‌شدند (تعداد = ۰ یا فقط نمونه‌های استارت).

بعد از fix:
  ۱. داشبورد از data/multi/{symbol}.sqlite می‌خواند (همان DB	run_live.py)
  ۲. کوئری هر دو فرمت (خط تیره + اسلش) را پوشش می‌دهد
"""
import sys, os, sqlite3, tempfile, shutil
from pathlib import Path
from datetime import date

PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)

from early_warning.price_range import to_jalali
from early_warning.storage import MarketDataStorage
from early_warning.data_collector import MarketSnapshot, BestLimitRow
from web_dashboard_live import today_jalali_str, LiveMonitor, load_cfg


def make_snap(idx, date_fmt, symbol="دابور"):
    """ساخت snapshot با فرمت date_jalali مشخص."""
    ts = f"2026-11-18T09:{idx:02d}:30"
    tt = f"09:{idx:02d}:30"
    return MarketSnapshot(
        timestamp=ts, tehran_time=tt, date_jalali=date_fmt,
        symbol=symbol, last_price=12000 + idx * 5, close_price=12000 + idx * 5,
        yesterday_price=12000, max_allowed_price=13000, min_allowed_price=11000,
        real_buy_value=1_000_000_000 * idx, real_sell_value=1_200_000_000 * idx,
        real_buy_count=10 * idx, real_sell_count=12 * idx,
        real_buy_volume=10000 * idx, real_sell_volume=12000 * idx,
        buy_rows=[BestLimitRow(price=11990, volume=5000, order_count=10)],
        sell_rows=[BestLimitRow(price=12010, volume=3000, order_count=8)],
        data_complete=True,
    )


def main():
    # --- فاز ۱: شبیه‌سازی run_live.py ---
    # run_live.py snapshot‌ها را با فرمت to_jalali (اسلش) ذخیره می‌کند
    tmpdir = tempfile.mkdtemp()
    db_path = Path(tmpdir) / "multi" / "دابور.sqlite"
    db_path.parent.mkdir(parents=True)

    slash_date = to_jalali(date.today())  # "1405/08/27"
    dash_date = today_jalali_str()        # "1405-08-27"
    print(f"فرمت to_jalali (run_live.py): {slash_date!r}")
    print(f"فرمت today_jalali_str (داشبورد): {dash_date!r}")
    print(f"برابر؟ {slash_date == dash_date}")
    print()

    # run_live.py: ۵ snapshot با فرمت اسلش ذخیره می‌کند
    storage = MarketDataStorage(db_path)
    for i in range(1, 6):
        snap = make_snap(i, slash_date)
        storage.insert_snapshot(snap)
    n = storage.conn.execute("SELECT COUNT(*) FROM snapshots WHERE symbol='دابور'").fetchone()[0]
    print(f"فاز ۱ (run_live.py): {n} snapshot با فرمت اسلش در {db_path.name} ذخیره شد")
    storage.conn.close()

    # --- فاز ۲: شبیه‌سازی داشبورد که AFTER run_live.py استارت می‌شود ---
    # داشبورد همان DB را باز می‌کند (با default --db=data/multi/{symbol}.sqlite)
    # و _cumulative_scores را اجرا می‌کند
    cfg = load_cfg()
    monitor = LiveMonitor(cfg, mode="live", symbol="دابور",
                          ins_code="12345", interval=30, scenario="sell_pressure",
                          samples=10, normalizer=None, storage=MarketDataStorage(db_path))

    cum_s, cum_b, count = monitor._cumulative_scores()
    print(f"\nفاز ۲ (داشبورد بعد از استارت):")
    print(f"  cumulative_samples = {count}")
    print(f"  cum_sell = {cum_s:.1f}, cum_buy = {cum_b:.1f}")

    # --- تست کلیدی ---
    print(f"\n{'='*50}")
    expected = 5  # همه snapshot‌های run_live.py از ابتدای روز
    ok = count == expected
    print(f"تعداد نمونه‌های انتظاری (از ابتدای روز): {expected}")
    print(f"تعداد نمونه‌های یافت‌شده: {count}")
    print(f"نتیجه: {'✅ گذشت' if ok else '❌ مردود'}")
    if not ok:
        print("  → نمونه‌های run_live.py (فرمت اسلش) پیدا نشدند!")
        print("  → مشکل: فرمت تاریخ یا مسیر DB")

    # --- فاز ۳: داشبورد ری‌استارت می‌شود، snapshotهای خودش (فرمت خط تیره) اضافه می‌شود ---
    print(f"\nفاز ۳ (داشبورد ری‌استارت + snapshotهای خودش با خط تیره):")
    monitor2 = LiveMonitor(cfg, mode="live", symbol="دابور",
                           ins_code="12345", interval=30, scenario="sell_pressure",
                           samples=10, normalizer=None, storage=MarketDataStorage(db_path))
    # شبیه‌سازی: داشبورد ۲ snapshot جدید با فرمت خط تیره اضافه می‌کند
    for i in range(6, 8):
        snap = make_snap(i, dash_date)
        monitor2.storage.insert_snapshot(snap)
    cum_s2, cum_b2, count2 = monitor2._cumulative_scores()
    print(f"  cumulative_samples = {count2} (انتظار: ۷ = ۵ اسلش + ۲ خط تیره)")
    ok2 = count2 == 7
    print(f"  نتیجه: {'✅ گذشت' if ok2 else '❌ مردود'}")

    shutil.rmtree(tmpdir)
    print(f"\n{'='*50}")
    if ok and ok2:
        print("✅ همه تست‌ها گذشت — نمونه‌ها از ابتدای روز (هر دو فرمت) خوانده می‌شوند.")
        return 0
    else:
        print("❌ یک یا چند تست مردود.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
