#!/usr/bin/env python3
"""تست: ۲ ستون ٪ نوسان لحظه‌ای و ٪ نوسان پایانی در انتهای جدول همه‌ی شیت‌ها.

بررسی می‌کند که هر دو ستون **آخرین دو ستون** جدول باشند (بعد از آخرین ستون اصلی)
و مقدار درست متناظر با هر تایم داشته باشند. در Dashboard ستون‌ها در جدول
«روند امتیاز» به‌صورت per-row قرار دارند (نه سلول تک).
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


def header_cols(ws, row=3):
    cols = []
    for col in range(1, ws.max_column + 1):
        v = ws.cell(row=row, column=col).value
        if v is not None:
            cols.append(col)
    return cols


def last_two_headers(ws, row=3):
    cols = header_cols(ws, row)
    if len(cols) < 2:
        return None, None, None, None
    c1, c2 = cols[-2], cols[-1]
    return (c1, ws.cell(row=row, column=c1).value,
            c2, ws.cell(row=row, column=c2).value)


def check_at_end(sheet_name, header_row=3, data_row=4,
                 exp_last=EXP_LAST, exp_close=EXP_CLOSE):
    ws = wb[sheet_name]
    c1, h1, c2, h2 = last_two_headers(ws, header_row)
    ok_hdr_last = h1 is not None and "نوسان لحظه‌ای" in str(h1)
    ok_hdr_close = h2 is not None and "نوسان پایانی" in str(h2)
    val_last = ws.cell(row=data_row, column=c1).value if c1 else None
    val_close = ws.cell(row=data_row, column=c2).value if c2 else None
    ok_val_last = val_last == exp_last
    ok_val_close = val_close == exp_close
    results[f"{sheet_name}: آخرین ستون ۱=٪ لحظه‌ای (ستون {c1})"] = ok_hdr_last
    results[f"{sheet_name}: آخرین ستون ۲=٪ پایانی (ستون {c2})"] = ok_hdr_close
    results[f"{sheet_name}: مقدار لحظه‌ای={exp_last}"] = ok_val_last
    results[f"{sheet_name}: مقدار پایانی={exp_close}"] = ok_val_close
    print(f"{sheet_name}: last_hdr={h1!r}@col{c1}({val_last}) "
          f"close_hdr={h2!r}@col{c2}({val_close}) "
          f"total_cols={len(header_cols(ws))}")


# --- Snapshots (مرجع) ---
check_at_end("Snapshots")

# --- SellPressure ---
check_at_end("SellPressure")

# --- Accumulation ---
check_at_end("Accumulation")

# --- History ---
check_at_end("History")

# --- Trades (اولین معامله قیمت 32160 → 0.5%) ---
exp_trade1 = round((32160 - YEST) / YEST * 100, 2)
check_at_end("Trades", exp_last=exp_trade1, exp_close=exp_trade1)

# --- Dashboard: جدول «روند امتیاز» ستون‌های per-row دارد، نه سلول تک ---
ws = wb["Dashboard"]
# ۱) سلول تک «٪ نوسان لحظه‌ای:» نباید وجود داشته باشد
single_cell = None
for row in ws.iter_rows(values_only=False):
    for c in row:
        if c.value is not None and "نوسان لحظه‌ای:" in str(c.value):
            single_cell = c
results["Dashboard: سلول تک حذف شده"] = single_cell is None
print(f"Dashboard single-cell removed: {'✅' if single_cell is None else '❌'}")

# ۲) در جدول روند امتیاز، ستون‌های ۴ و ۵ هدر درصد هستند
trend_hdr_row = None
for row in ws.iter_rows(values_only=False):
    for c in row:
        if c.value == "نمونه":
            trend_hdr_row = c.row
            break
    if trend_hdr_row:
        break
if trend_hdr_row:
    h4 = ws.cell(row=trend_hdr_row, column=4).value
    h5 = ws.cell(row=trend_hdr_row, column=5).value
    results["Dashboard: روند هدر col4=٪ لحظه‌ای"] = h4 is not None and "نوسان لحظه‌ای" in str(h4)
    results["Dashboard: روند هدر col5=٪ پایانی"] = h5 is not None and "نوسان پایانی" in str(h5)
    # اولین ردیف داده (نمونه ۱) → اولین snapshot درصد
    v4 = ws.cell(row=trend_hdr_row + 1, column=4).value
    v5 = ws.cell(row=trend_hdr_row + 1, column=5).value
    results["Dashboard: روند ردیف۱ لحظه‌ای=۱.۵"] = v4 == EXP_LAST
    results["Dashboard: روند ردیف۱ پایانی=۱.۰"] = v5 == EXP_CLOSE
    print(f"Dashboard trend hdr@row{trend_hdr_row}: col4={h4!r}({v4}) col5={h5!r}({v5})")
else:
    results["Dashboard: جدول روند یافت شد"] = False
    print("Dashboard trend table NOT found")

# --- خلاصه ---
print(f"\n{'='*60}")
print("خلاصه بررسی (۲ ستون در انتهای جدول همه‌ی شیت‌ها):")
for name, ok in results.items():
    print(f"  {'✅' if ok else '❌'} {name}")

all_ok = all(results.values())
print(f"\nنتیجه: {'✅ هر دو ستون در انتهای جدول همه‌ی شیت‌ها (per-row)' if all_ok else '❌ مشکل وجود دارد'}")

storage.close()
for f in Path(PROJ).glob("reports/live_report_*.xlsx"):
    f.unlink()
db_path.unlink(missing_ok=True)
sys.exit(0 if all_ok else 1)
