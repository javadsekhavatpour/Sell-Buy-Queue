#!/usr/bin/env python3
"""تست تولید ریپورت Excel از شبیه‌سازی.

مراحل:
  ۱) ساخت بانک با snapshotهای یک نماد + تاریخ (مقادیر تجمعی متغیر + معاملات)
  ۲) استارت داشبورد → /sim?symbol=دابور&date=1405/08/28
  ۳) GET /sim/report → دانلود فایل اکسل
  ۴) باز کردن فایل با openpyxl و بررسی:
     - شیت‌های موجود (Dashboard, SellPressure, Snapshots, Metadata, ...)
     - فیلد «نوع گزارش» = «شبیه‌سازی (Sim)» در Metadata
     - نام فایل شامل sim_report، نماد و تاریخ
     - داده‌ها پر شده‌اند (سطر غیرخالی)
"""
import json
import os
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path

import openpyxl

PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)

from early_warning.data_collector import MarketSnapshot, BestLimitRow, Trade
from early_warning.storage import MarketDataStorage

db_path = Path(PROJ) / "data" / "multi" / "دابور.sqlite"
db_path.parent.mkdir(parents=True, exist_ok=True)
if db_path.exists():
    db_path.unlink()

DATE = "1405/08/28"


def make_snap(idx, rbc, rsc, rbv, rsv, hour, minute):
    return MarketSnapshot(
        timestamp=f"2026-11-19T{hour:02d}:{minute:02d}:00",
        tehran_time=f"{hour:02d}:{minute:02d}:00",
        date_jalali=DATE, symbol="دابور",
        last_price=12000 + idx * 15, close_price=12000 + idx * 15,
        yesterday_price=12000, max_allowed_price=13000, min_allowed_price=11000,
        open_price=12000, daily_high=12100 + idx * 15, daily_low=11950,
        total_volume=50000 + idx * 1000, total_value=600_000_000 + idx * 15_000_000,
        total_trade_count=200 + idx * 10, base_volume=100000,
        real_buy_value=rbv, real_sell_value=rsv,
        real_buy_count=rbc, real_sell_count=rsc,
        real_buy_volume=rbv // 1000, real_sell_volume=rsv // 1000,
        buy_rows=[BestLimitRow(price=11990, volume=5000 + idx * 100, order_count=10)],
        sell_rows=[BestLimitRow(price=12010, volume=3000 + idx * 50, order_count=8)],
        data_complete=True, data_status="ok", market_phase="A",
        ins_code="123456", symbol_status="A",
    )


# ساخت بانک با ۶ snapshot (مقادیر تجمعی متغیر) + معاملات
st = MarketDataStorage(db_path)
for i in range(6):
    st.insert_snapshot(make_snap(i, rbc=100 + i * 50, rsc=80 + i * 40,
                                  rbv=500_000_000 + i * 200_000_000,
                                  rsv=400_000_000 + i * 150_000_000,
                                  hour=9, minute=i * 5))
    # معاملات برای هر snapshot
    trades_batch = []
    for j in range(3):
        trades_batch.append(Trade(
            trade_time=f"{9:02d}:{i*5:02d}:{j*20:02d}",
            trade_price=12000 + i * 15,
            trade_volume=500 + j * 200,
            trade_id=f"t{i}_{j}", aggressor_side="buy" if j % 2 == 0 else "sell"))
    st.insert_trades(trades_batch, "دابور")
st.conn.close()
print(f"بانک: ۶ snapshot + ۱۸ معامله برای «دابور» در تاریخ {DATE}")

# استارت داشبورد
env = {**os.environ, "PYTHONPATH": PROJ}
import subprocess
proc = subprocess.Popen(
    ["/home/z/.venv/bin/python3", "-u", f"{PROJ}/web_dashboard_adaptive.py",
     "--port", "5592"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
)
time.sleep(4)


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.read(), r.status


try:
    # ۱) استارت شبیه‌سازی
    q = urllib.parse.urlencode({"symbol": "دابور", "date": DATE, "speed": "10"})
    with urllib.request.urlopen(f"http://127.0.0.1:5592/sim?{q}", timeout=10) as r:
        print(f"GET /sim: {r.status}")
    time.sleep(3)  # pre-compute

    # ۲) بررسی وضعیت sim
    with urllib.request.urlopen("http://127.0.0.1:5592/api/sim/status", timeout=5) as r:
        status = json.loads(r.read())
    print(f"sim status: mode={status.get('mode')}, total={status.get('total_samples')}")

    # ۳) دانلود ریپورت
    print("\nدرخواست /sim/report ...")
    resp, code = get("http://127.0.0.1:5592/sim/report")
    print(f"HTTP {code}, حجم: {len(resp)} bytes")

    if code != 200:
        print(f"❌ خطا: {resp.decode()[:200]}")
        sys.exit(1)

    # ذخیره فایل
    report_path = Path(PROJ) / "reports" / "test_sim_report.xlsx"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(resp)
    print(f"فایل ذخیره شد: {report_path}")

    # ۴) بررسی فایل اکسل
    print(f"\n{'='*55}")
    print("بررسی فایل اکسل:")
    wb = openpyxl.load_workbook(report_path)
    print(f"  شیت‌ها: {wb.sheetnames}")

    # بررسی Metadata — فیلد «نوع گزارش»
    ws_meta = wb["Metadata"]
    source_found = False
    for row in ws_meta.iter_rows(min_row=1, max_row=40, values_only=False):
        for cell in row:
            if cell.value and "نوع گزارش" in str(cell.value):
                val_cell = ws_meta.cell(row=cell.row, column=cell.column + 1)
                print(f"  نوع گزارش (Source): {val_cell.value}")
                source_found = ("شبیه‌سازی" in str(val_cell.value) or "Sim" in str(val_cell.value))
                break
        if source_found:
            break

    # بررسی نماد در Metadata
    symbol_found = False
    for row in ws_meta.iter_rows(min_row=1, max_row=40, values_only=True):
        if row and len(row) >= 2 and str(row[0]) == "نماد":
            print(f"  نماد: {row[1]}")
            symbol_found = str(row[1]) == "دابور"
            break

    # بررسی تاریخ در Metadata
    date_found = False
    for row in ws_meta.iter_rows(min_row=1, max_row=40, values_only=True):
        if row and len(row) >= 2 and "تاریخ شمسی" in str(row[0]):
            print(f"  تاریخ شمسی: {row[1]}")
            date_found = DATE.replace("/", "-") in str(row[1]).replace("/", "-") or \
                         DATE in str(row[1])
            break

    # بررسی Dashboard sheet (باید سطر داده داشته باشد)
    ws_dash = wb["Dashboard"]
    dash_rows = sum(1 for r in ws_dash.iter_rows(values_only=True) if any(c for c in r))
    print(f"  سطرهای غیرخالی Dashboard: {dash_rows}")

    # بررسی Snapshots sheet
    ws_snap = wb["Snapshots"]
    snap_rows = sum(1 for r in ws_snap.iter_rows(values_only=True) if any(c for c in r))
    print(f"  سطرهای غیرخالی Snapshots: {snap_rows} (باید > ۱ باشد)")

    # بررسی فایل در reports/
    actual_files = list(Path(PROJ).glob("reports/sim_report_دابور_*.xlsx"))
    print(f"  فایل‌های sim_report در reports/: {len(actual_files)}")
    if actual_files:
        print(f"  نام فایل: {actual_files[0].name}")

    # جمع‌بندی
    checks = {
        "شیت Metadata موجود": "Metadata" in wb.sheetnames,
        "نوع گزارش = شبیه‌سازی (Sim)": source_found,
        "نماد = دابور": symbol_found,
        "تاریخ درج شده": date_found,
        "Snapshots داده دارد": snap_rows > 1,
        "Dashboard داده دارد": dash_rows > 2,
        "فایل sim_report ساخته شد": len(actual_files) > 0,
    }

    print(f"\n{'='*55}")
    print("خلاصه بررسی:")
    for name, ok in checks.items():
        print(f"  {'✅' if ok else '❌'} {name}")

    all_ok = all(checks.values())
    print(f"\nنتیجه: {'✅ ریپورت Sim صحیح تولید شد' if all_ok else '❌ مشکل وجود دارد'}")

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

# پاکسازی فایل تست
if report_path.exists():
    report_path.unlink()
for f in Path(PROJ).glob("reports/sim_report_*.xlsx"):
    f.unlink()

sys.exit(0 if all_ok else 1)
