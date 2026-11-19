#!/usr/bin/env python3
"""تست رفع باگ «اعداد ثابت» در /db mode.

سناریو:
  ۱) ساخت بانک با ۲ snapshot (مقادیر تجمعی متفاوت)
  ۲) استارت /db → مانیتور آخرین snapshot را می‌خواند
  ۳) درج snapshot جدید با real_buy_count بیشتر
  ۴) بررسی /api/live: فاکتور sell_breadth و buy_flow باید غیرصفر باشند
  ۵) درج snapshot دیگر با مقادیر متفاوت
  ۶) بررسی: مقادیر فاکتور تغییر کرده‌اند
"""
import json
import os
import sys
import time
import sqlite3
import subprocess
import urllib.request
import urllib.parse
from pathlib import Path

PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)

from early_warning.data_collector import MarketSnapshot, BestLimitRow
from early_warning.storage import MarketDataStorage

db_path = Path(PROJ) / "data" / "multi" / "دابور.sqlite"
db_path.parent.mkdir(parents=True, exist_ok=True)
if db_path.exists():
    db_path.unlink()

DATE = "1405/08/28"


def make_snap(idx, rbc, rsc, rbv, rsv, buy_vol, sell_vol, hour, minute):
    """snapshot با مقادیر تجمعی قابل‌کنترل."""
    return MarketSnapshot(
        timestamp=f"2026-11-19T{hour:02d}:{minute:02d}:00",
        tehran_time=f"{hour:02d}:{minute:02d}:00",
        date_jalali=DATE, symbol="دابور",
        last_price=12000 + idx * 10, close_price=12000 + idx * 10,
        yesterday_price=12000, max_allowed_price=13000, min_allowed_price=11000,
        real_buy_value=rbv, real_sell_value=rsv,
        real_buy_count=rbc, real_sell_count=rsc,
        real_buy_volume=rbv // 1000, real_sell_volume=rsv // 1000,
        buy_rows=[BestLimitRow(price=11990, volume=buy_vol, order_count=10)],
        sell_rows=[BestLimitRow(price=12010, volume=sell_vol, order_count=8)],
        data_complete=True,
    )


# snapshot‌های اولیه
st = MarketDataStorage(db_path)
st.insert_snapshot(make_snap(1, rbc=100, rsc=80, rbv=500_000_000, rsv=400_000_000,
                              buy_vol=5000, sell_vol=3000, hour=9, minute=0))
st.insert_snapshot(make_snap(2, rbc=150, rsc=120, rbv=800_000_000, rsv=650_000_000,
                              buy_vol=5200, sell_vol=3500, hour=9, minute=5))
st.conn.close()
print(f"بانک اولیه: ۲ snapshot (real_buy_count: 100→150)")

# استارت سرور
env = {**os.environ, "PYTHONPATH": PROJ}
proc = subprocess.Popen(
    ["/home/z/.venv/bin/python3", "-u", f"{PROJ}/web_dashboard_adaptive.py",
     "--port", "5591"],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, text=True,
)
time.sleep(4)


def fetch_api():
    try:
        with urllib.request.urlopen("http://127.0.0.1:5591/api/live", timeout=5) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}


def get_factor(d, side, name):
    """استخراج normalized و raw_value یک فاکتور."""
    eng = d.get("engines", {})
    factors = (eng.get(side) or {}).get("factors") or []
    for f in factors:
        if f.get("name") == name:
            return f.get("normalized"), f.get("raw_value")
    return None, None


def insert_snap(idx, rbc, rsc, rbv, rsv, buy_vol, sell_vol, hour, minute):
    """درج مستقیم snapshot در بانک (شبیه‌سازی run_multi)."""
    conn = sqlite3.connect(str(db_path))
    snap = make_snap(idx, rbc, rsc, rbv, rsv, buy_vol, sell_vol, hour, minute)
    # استفاده از insert_snapshot نیاز به شیء storage دارد
    st2 = MarketDataStorage(db_path)
    st2.insert_snapshot(snap)
    st2.conn.close()


results = {}
try:
    # ۱) شروع /db
    q = urllib.parse.urlencode({"symbol": "دابور"})
    with urllib.request.urlopen(f"http://127.0.0.1:5591/db?{q}", timeout=5) as r:
        print(f"GET /db: {r.status}")
    time.sleep(7)  # مانیتور یک poll انجام می‌دهد (۵ث)

    d0 = fetch_api()
    print(f"\nوضعیت اولیه: history={len(d0.get('history', {}).get('time', []))} samples")
    nb0, rb0 = get_factor(d0, "sell", "sell_breadth")
    nf0, rf0 = get_factor(d0, "sell", "sell_flow")
    bb0, brb0 = get_factor(d0, "buy", "buy_breadth")
    bf0, brf0 = get_factor(d0, "buy", "buy_flow")
    print(f"  sell_breadth: norm={nb0}, raw={rb0}")
    print(f"  buy_breadth:  norm={bb0}, raw={brb0}")

    # ۲) درج snapshot جدید (real_buy_count: 150→220, delta=70)
    insert_snap(3, rbc=220, rsc=180, rbv=1_200_000_000, rsv=950_000_000,
                buy_vol=5500, sell_vol=3800, hour=9, minute=10)
    print("\nدرج snapshot ۳ (real_buy_count: 150→220, delta=70)")
    time.sleep(7)  # مانیتور snapshot جدید را می‌خواند

    d1 = fetch_api()
    nb1, rb1 = get_factor(d1, "sell", "sell_breadth")
    nf1, rf1 = get_factor(d1, "sell", "sell_flow")
    bb1, brb1 = get_factor(d1, "buy", "buy_breadth")
    bf1, brf1 = get_factor(d1, "buy", "buy_flow")
    print(f"  sell_breadth: norm={nb1}, raw={rb1}")
    print(f"  sell_flow:    norm={nf1}, raw={rf1}")
    print(f"  buy_breadth:  norm={bb1}, raw={brb1}")
    print(f"  buy_flow:     norm={bf1}, raw={brf1}")

    # ۳) درج snapshot دیگر (real_buy_count: 220→350, delta=130)
    insert_snap(4, rbc=350, rsc=250, rbv=1_800_000_000, rsv=1_400_000_000,
                buy_vol=4800, sell_vol=4200, hour=9, minute=15)
    print("\nدرج snapshot ۴ (real_buy_count: 220→350, delta=130)")
    time.sleep(7)

    d2 = fetch_api()
    nb2, rb2 = get_factor(d2, "sell", "sell_breadth")
    nf2, rf2 = get_factor(d2, "sell", "sell_flow")
    bb2, brb2 = get_factor(d2, "buy", "buy_breadth")
    bf2, brf2 = get_factor(d2, "buy", "buy_flow")
    print(f"  sell_breadth: norm={nb2}, raw={rb2}")
    print(f"  sell_flow:    norm={nf2}, raw={rf2}")
    print(f"  buy_breadth:  norm={bb2}, raw={brb2}")
    print(f"  buy_flow:     norm={bf2}, raw={brf2}")

    # بررسی: آیا مقادیر raw تغییر کردند؟ (حداقل یکی از طرفین)
    changed_breadth = (rb1 != rb0) and (rb2 != rb1)
    changed_flow = (rf1 != rf0) and (rf2 != rf1)
    changed_buy_breadth = (brb1 != brb0) and (brb2 != brb1)
    nonzero_after = ((rb1 not in (None, 0)) or (brb1 not in (None, 0)))

    print(f"\n{'='*55}")
    print(f"sell_breadth raw تغییر کرد: {'✅' if changed_breadth else '❌'}")
    print(f"  {rb0} → {rb1} → {rb2}")
    print(f"buy_breadth raw تغییر کرد:  {'✅' if changed_buy_breadth else '❌'}")
    print(f"  {brb0} → {brb1} → {brb2}")
    print(f"غیرصفر بعد از درج داده جدید: {'✅' if nonzero_after else '❌'}")

    results["breadth_changes"] = changed_breadth or changed_buy_breadth
    results["flow_changes"] = changed_flow
    results["nonzero"] = nonzero_after

finally:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()

ok = all(results.values())
print(f"\nنتیجه: {'✅ اعداد تغییر می‌کنند — باگ رفع شد' if ok else '❌ هنوز ثابت است'}")
sys.exit(0 if ok else 1)
