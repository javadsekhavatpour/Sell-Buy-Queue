#!/usr/bin/env python3
"""تست ریپورت اتوماتیک لایو.

مراحل:
  ۱) ساخت بانک با snapshotهای امروز (آخری با market_phase=closed)
  ۲) ساخت LiveMonitor (حالت live) با storage
  ۳) تست generate_live_report() → فایل live_report_{نماد}_{تاریخ}.xlsx
  ۴) تست _maybe_auto_report(snap) با فاز closed → تولید خودکار + جلوگیری از تکرار
  ۵) بررسی فایل اکسل: source=زنده (Live)، نماد، تاریخ، ستون‌های درصد
"""
import sys
from pathlib import Path
from datetime import datetime

PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)

import openpyxl
from early_warning.data_collector import MarketSnapshot, BestLimitRow, Trade
from early_warning.storage import MarketDataStorage
import web_dashboard_adaptive as m
from web_dashboard_adaptive import LiveMonitor, today_jalali_str

TODAY = today_jalali_str()
print(f"تاریخ امروز: {TODAY}")

# ساخت بانک با snapshotهای امروز
db_path = Path(PROJ) / "data" / "multi" / "فولاد.sqlite"
db_path.parent.mkdir(parents=True, exist_ok=True)
if db_path.exists():
    db_path.unlink()

st = MarketDataStorage(db_path)


def make_snap(idx, phase="continuous", hour=9, minute=0):
    return MarketSnapshot(
        timestamp=f"2026-11-19T{hour:02d}:{minute:02d}:00",
        tehran_time=f"{hour:02d}:{minute:02d}:00",
        date_jalali=TODAY, symbol="فولاد",
        last_price=32000 + idx * 40, close_price=32000 + idx * 40,
        yesterday_price=32000, max_allowed_price=35000, min_allowed_price=29000,
        open_price=32000, daily_high=32500 + idx * 40, daily_low=31800,
        total_volume=80000 + idx * 2000, total_value=2_600_000_000 + idx * 80_000_000,
        total_trade_count=300 + idx * 15, base_volume=200000,
        real_buy_value=1_500_000_000 + idx * 60_000_000,
        real_sell_value=1_100_000_000 + idx * 50_000_000,
        real_buy_count=200 + idx * 30, real_sell_count=180 + idx * 25,
        real_buy_volume=900_000 + idx * 30000, real_sell_volume=700_000 + idx * 25000,
        buy_rows=[BestLimitRow(price=31990, volume=8000 + idx * 200, order_count=15)],
        sell_rows=[BestLimitRow(price=32010, volume=5000 + idx * 100, order_count=12)],
        data_complete=True, data_status="ok", market_phase=phase,
        ins_code="2289764488799380", symbol_status="A",
    )


# ۵ snapshot پیوسته + ۱ snapshot بسته (پایان بازار)
for i in range(5):
    st.insert_snapshot(make_snap(i, phase="continuous", hour=9, minute=i * 10))
st.insert_snapshot(make_snap(5, phase="closed", hour=16, minute=30))
# معاملات
trades_batch = []
for i in range(4):
    trades_batch.append(Trade(
        trade_time=f"{9:02d}:{i*10:02d}:15",
        trade_price=32000 + i * 40,
        trade_volume=1000 + i * 200,
        trade_id=f"lt{i}", aggressor_side="buy" if i % 2 == 0 else "sell"))
st.insert_trades(trades_batch, "فولاد")
st.conn.close()
print(f"بانک: ۶ snapshot (۵ پیوسته + ۱ بسته) + ۴ معامله برای «فولاد» در {TODAY}")

# ساخت LiveMonitor (حالت live) با storage و config واقعی
cfg = m.load_cfg()
cfg.setdefault("test_symbol", {"name": "فولاد", "ins_code": "2289764488799380"})
storage = MarketDataStorage(db_path)
mon = LiveMonitor(cfg, mode="live", symbol="فولاد",
                   ins_code="2289764488799380", interval=30,
                   storage=storage)

print(f"\n{'='*55}")
print("تست ۱: generate_live_report() (دستی)")
path = mon.generate_live_report()
assert path is not None, "ریپورت تولید نشد!"
print(f"  فایل: {path.name}")
print(f"  وجود دارد: {path.exists()}")
assert path.exists() and path.name.startswith("live_report_")
assert "فولاد" in path.name
assert TODAY.replace("/", "-") in path.name

# بررسی فایل اکسل
wb = openpyxl.load_workbook(path)
print(f"  شیت‌ها: {wb.sheetnames}")

ws_meta = wb["Metadata"]
source_found = False
symbol_found = False
date_found = False
pct_last = pct_close = None
for row in ws_meta.iter_rows(min_row=1, max_row=45, values_only=True):
    if row and len(row) >= 2:
        k, v = str(row[0]), row[1]
        if "نوع گزارش" in k:
            source_found = "زنده" in str(v) and "Live" in str(v)
            print(f"  نوع گزارش: {v}")
        elif k == "نماد":
            symbol_found = v == "فولاد"
            print(f"  نماد: {v}")
        elif "تاریخ شمسی" in k:
            date_found = TODAY.replace("/", "-") in str(v).replace("/", "-") or TODAY in str(v)
            print(f"  تاریخ: {v}")
        elif "نوسان قیمت لحظه‌ای" in k:
            pct_last = v
        elif "نوسان قیمت پایانی" in k:
            pct_close = v

# yesterday=32000, آخرین snapshot (closed, i=5) last=32200 → pct = 0.625 → round(۲)=0.62
exp_pct = round((32200 - 32000) / 32000 * 100, 2)
print(f"  ٪ لحظه‌ای: {pct_last} (انتظار: {exp_pct})")
print(f"  ٪ پایانی:  {pct_close} (انتظار: {exp_pct})")
pct_ok = (pct_last is not None and abs(float(pct_last) - exp_pct) < 0.01
          and pct_close is not None and abs(float(pct_close) - exp_pct) < 0.01)

# بررسی Snapshots — ستون‌های درصد (آخرین دو ستون هدر)
ws_snap = wb["Snapshots"]
# ستون‌های هدر درصد را بر اساس برچسب پیدا می‌کنیم (در انتهای جدول)
snap_pct_cols = []
for col in range(1, ws_snap.max_column + 1):
    v = ws_snap.cell(row=3, column=col).value
    if v is not None and "نوسان" in str(v):
        snap_pct_cols.append((col, str(v)))
snap_pct_hdr = (len(snap_pct_cols) >= 2
                and "لحظه" in snap_pct_cols[-2][1]
                and "پایان" in snap_pct_cols[-1][1])
snap_rows = sum(1 for r in ws_snap.iter_rows(values_only=True) if any(c for c in r))
print(f"  سطرهای Snapshots: {snap_rows}")
print(f"  ستون‌های درصد هدر: {snap_pct_cols}")

print(f"\n{'='*55}")
print("تست ۲: _maybe_auto_report (اتوماتیک هنگام بسته‌شدن بازار)")

# پاک فایل قبلی و ریست tracking
for f in Path(PROJ).glob("reports/live_report_*.xlsx"):
    f.unlink()
mon._live_report_date = None

# snapshot پیوسته → نباید تولید کند
snap_open = make_snap(10, phase="continuous", hour=10, minute=0)
mon._maybe_auto_report(snap_open)
auto1 = list(Path(PROJ).glob("reports/live_report_*.xlsx"))
print(f"  فاز continuous → فایل تولید: {len(auto1)} (انتظار: ۰)")
assert len(auto1) == 0, "نباید در فاز continuous تولید کند!"

# snapshot بسته → باید تولید کند
snap_closed = make_snap(11, phase="closed", hour=16, minute=30)
mon._maybe_auto_report(snap_closed)
auto2 = list(Path(PROJ).glob("reports/live_report_*.xlsx"))
print(f"  فاز closed → فایل تولید: {len(auto2)} (انتظار: ۱)")
assert len(auto2) == 1, "باید در فاز closed تولید کند!"

# دوباره فاز closed → نباید تکرار کند (همان روز)
mon._maybe_auto_report(snap_closed)
auto3 = list(Path(PROJ).glob("reports/live_report_*.xlsx"))
print(f"  فاز closed دوباره → فایل: {len(auto3)} (انتظار: ۱ — بدون تکرار)")
assert len(auto3) == 1, "نباید در همان روز تکرار کند!"

# جمع‌بندی
checks = {
    "فایل live_report ساخته شد": path.name.startswith("live_report_"),
    "نام شامل نماد": "فولاد" in path.name,
    "نام شامل تاریخ": TODAY.replace("/", "-") in path.name,
    "شیت Metadata موجود": "Metadata" in wb.sheetnames,
    "source = زنده (Live)": source_found,
    "نماد = فولاد": symbol_found,
    "تاریخ امروز درج شده": date_found,
    "درصد نوسان در Metadata": pct_ok,
    "هدر ستون‌های درصد در Snapshots": snap_pct_hdr,
    "Snapshots داده دارد (۷ سطر)": snap_rows >= 7,
    "اتوماتیک: فاز continuous تولید نمی‌کند": len(auto1) == 0,
    "اتوماتیک: فاز closed تولید می‌کند": len(auto2) == 1,
    "اتوماتیک: تکرار در همان روز نیست": len(auto3) == 1,
}

print(f"\n{'='*55}")
print("خلاصه بررسی:")
for name, ok in checks.items():
    print(f"  {'✅' if ok else '❌'} {name}")

all_ok = all(checks.values())
print(f"\nنتیجه: {'✅ ریپورت لایو اتوماتیک صحیح کار کرد' if all_ok else '❌ مشکل وجود دارد'}")

# پاکسازی
storage.close()
for f in Path(PROJ).glob("reports/live_report_*.xlsx"):
    f.unlink()
db_path.unlink(missing_ok=True)

sys.exit(0 if all_ok else 1)
