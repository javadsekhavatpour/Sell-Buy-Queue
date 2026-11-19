#!/usr/bin/env python3
"""
live.py — داشبورد زنده (Live)

داده از TSETMC دریافت می‌شود، مستقیم در وب نشان داده می‌شود و هم‌زمان
در بانک SQLite ذخیره می‌گردد. هدف: بررسی بصری صحت جمع‌آوری زنده.

اجرا:
  python live.py                              # نماد پیش‌فرض پیکربندی
  python live.py --symbol دابور               # نماد دلخواه
  python live.py --symbol دابور --interval 30 --port 8060

وب: http://localhost:<port>
"""
from __future__ import annotations

import argparse

import web_dashboard_adaptive as adapt
from web_dashboard_live import load_cfg, load_price_range_live
from early_warning import MarketDataCollector, MarketDataStorage, AdaptiveNormalizer


def main():
    ap = argparse.ArgumentParser(
        description="داشبورد زنده — داده از TSETMC → نمایش وب + ذخیره در بانک")
    ap.add_argument("--symbol", default=None, help="نام نماد (پیش‌فرض: پیکربندی)")
    ap.add_argument("--ins-code", default=None, help="کد TSETMC نماد")
    ap.add_argument("--interval", type=int, default=30,
                    help="فاصله نمونه‌برداری از TSETMC (ثانیه، پیش‌فرض ۳۰)")
    ap.add_argument("--port", type=int, default=8052)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    cfg = load_cfg()
    symbol = args.symbol or cfg.get("test_symbol", {}).get("name", "ریتون")
    ins_code = args.ins_code or cfg.get("test_symbol", {}).get("ins_code", "")

    # جستجوی کد نماد در TSETMC اگر داده نشده
    if symbol and not ins_code:
        print(f"جستجوی کد نماد '{symbol}' در TSETMC...")
        tmp = MarketDataCollector(cfg)
        res = tmp.search_symbol(symbol)
        if res:
            ins_code = res[0]["code"]
            print(f"کد پیدا شد: {ins_code}")
        else:
            print(f"نماد '{symbol}' پیدا نشد — از کد پیکربندی استفاده می‌شود.")

    db_path = adapt.ROOT / "data" / "multi" / f"{symbol}.sqlite"
    storage = MarketDataStorage(db_path)
    load_price_range_live(cfg, symbol, ins_code, storage=storage)
    normalizer = AdaptiveNormalizer(storage, cfg)

    adapt.MONITOR = adapt.AdaptiveLiveMonitor(
        cfg, mode="live", symbol=symbol, ins_code=ins_code,
        interval=args.interval, normalizer=normalizer, storage=storage,
    )
    adapt.MONITOR.start()

    print("=" * 60)
    print("داشبورد زنده (Live) — TSETMC → وب + بانک")
    print(f"نماد      : {symbol} (کد: {ins_code})")
    print(f"نمونه‌برداری: هر {args.interval} ثانیه از TSETMC")
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
