#!/usr/bin/env python3
"""
db.py — داشبورد بانک (DB)

آخرین داده ذخیره‌شده در بانک SQLite هر چند ثانیه خوانده و در وب نمایش
داده می‌شود. هیچ فراخوانی TSETMC انجام نمی‌شود. هدف: بررسی بصری صحت
اطلاعاتی که run_multi.py / run_live.py در بانک ذخیره کرده‌اند.

وقتی run_multi.py در پس‌زمینه در حال جمع‌آوری است، این داشبورد نشان
می‌دهد که داده‌ها به‌درستی در بانک می‌نشینند.

اجرا:
  python db.py                              # نماد پیش‌فرض، فاصله ۵ ثانیه
  python db.py --symbol دابور               # نماد دلخواه
  python db.py --symbol دابور --interval 3 --port 8060

وب: http://localhost:<port>
"""
from __future__ import annotations

import argparse

import web_dashboard_adaptive as adapt
from web_dashboard_live import load_cfg
from early_warning import MarketDataStorage, AdaptiveNormalizer


def main():
    ap = argparse.ArgumentParser(
        description="داشبورد بانک — خواندن لحظه‌ای آخرین داده از DB")
    ap.add_argument("--symbol", default=None, help="نام نماد (پیش‌فرض: پیکربندی)")
    ap.add_argument("--interval", type=int, default=5,
                    help="فاصله خواندن از بانک (ثانیه، پیش‌فرض ۵)")
    ap.add_argument("--port", type=int, default=8052)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    cfg = load_cfg()
    symbol = args.symbol or cfg.get("test_symbol", {}).get("name", "ریتون")
    db_path = adapt.ROOT / "data" / "multi" / f"{symbol}.sqlite"

    if not db_path.exists():
        print(f"⚠ بانک {db_path} وجود ندارد.")
        print(f"  ابتدا با run_multi.py یا live.py داده جمع کنید.")
        return

    storage = MarketDataStorage(db_path)
    normalizer = AdaptiveNormalizer(storage, cfg)

    adapt.MONITOR = adapt.DBLiveMonitor(
        cfg, symbol=symbol, interval=args.interval,
        normalizer=normalizer, storage=storage,
    )
    adapt.MONITOR.start()

    print("=" * 60)
    print("داشبورد بانک (DB) — خواندن لحظه‌ای از بانک")
    print(f"نماد      : {symbol}")
    print(f"خواندن    : هر {args.interval} ثانیه از بانک")
    print(f"بانک       : {db_path}")
    print(f"آدرس      : http://localhost:{args.port}")
    print("=" * 60)

    try:
        adapt.app.run(host=args.host, port=args.port, threaded=True,
                      debug=False, use_reloader=False)
    finally:
        try:
            storage.close()
        except Exception:
            pass


if __name__ == "__main__":
    main()
