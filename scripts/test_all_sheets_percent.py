#!/usr/bin/env python3
"""تست جامع: ۲ ستون ٪ نوسان لحظه‌ای و ٪ نوسان پایانی در همه‌ی شیت‌ها.

بررسی می‌کند که هر دو ستون در شیت‌های زیر وجود دارند و مقدار درست دارند:
  - Snapshots (مرجع)
  - SellPressure
  - Accumulation
  - History
  - Trades
  - Dashboard (به‌صورت مقدار کلیدی)
  - Metadata (خلاصه پایان روز)
"""
import sys
from pathlib import Path

PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)

import openpyxl
from early_warning.data_collector import MarketSnapshot, BestLimitRow, Trade
from early_warning.storage import MarketDataStorage
import web_dashboard_adaptive as m
from web_dashboard_adaptive import LiveMonitor, today_jalali_str

TODAY = today_jalali_str()
YEST = 32000.0
LAST = 32480.0   # +1.5%
CLOSE = 32320.0  # +1.0%

# ساخت بانک
db_path = Path(PROJ) / "data" / "multi" / "فخوز.sqlite"
db_path.parent.mkdir(parents=True, exist_ok=True)
if db_path.exists():
    db_path.unlink()
st = MarketDataStorage(db_path)


def mk(i, phase="continuous", h=9, mn=0, last=LAST, close=CLOSE):
    return MarketSnapshot(
        timestamp=f"2026-11-19T{h:02d}:{mn:02d}:00", tehran_time=f"{h:02d}:{mn:02d}:00",
        date_jalali=TODAY, symbol="فخوز", last_price=last, close_price=close,
        yesterday_price=YEST, max_allowed_price=35000, min_allowed_price=29000,
        open_price=32000, daily_high=32500, daily_low=31800,
        total_volume=80000, total_value=2.6e9, total_trade_count=300, base_volume=200000,
        real_buy_value=1.5e9, real_sell_value=1.1e9, real_buy_count=200, real_sell_count=180,
        real_buy_volume=900000, real_sell_volume=700000,
        buy_rows=[BestLimitRow(price=31990, volume=8000, order_count=15)],
        sell_rows=[BestLimitRow(price=32010, volume=5000, order_count=12)],
        data_complete=True, data_status="ok", market_phase=phase,
        ins_code="2289764488799380", symbol_status="A")


for i in range(5):
    st.insert_snapshot(mk(i, h=9, mn=i * 10))
st.insert_snapshot(mk(5, phase="closed", h=16, mn=30, last=LAST, close=CLOSE))
# معاملات با قیمت‌های متفاوت
st.insert_trades([
    Trade(trade_time="09:05:10", trade_price=32160, trade_volume=500, trade_id="t1", aggressor_side="buy"),
    Trade(trade_time="09:15:20", trade_price=32480, trade_volume=300, trade_id="t2", aggressor_side="buy"),
    Trade(trade_time="10:00:00", trade_price=32320, trade_volume=800, trade_id="t3", aggressor_side="sell"),
], "فخوز")
st.conn.close()

cfg = m.load_cfg()
storage = MarketDataStorage(db_path)
mon = LiveMonitor(cfg, mode="live", symbol="فخوز", ins_code="2289764488799380",
                   interval=30, storage=storage)
path = mon.generate_live_report()
print(f"ریپورت: {path.name}\n")

wb = openpyxl.load_workbook(path)
EXP_LAST = round((LAST - YEST) / YEST * 100, 2)   # 1.5
EXP_CLOSE = round((CLOSE - YEST) / YEST * 100, 2)  # 1.0

results = {}


def find_header_col(ws, label, row=3):
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=row, column=col).value
        if v and label in str(v):
            return col
    return None


def find_cell(ws, needle):
    for row in ws.iter_rows(values_only=False):
        for c in row:
            if c.value is not None and needle in str(c.value):
                return c
    return None


# --- Snapshots (مرجع) ---
ws = wb["Snapshots"]
col_last = find_header_col(ws, "نوسان لحظه‌ای")
col_close = find_header_col(ws, "نوسان پایانی")
val_last = ws.cell(row=4, column=col_last).value if col_last else None
val_close = ws.cell(row=4, column=col_close).value if col_close else None
results["Snapshots: هدر ٪ لحظه‌ای"] = col_last is not None
results["Snapshots: هدر ٪ پایانی"] = col_close is not None
results["Snapshots: مقدار لحظه‌ای=۱.۵"] = val_last == EXP_LAST
results["Snapshots: مقدار پایانی=۱.۰"] = val_close == EXP_CLOSE
print(f"Snapshots: col_last={col_last}({val_last}) col_close={col_close}({val_close})")

# --- SellPressure ---
ws = wb["SellPressure"]
col_last = find_header_col(ws, "نوسان لحظه‌ای")
col_close = find_header_col(ws, "نوسان پایانی")
val_last = ws.cell(row=4, column=col_last).value if col_last else None
val_close = ws.cell(row=4, column=col_close).value if col_close else None
results["SellPressure: هدر ٪ لحظه‌ای"] = col_last is not None
results["SellPressure: هدر ٪ پایانی"] = col_close is not None
results["SellPressure: مقدار لحظه‌ای=۱.۵"] = val_last == EXP_LAST
results["SellPressure: مقدار پایانی=۱.۰"] = val_close == EXP_CLOSE
print(f"SellPressure: col_last={col_last}({val_last}) col_close={col_close}({val_close})")

# --- Accumulation ---
ws = wb["Accumulation"]
col_last = find_header_col(ws, "نوسان لحظه‌ای")
col_close = find_header_col(ws, "نوسان پایانی")
val_last = ws.cell(row=4, column=col_last).value if col_last else None
val_close = ws.cell(row=4, column=col_close).value if col_close else None
results["Accumulation: هدر ٪ لحظه‌ای"] = col_last is not None
results["Accumulation: هدر ٪ پایانی"] = col_close is not None
results["Accumulation: مقدار لحظه‌ای=۱.۵"] = val_last == EXP_LAST
results["Accumulation: مقدار پایانی=۱.۰"] = val_close == EXP_CLOSE
print(f"Accumulation: col_last={col_last}({val_last}) col_close={col_close}({val_close})")

# --- History ---
ws = wb["History"]
col_last = find_header_col(ws, "نوسان لحظه‌ای")
col_close = find_header_col(ws, "نوسان پایانی")
val_last = ws.cell(row=4, column=col_last).value if col_last else None
val_close = ws.cell(row=4, column=col_close).value if col_close else None
results["History: هدر ٪ لحظه‌ای"] = col_last is not None
results["History: هدر ٪ پایانی"] = col_close is not None
results["History: مقدار لحظه‌ای=۱.۵"] = val_last == EXP_LAST
results["History: مقدار پایانی=۱.۰"] = val_close == EXP_CLOSE
print(f"History: col_last={col_last}({val_last}) col_close={col_close}({val_close})")

# --- Trades ---
ws = wb["Trades"]
col_last = find_header_col(ws, "نوسان لحظه‌ای")
col_close = find_header_col(ws, "نوسان پایانی")
# اولین معامله: قیمت 32160 → (32160-32000)/32000*100 = 0.5
exp_trade1 = round((32160 - YEST) / YEST * 100, 2)
val_last = ws.cell(row=4, column=col_last).value if col_last else None
val_close = ws.cell(row=4, column=col_close).value if col_close else None
results["Trades: هدر ٪ لحظه‌ای"] = col_last is not None
results["Trades: هدر ٪ پایانی"] = col_close is not None
results["Trades: مقدار معامله ۱=۰.۵"] = val_last == exp_trade1 and val_close == exp_trade1
print(f"Trades: col_last={col_last}({val_last}) col_close={col_close}({val_close}) exp={exp_trade1}")

# --- Dashboard (کلیدی) ---
ws = wb["Dashboard"]
lbl_last = find_cell(ws, "نوسان لحظه‌ای:")
lbl_close = find_cell(ws, "نوسان پایانی:")
val_last = ws.cell(row=lbl_last.row, column=lbl_last.column + 1).value if lbl_last else None
val_close = ws.cell(row=lbl_close.row, column=lbl_close.column + 1).value if lbl_close else None
results["Dashboard: برچسب ٪ لحظه‌ای"] = lbl_last is not None
results["Dashboard: برچسب ٪ پایانی"] = lbl_close is not None
results["Dashboard: مقدار لحظه‌ای=۱.۵"] = val_last == EXP_LAST
results["Dashboard: مقدار پایانی=۱.۰"] = val_close == EXP_CLOSE
print(f"Dashboard: last={val_last} close={val_close}")

# --- Metadata (خلاصه پایان روز) ---
ws = wb["Metadata"]
lbl_last = find_cell(ws, "نوسان قیمت لحظه‌ای")
lbl_close = find_cell(ws, "نوسان قیمت پایانی")
results["Metadata: خلاصه ٪ لحظه‌ای"] = lbl_last is not None
results["Metadata: خلاصه ٪ پایانی"] = lbl_close is not None
print(f"Metadata: last_label={'✓' if lbl_last else '✗'} close_label={'✓' if lbl_close else '✗'}")

# --- خلاصه ---
print(f"\n{'='*55}")
print("خلاصه بررسی (۲ ستون در همه‌ی شیت‌ها):")
for name, ok in results.items():
    print(f"  {'✅' if ok else '❌'} {name}")

all_ok = all(results.values())
print(f"\nنتیجه: {'✅ هر دو ستون در همه‌ی شیت‌ها موجود و صحیح' if all_ok else '❌ مشکل وجود دارد'}")

# پاکسازی
storage.close()
for f in Path(PROJ).glob("reports/live_report_*.xlsx"):
    f.unlink()
db_path.unlink(missing_ok=True)
sys.exit(0 if all_ok else 1)
