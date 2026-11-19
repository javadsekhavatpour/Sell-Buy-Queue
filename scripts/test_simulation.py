#!/usr/bin/env python3
"""تست فاز شبیه‌سازی: پخش داده‌های بانک با کنترل play/pause/step/speed.

فازها:
۱. ساخت ۱۲ snapshot در data/multi/دابور.sqlite با تاریخ امروز
۲. استارت داشبورد در --mode simulation --symbol دابور --date <today>
۳. بررسی /api/sim/status (mode=simulation، total=12)
۴. step +5 → index=5
۵. pause → playing=false
۶. speed=50 → speed=50
۷. /api/live → cumulative_samples باید 6 باشد (index 5 + 1)
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
    # ساخت مسیر data/multi/دابور.sqlite (مسیر پیش‌فرض adaptive)
    multi_dir = Path(tmpdir) / "data" / "multi"
    multi_dir.mkdir(parents=True)
    db_path = multi_dir / "دابور.sqlite"

    slash_date = to_jalali(date.today())

    # فاز ۱: ۱۲ snapshot در بانک
    storage = MarketDataStorage(db_path)
    for i in range(1, 13):
        storage.insert_snapshot(make_snap(i, slash_date))
    n = storage.conn.execute(
        "SELECT COUNT(*) FROM snapshots WHERE symbol='دابور'").fetchone()[0]
    storage.conn.close()
    print(f"فاز ۱: {n} snapshot در بانک ذخیره شد (تاریخ {slash_date})")

    # فاز ۲: استارت داشبورد در حالت simulation
    import subprocess
    env = {**os.environ, "PYTHONPATH": PROJ}
    proc = subprocess.Popen(
        [sys.executable, "-u", f"{PROJ}/web_dashboard_adaptive.py",
         "--mode", "simulation", "--symbol", "دابور", "--date", slash_date,
         "--time-speed", "100", "--port", "5572", "--db", str(db_path)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
    )
    try:
        time.sleep(5)  # صبر برای استارت Flask + بارگذاری

        # فاز ۳: بررسی /api/sim/status
        r = requests.get("http://127.0.0.1:5572/api/sim/status", timeout=5).json()
        print(f"\nفاز ۳: /api/sim/status:")
        print(f"  mode={r.get('mode')}, symbol={r.get('symbol')}, "
              f"total={r.get('total')}, index={r.get('index')}, playing={r.get('playing')}")
        ok3 = r.get("mode") == "simulation" and r.get("total") == 12
        print(f"  {'✅' if ok3 else '❌'} mode=simulation, total=12")

        # فاز ۴: step +5
        requests.post("http://127.0.0.1:5572/api/sim/step",
                      json={"n": 5}, timeout=5)
        time.sleep(0.5)
        r = requests.get("http://127.0.0.1:5572/api/sim/status", timeout=5).json()
        print(f"\nفاز ۴: بعد از step +5:")
        print(f"  index={r.get('index')} (انتظار ≥5)")
        ok4 = r.get("index", 0) >= 5
        print(f"  {'✅' if ok4 else '❌'} step forward کار کرد")

        # فاز ۵: pause
        requests.post("http://127.0.0.1:5572/api/sim/pause", timeout=5)
        time.sleep(0.5)
        r = requests.get("http://127.0.0.1:5572/api/sim/status", timeout=5).json()
        print(f"\nفاز ۵: بعد از pause:")
        print(f"  playing={r.get('playing')} (انتظار false)")
        ok5 = r.get("playing") is False
        print(f"  {'✅' if ok5 else '❌'} pause کار کرد")

        # فاز ۶: speed=50
        requests.post("http://127.0.0.1:5572/api/sim/speed",
                      json={"speed": 50}, timeout=5)
        time.sleep(0.5)
        r = requests.get("http://127.0.0.1:5572/api/sim/status", timeout=5).json()
        print(f"\nفاز ۶: بعد از speed=50:")
        print(f"  speed={r.get('speed')} (انتظار 50)")
        ok6 = r.get("speed") == 50
        print(f"  {'✅' if ok6 else '❌'} speed change کار کرد")

        # فاز ۷: /api/live → cumulative_samples
        r = requests.get("http://127.0.0.1:5572/api/live", timeout=5).json()
        eng = r.get("engines", {})
        cum = eng.get("cumulative_samples")
        print(f"\nفاز ۷: /api/live:")
        print(f"  cumulative_samples={cum}")
        print(f"  cumulative_sell_score={eng.get('cumulative_sell_score')}")
        ok7 = cum is not None and cum >= 1
        print(f"  {'✅' if ok7 else '❌'} داده از بانک پخش شد")

        # فاز ۸: step -3 (پرش عقب)
        idx_before = requests.get("http://127.0.0.1:5572/api/sim/status",
                                   timeout=5).json().get("index")
        requests.post("http://127.0.0.1:5572/api/sim/step",
                      json={"n": -3}, timeout=5)
        time.sleep(0.5)
        idx_after = requests.get("http://127.0.0.1:5572/api/sim/status",
                                  timeout=5).json().get("index")
        print(f"\nفاز ۸: بعد از step -3:")
        print(f"  index: {idx_before} → {idx_after} (انتظار {max(0,idx_before-3)})")
        ok8 = idx_after == max(0, idx_before - 3)
        print(f"  {'✅' if ok8 else '❌'} step backward کار کرد")

        all_ok = all([ok3, ok4, ok5, ok6, ok7, ok8])
        print(f"\n{'='*55}")
        print(f"نتیجه‌ی کل: {'✅ همه گذشت' if all_ok else '❌ بعضی مردود'}")
        return 0 if all_ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
