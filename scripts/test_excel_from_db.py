#!/usr/bin/env python3
"""تست fix اکسل خالی: اکسل باید از بانک پر شود نه از in-memory.

شبیه‌سازی: ۱۰ snapshot در data/multi/دابور.sqlite ذخیره شده (توسط داشبورد یا
session قبلی). سپس run_live.py با --max-samples 1 اجرا می‌شود (in-memory فقط
۱ نمونه). قبل از fix: اکسل خالی/یک‌نمونه‌ای. بعد از fix: اکسل ۱۰ نمونه از بانک.
"""
import sys, os, tempfile, shutil
from pathlib import Path
from datetime import date

PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)
os.chdir(PROJ)

from early_warning.price_range import to_jalali
from early_warning.storage import MarketDataStorage
from early_warning.data_collector import MarketSnapshot, BestLimitRow


def make_snap(idx, date_fmt, symbol="دابور"):
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
    tmpdir = tempfile.mkdtemp()
    multi_dir = Path(tmpdir) / "data" / "multi"
    multi_dir.mkdir(parents=True)
    db_path = multi_dir / "دابور.sqlite"
    out_xlsx = Path(tmpdir) / "report.xlsx"

    slash_date = to_jalali(date.today())

    # فاز ۱: ۱۰ snapshot در بانک (شبیه‌سازی جمع‌آوری توسط داشبورد)
    storage = MarketDataStorage(db_path)
    for i in range(1, 11):
        storage.insert_snapshot(make_snap(i, slash_date))
    n = storage.conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE symbol='دابور'").fetchone()[0]
    storage.conn.close()
    print(f"فاز ۱: {n} snapshot در بانک ذخیره شد (شبیه‌سازی جمع‌آوری)")

    # فاز ۲: run_live.py با --max-samples 1 (in-memory فقط ۱ نمونه)
    import subprocess
    proc = subprocess.run(
        [sys.executable, "-u", f"{PROJ}/run_live.py",
         "--symbol", "دابور", "--ins-code", "123",
         "--db", str(db_path), "--output", str(out_xlsx),
         "--max-samples", "1", "--interval", "1", "--analysis-interval", "1"],
        capture_output=True, text=True, timeout=30, env={**os.environ, "PYTHONPATH": PROJ},
    )
    print(f"\nفاز ۲: run_live.py exit={proc.returncode}")
    # چاپ خطوط مرتبط با اکسل
    for line in proc.stdout.splitlines():
        if "اکسل" in line or "بازخوانی" in line or "گزارش" in line or "نمونه" in line:
            print(f"  {line.strip()}")

    # فاز ۳: بررسی اکسل
    import openpyxl
    wb = openpyxl.load_workbook(out_xlsx)
    print(f"\nفاز ۳: شیت‌ها = {wb.sheetnames}")
    snap_sheet = wb["Snapshots"]
    # ردیف ۱ هدر است؛ ردیف‌های داده از ۲ شروع می‌شوند
    data_rows = snap_sheet.max_row - 1
    print(f"  شیت Snapshots: {data_rows} ردیف داده")

    ok = data_rows >= 10
    print(f"\n{'='*55}")
    print(f"انتظار: ≥ ۱۰ ردیف (از بانک)")
    print(f"یافت‌شده: {data_rows} ردیف")
    print(f"نتیجه: {'✅ گذشت' if ok else '❌ مردود'}")
    if not ok:
        print("  → اکسل هنوز از in-memory پر می‌شود، نه از بانک")
    shutil.rmtree(tmpdir, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
