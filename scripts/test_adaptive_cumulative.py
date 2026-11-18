#!/usr/bin/env python3
"""تست fix مشکل تعداد نمونه در web_dashboard_adaptive.

شبیه‌سازی: run_live.py (از run_multi) snapshot‌ها را در data/multi/{symbol}.sqlite
ذخیره کرده. سپس web_dashboard_adaptive.py استارت می‌شود. قبل از fix:
  - self.storage = None (پارامتر storage پاس داده نمی‌شد)
  - _cumulative_scores به history درون‌حافظه‌ای fallback می‌کرد
  - cumulative_samples = 0 (یا فقط نمونه‌های استارت داشبورد)

بعد از fix:
  - storage=live_storage به AdaptiveLiveMonitor پاس داده می‌شود
  - _cumulative_scores از بانک می‌خواند
  - cumulative_samples = تعداد واقعی نمونه‌های امروز از بانک
"""
import sys, os, time, tempfile, shutil, requests
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
    # شبیه‌سازی DB data/multi/دابور.sqlite (مسیر پیش‌فرض adaptive)
    multi_dir = Path(tmpdir) / "data" / "multi"
    multi_dir.mkdir(parents=True)
    db_path = multi_dir / "دابور.sqlite"

    slash_date = to_jalali(date.today())  # فرمت run_live.py

    # run_live.py: ۶ snapshot با فرمت اسلش ذخیره می‌کند
    storage = MarketDataStorage(db_path)
    for i in range(1, 7):
        snap = make_snap(i, slash_date)
        storage.insert_snapshot(snap)
    n = storage.conn.execute("SELECT COUNT(*) FROM snapshots WHERE symbol='دابور'").fetchone()[0]
    storage.conn.close()
    print(f"فاز ۱: {n} snapshot با فرمت اسلش در {db_path.name} ذخیره شد (شبیه‌سازی run_live.py)")

    # استارت web_dashboard_adaptive.py در حالت demo (بدون نیاز به TSETMC)
    # با مسیر DB=tmpdir/data/multi/دابور.sqlite
    import subprocess
    env = os.environ.copy()
    env["PYTHONPATH"] = PROJ
    proc = subprocess.Popen(
        [sys.executable, "-u", f"{PROJ}/web_dashboard_adaptive.py",
         "--mode", "demo", "--scenario", "sell_pressure",
         "--symbol", "دابور", "--db", str(db_path),
         "--port", "5571", "--samples", "3", "--interval", "1"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
    )
    try:
        # صبر برای استارت Flask
        time.sleep(6)
        # درخواست /api/live
        r = requests.get("http://127.0.0.1:5571/api/live", timeout=5)
        data = r.json()
        eng = data.get("engines", {})
        cum_samples = eng.get("cumulative_samples")
        cum_sell = eng.get("cumulative_sell_score")
        print(f"\nفاز ۲: /api/live پاس داد:")
        print(f"  cumulative_samples = {cum_samples}")
        print(f"  cumulative_sell_score = {cum_sell}")

        # انتظار: حداقل ۶ نمونه از بانک (run_live.py) — حتی اگر داشبورد تازه استارت شده
        # (ممکن است samples demo هم اضافه شود، ولی حداقل ۶ باید باشد)
        ok = cum_samples is not None and cum_samples >= 6
        print(f"\n{'='*55}")
        print(f"تعداد نمونه‌های انتظاری (از بانک): ≥ ۶")
        print(f"تعداد نمونه‌های یافت‌شده: {cum_samples}")
        print(f"نتیجه: {'✅ گذشت' if ok else '❌ مردود'}")
        if not ok:
            print("  → self.storage احتمالاً None است (storage پاس داده نشده)")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
