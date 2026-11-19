#!/usr/bin/env python3
"""تست صفحه‌ی نمایه با dropdown تاریخ + فیلتر /db و /sim با تاریخ.

مراحل:
  ۱) ساخت بانک دابور با دو تاریخ متفاوت (هرکدام چند snapshot)
  ۲) استارت سرور web_dashboard_adaptive روی پورت 5574
  ۳) GET / → بررسی dropdown تاریخ
  ۴) GET /api/sim/dates?symbol=دابور → بررسی لیست تاریخ‌ها
  ۵) GET /db?symbol=دابور&date=<date1> → بررسی فیلتر تاریخ
  ۶) GET /db?symbol=دابور&date=<date2> → تاریخ دیگر
  ۷) GET /sim?symbol=دابور&date=<date1>
"""
import json
import os
import sys
import time
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import date

PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)

from early_warning.data_collector import MarketSnapshot, BestLimitRow
from early_warning.storage import MarketDataStorage

# ---------------------------------------------------------------------------
# ۱) ساخت بانک با دو تاریخ
# ---------------------------------------------------------------------------
db_path = Path(PROJ) / "data" / "multi" / "دابور.sqlite"
db_path.parent.mkdir(parents=True, exist_ok=True)
if db_path.exists():
    db_path.unlink()

DATE1 = "1405/08/27"
DATE2 = "1405/08/28"


def make_snap(idx, date_jalali, hour, symbol="دابور"):
    return MarketSnapshot(
        timestamp=f"2026-11-18T{hour:02d}:{idx:02d}:30",
        tehran_time=f"{hour:02d}:{idx:02d}:30",
        date_jalali=date_jalali, symbol=symbol,
        last_price=12000 + idx * 5, close_price=12000 + idx * 5,
        yesterday_price=12000, max_allowed_price=13000, min_allowed_price=11000,
        real_buy_value=1_000_000_000 * idx, real_sell_value=1_200_000_000 * idx,
        real_buy_count=10 * idx, real_sell_count=12 * idx,
        real_buy_volume=10000 * idx, real_sell_volume=12000 * idx,
        buy_rows=[BestLimitRow(price=11990, volume=5000, order_count=10)],
        sell_rows=[BestLimitRow(price=12010, volume=3000, order_count=8)],
        data_complete=True,
    )


st = MarketDataStorage(db_path)
# تاریخ اول: ۳ snapshot در ساعت‌های ۹، ۱۰، ۱۱
for i in range(1, 4):
    st.insert_snapshot(make_snap(i, DATE1, 9 + i - 1))
# تاریخ دوم: ۲ snapshot در ساعت‌های ۹، ۱۲
st.insert_snapshot(make_snap(1, DATE2, 9))
st.insert_snapshot(make_snap(2, DATE2, 12))
st.conn.close()
print(f"بانک ساخته شد: {db_path} — دو تاریخ: {DATE1}, {DATE2}")

# ---------------------------------------------------------------------------
# ۲) استارت سرور
# ---------------------------------------------------------------------------
env = os.environ.copy()
env["PYTHONPATH"] = PROJ
proc = subprocess.Popen(
    ["/home/z/.venv/bin/python3", "-u", f"{PROJ}/web_dashboard_adaptive.py",
     "--port", "5574"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
)
time.sleep(4)

results = {}


def fetch(path):
    url = f"http://127.0.0.1:5574{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


try:
    # ۳) GET / → dropdown تاریخ
    st_code, html = fetch("/")
    ok_index = (st_code == 200 and 'id="date"' in html
                and "loadDates" in html and "api/sim/dates" in html)
    print(f"\n۳) صفحه نمایه: {'✅' if ok_index else '❌'} (dropdown={'دارد' if 'id=\"date\"' in html else 'ندارد'})")
    results["index"] = ok_index

    # ۴) GET /api/sim/dates
    st_code, body = fetch("/api/sim/dates?symbol=" + urllib.parse.quote("دابور"))
    dates = []
    if st_code == 200:
        try:
            dates = json.loads(body)
        except Exception:
            pass
    ok_dates = (isinstance(dates, list) and len(dates) == 2
                and DATE1 in dates and DATE2 in dates)
    print(f"۴) /api/sim/dates: {'✅' if ok_dates else '❌'} (تاریخ‌ها={dates})")
    results["dates_api"] = ok_dates

    # ۵) GET /db?symbol=دابور&date=DATE2
    q = urllib.parse.urlencode({"symbol": "دابور", "date": DATE2})
    st_code, html = fetch(f"/db?{q}")
    print(f"۵) /db?date={DATE2}: status={st_code} {'✅' if st_code == 200 else '❌'}")
    results["db_date1"] = st_code == 200

    # ۶) GET /db?symbol=دابور&date=DATE1
    q = urllib.parse.urlencode({"symbol": "دابور", "date": DATE1})
    st_code, html = fetch(f"/db?{q}")
    print(f"۶) /db?date={DATE1}: status={st_code} {'✅' if st_code == 200 else '❌'}")
    results["db_date2"] = st_code == 200

    # ۷) GET /sim?symbol=دابور&date=DATE2
    q = urllib.parse.urlencode({"symbol": "دابور", "date": DATE2})
    st_code, html = fetch(f"/sim?{q}")
    print(f"۷) /sim?date={DATE2}: status={st_code} {'✅' if st_code == 200 else '❌'}")
    results["sim_date"] = st_code == 200

    # ۸) بدون تاریخ → آخرین کلی
    q = urllib.parse.urlencode({"symbol": "دابور"})
    st_code, html = fetch(f"/db?{q}")
    print(f"۸) /db (بدون تاریخ): status={st_code} {'✅' if st_code == 200 else '❌'}")
    results["db_nodate"] = st_code == 200

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

# ---------------------------------------------------------------------------
# خلاصه
# ---------------------------------------------------------------------------
print("\n" + "=" * 50)
all_ok = all(results.values())
print("خلاصه:")
for k, v in results.items():
    print(f"  {k}: {'✅' if v else '❌'}")
print(f"\nنتیجه: {'✅ همه گذشت' if all_ok else '❌ بعضی مردود'}")
sys.exit(0 if all_ok else 1)
