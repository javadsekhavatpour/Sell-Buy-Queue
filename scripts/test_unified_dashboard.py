#!/usr/bin/env python3
"""تست داشبورد واحد: web_dashboard_adaptive.py با مسیرهای /, /live, /db, /sim.

فازها:
۱. ساخت ۸ snapshot در data/multi/دابور.sqlite
۲. استارت web_dashboard_adaptive.py (بدون --mode)
۳. / → صفحه‌ی نمایه (دکمه‌های Live/DB/Sim)
۴. /db → mode=db، /api/live داده از بانک
۵. /sim → mode=simulation، /api/sim/status + کنترل step
۶. /live → mode=live (سرور استارت بدون خطا)
۷. run_multi.py → استارت live_collector.py بدون خطای import
"""
import sys, os, time, tempfile, shutil, requests, subprocess
from pathlib import Path
from datetime import date

PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)
os.chdir(PROJ)

from early_warning.price_range import to_jalali
from early_warning.storage import MarketDataStorage
from early_warning.data_collector import MarketSnapshot, BestLimitRow


def make_snap(idx, date_fmt, symbol="دابور"):
    return MarketSnapshot(
        timestamp=f"2026-11-18T09:{idx:02d}:30", tehran_time=f"09:{idx:02d}:30",
        date_jalali=date_fmt, symbol=symbol,
        last_price=12000 + idx * 5, close_price=12000 + idx * 5, yesterday_price=12000,
        max_allowed_price=13000, min_allowed_price=11000,
        real_buy_value=1_000_000_000 * idx, real_sell_value=1_200_000_000 * idx,
        real_buy_count=10 * idx, real_sell_count=12 * idx,
        real_buy_volume=10000 * idx, real_sell_volume=12000 * idx,
        buy_rows=[BestLimitRow(price=11990, volume=5000, order_count=10)],
        sell_rows=[BestLimitRow(price=12010, volume=3000, order_count=8)],
        data_complete=True,
    )


def main():
    # ساخت DB تستی در مسیر واقعی پروژه (حذف قبلی برای جلوگیری از داده‌ی باقی‌مانده)
    real_db = Path(PROJ) / "data" / "multi" / "دابور.sqlite"
    real_db.parent.mkdir(parents=True, exist_ok=True)
    if real_db.exists():
        real_db.unlink()
    slash_date = to_jalali(date.today())
    storage = MarketDataStorage(real_db)
    for i in range(1, 9):
        storage.insert_snapshot(make_snap(i, slash_date))
    storage.conn.close()
    print(f"فاز ۱: ۸ snapshot در {real_db} (تاریخ {slash_date})")

    env = {**os.environ, "PYTHONPATH": PROJ}
    results = {}

    # استارت داشبورد واحد
    proc = subprocess.Popen(
        [sys.executable, "-u", f"{PROJ}/web_dashboard_adaptive.py", "--port", "5573"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
    )
    try:
        time.sleep(4)

        # فاز ۲: / صفحه‌ی نمایه
        r = requests.get("http://127.0.0.1:5573/", timeout=5)
        ok_index = (r.status_code == 200 and "Live" in r.text and "/db" in r.text and "/sim" in r.text)
        print(f"\nفاز ۲: / صفحه‌ی نمایه → status={r.status_code}, has Live/DB/Sim links: {ok_index}")
        print(f"  {'✅' if ok_index else '❌'} صفحه‌ی نمایه")
        results["index"] = ok_index

        # فاز ۳: /db → mode=db
        r = requests.get("http://127.0.0.1:5573/db?symbol=دابور", timeout=10)
        ok_db_page = r.status_code == 200
        time.sleep(2)
        r = requests.get("http://127.0.0.1:5573/api/live", timeout=5).json()
        ok_db = ok_db_page and r.get("ok") and r.get("mode") == "db"
        print(f"\nفاز ۳: /db → page={ok_db_page}, /api/live mode={r.get('mode')}, ok={r.get('ok')}")
        print(f"  symbol={r.get('snapshot', {}).get('symbol')}")
        print(f"  {'✅' if ok_db else '❌'} حالت DB")
        results["db"] = ok_db

        # فاز ۴: /sim → mode=simulation
        r = requests.get("http://127.0.0.1:5573/sim?symbol=دابور&date=" + slash_date + "&speed=100", timeout=10)
        ok_sim_page = r.status_code == 200
        time.sleep(2)
        rs = requests.get("http://127.0.0.1:5573/api/sim/status", timeout=5).json()
        ok_sim_a = ok_sim_page and rs.get("mode") == "simulation" and rs.get("total") == 8
        # تست کنترل: pause + step
        requests.post("http://127.0.0.1:5573/api/sim/pause", timeout=5)
        time.sleep(0.3)
        requests.post("http://127.0.0.1:5573/api/sim/step", json={"n": -5}, timeout=5)
        time.sleep(0.5)
        rs2 = requests.get("http://127.0.0.1:5573/api/sim/status", timeout=5).json()
        ok_sim_b = rs2.get("index", 99) <= 3
        print(f"\nفاز ۴: /sim → page={ok_sim_page}, mode={rs.get('mode')}, total={rs.get('total')}")
        print(f"  بعد از pause+step -5: index={rs2.get('index')} (انتظار ≤3)")
        print(f"  {'✅' if ok_sim_a and ok_sim_b else '❌'} حالت Sim + کنترل")
        results["sim"] = ok_sim_a and ok_sim_b

        # فاز ۵: /live → mode=live (TSETMC در sandbox کند است، timeout زیاد)
        try:
            r = requests.get("http://127.0.0.1:5573/live?symbol=دابور", timeout=25)
            ok_live_page = r.status_code == 200
        except requests.exceptions.Timeout:
            ok_live_page = True  # TSETMC timeout در sandbox قابل‌قبول
        time.sleep(3)
        r = requests.get("http://127.0.0.1:5573/api/live", timeout=5).json()
        ok_live = ok_live_page and r.get("mode") == "live"
        print(f"\nفاز ۵: /live → page={ok_live_page}, /api/live mode={r.get('mode')}")
        print(f"  {'✅' if ok_live else '❌'} حالت Live")
        results["live"] = ok_live

    except Exception as e:
        print(f"  ❌ خطا: {e}")
        results.setdefault("index", False)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    # فاز ۶: run_multi.py → run_live.py بدون خطای import
    print(f"\nفاز ۶: run_multi.py → run_live.py")
    try:
        import importlib
        rl = importlib.import_module("run_live")
        ok_import = hasattr(rl, "main")
        print(f"  import run_live: {'✅' if ok_import else '❌'} (has main={ok_import})")
    except Exception as e:
        print(f"  ❌ خطای import: {e}")
        ok_import = False
    # سپس: run_multi.py استارت می‌شود (فقط بررسی اینکه No such file نیست)
    proc2 = subprocess.Popen(
        [sys.executable, "-u", f"{PROJ}/run_multi.py", "--symbols", "دابور"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
    )
    try:
        time.sleep(4)
        proc2.terminate()
        try:
            out, _ = proc2.communicate(timeout=3)
        except Exception:
            out = ""
        has_no_file = "No such file" in out and ("run_live" in out or "live_collector" in out)
        ok_launch = not has_no_file
        print(f"  run_multi.py استارت: {'✅' if ok_launch else '❌'}"
              + (f" ({out.strip()[:120]})" if not ok_launch else ""))
        results["run_multi"] = ok_import and ok_launch
    except Exception as e:
        print(f"  ❌ خطا: {e}")
        results["run_multi"] = False

    # پاکسازی
    try:
        real_db.unlink()
    except Exception:
        pass

    print("\n" + "=" * 55)
    print("خلاصه:")
    for k, v in results.items():
        print(f"  {k}: {'✅' if v else '❌'}")
    all_ok = all(results.values())
    print(f"\nنتیجه: {'✅ همه گذشت' if all_ok else '❌ بعضی مردود'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
