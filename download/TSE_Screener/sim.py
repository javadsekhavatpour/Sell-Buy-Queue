#!/usr/bin/env python3
"""
sim.py — داشبورد شبیه‌سازی (Sim)

داده‌های ذخیره‌شده در بانک SQLite برای یک نماد + یک تاریخ با سرعت
قابل‌تنظیم پخش می‌شوند. کنترل‌ها: play/pause، تغییر سرعت زنده،
پرش ±N نمونه، seek. هدف: ادامه و رفع اشکال پروژه در زمانی که بازار
بسته است — بدون نیاز به داده‌ی زنده.

اجرا:
  python sim.py --symbol دابور --date 1405/08/28 --time-speed 10 --port 8060
  python sim.py --symbol دابور                      # آخرین تاریخ موجود
  python sim.py --port 8060                          # از /sim انتخاب کن

وب: http://localhost:<port>     (نوار کنترل بالای داشبورد)
     http://localhost:<port>/sim (فرم انتخاب نماد/تاریخ/سرعت)
"""
from __future__ import annotations

import argparse

import web_dashboard_adaptive as adapt
from web_dashboard_live import load_cfg
from early_warning import MarketDataStorage, AdaptiveNormalizer


def main():
    ap = argparse.ArgumentParser(
        description="داشبورد شبیه‌سازی — پخش داده‌های بانک با کنترل")
    ap.add_argument("--symbol", default=None, help="نام نماد (پیش‌فرض: پیکربندی)")
    ap.add_argument("--date", default=None,
                    help="تاریخ شمسی (مثلاً 1405/08/28) — اگر داده نشود، آخرین تاریخ موجود")
    ap.add_argument("--time-speed", type=float, default=10.0,
                    help="سرعت گذر زمان (مثلاً 10 = ۱۰ برابر، پیش‌فرض ۱۰)")
    ap.add_argument("--port", type=int, default=8052)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    cfg = load_cfg()
    symbol = args.symbol or cfg.get("test_symbol", {}).get("name", "ریتون")
    db_path = adapt.ROOT / "data" / "multi" / f"{symbol}.sqlite"

    if not db_path.exists():
        print(f"⚠ بانک {db_path} وجود ندارد.")
        print(f"  ابتدا با run_multi.py یا live.py داده جمع کنید.")
        print(f"  یا از صفحه‌ی /sim برای انتخاب نماد دیگر استفاده کنید.")

    storage = MarketDataStorage(db_path) if db_path.exists() else None
    normalizer = AdaptiveNormalizer(storage, cfg) if storage else None

    date_jalali = args.date
    if not date_jalali and storage:
        # آخرین تاریخ موجود در بانک
        row = storage.conn.execute(
            "SELECT date_jalali FROM snapshots WHERE symbol=? "
            "ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        date_jalali = row[0] if row else ""

    if symbol and date_jalali and storage:
        adapt.MONITOR = adapt.SimulationAdaptiveMonitor(
            cfg, symbol=symbol, date_jalali=date_jalali, db_path=db_path,
            time_speed=args.time_speed, normalizer=normalizer, storage=storage,
        )
        adapt.MONITOR.start()
        print("=" * 60)
        print("داشبورد شبیه‌سازی (Sim) — پخش از بانک با کنترل")
        print(f"نماد      : {symbol}")
        print(f"تاریخ     : {date_jalali}")
        sm = adapt.MONITOR
        print(f"نمونه‌ها   : {len(sm._sim_snaps)} (سرعت {sm._sim_speed}x)")
        print(f"بانک       : {db_path}")
        print(f"آدرس      : http://localhost:{args.port}")
        print(f"صفحه‌ی انتخاب: http://localhost:{args.port}/sim")
        print("=" * 60)
    else:
        print("=" * 60)
        print("داشبورد شبیه‌سازی (Sim) — بدون پارامتر")
        print(f"از صفحه‌ی /sim برای انتخاب نماد/تاریخ/سرعت استفاده کنید:")
        print(f"  http://localhost:{args.port}/sim")
        print("=" * 60)

    try:
        adapt.app.run(host=args.host, port=args.port, threaded=True,
                      debug=False, use_reloader=False)
    finally:
        if storage:
            try:
                storage.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
