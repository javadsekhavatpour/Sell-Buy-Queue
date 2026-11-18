"""
run_live.py
اجرای ماژول هشدار زودهنگام با داده واقعی TSETMC در بازار زنده.

این نسخه به جای تولید گزارش در پایان، داده‌ها را زنده در SQLite
ذخیره می‌کند و هر نمونه را هم‌زمان تحلیل می‌کند.

نحوه اجرا (Windows 10):
    cd C:\\TSE_Screener
    python run_live.py

نمونه‌برداری و تحلیل (نسخه ۱.۲):
  - تابلو هر `sampling.interval_seconds` ثانیه (پیش‌فرض ۵ ثانیه) جمع‌آوری
    و در SQLite ذخیره می‌شود (برای داشبورد زنده و گروه E)
  - موتورهای تحلیلی با گام `sampling.analysis_interval_seconds`
    (پیش‌فرض ۶۰ ثانیه) اجرا می‌شوند تا کالیبراسیون آستانه‌ها که برای
    نمونه‌های ۶۰ ثانیه‌ای تنظیم شده حفظ شود
  - حداکثر نمونه‌ها به‌صورت خودکار پوشش کامل جلسه (08:45 تا 12:30) است

زمان‌بندی پیشنهادی:
    08:45-09:00  پیش‌گشایش (دریافت و ذخیره، بدون موتورها)
    09:00-12:30  معاملات پیوسته (دریافت + ذخیره + موتورها + هشدار)
    12:30+       ذخیره نهایی، کنترل نقص‌ها، تولید گزارش
"""

from __future__ import annotations

import sys
import json
import time
import argparse
import signal
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import (
    MarketDataCollector,
    DataValidator,
    SellPressureDetector,
    BuyPressureDetector,
    AlertEngine,
    SpeedIndicatorEngine,
    ExcelReportGenerator,
    MarketDataStorage,
    AdaptiveNormalizer,
    MarketPhase,
    MarketSnapshot,
    Trade,
    load_range_rules,
    get_symbol_category,
    get_category_percent,
    compute_daily_params,
    to_jalali,
)
from early_warning.market_detector import detect_market, in_trading_window, tehran_now


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    print(f"📂 فایل پیکربندی: {cfg_path}")
    print(f"   وجود دارد: {cfg_path.exists()}")
    if not cfg_path.exists():
        print(f"❌ فایل پیکربندی پیدا نشد!")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    print(f"   نماد در پیکربندی: {cfg['test_symbol']['name']} (کد: {cfg['test_symbol']['ins_code']})")
    return cfg


def parse_args():
    p = argparse.ArgumentParser(description="TSE Early Warning - Live Mode (SQLite)")
    p.add_argument("--symbol", default=None, help="نام نماد (اگر ندهید، از پیکربندی استفاده می‌شود)")
    p.add_argument("--ins-code", default=None, help="کد TSETMC (اگر ندهید، از پیکربندی استفاده می‌شود)")
    p.add_argument("--interval", type=int, default=None,
                   help="فاصله نمونه‌برداری (ثانیه) - پیش‌فرض: sampling.interval_seconds پیکربندی (۵)")
    p.add_argument("--analysis-interval", type=int, default=None,
                   help="فاصله اجرای موتورهای تحلیلی (ثانیه) - پیش‌فرض: sampling.analysis_interval_seconds پیکربندی (۶۰)")
    p.add_argument("--max-samples", type=int, default=None,
                   help="حداکثر تعداد نمونه - پیش‌فرض: پوشش کامل جلسه معاملاتی")
    p.add_argument("--db", default="data/early_warning_live.sqlite", help="مسیر فایل SQLite")
    p.add_argument("--output", default="reports/early_warning_report_live.xlsx")
    p.add_argument("--prompt", action="store_true",
                   help="از کاربر بپرسد کدام نماد (پیش‌فرض: بدون پرسش از پیکربندی)")
    return p.parse_args()


def load_config_with_prompt(args) -> dict:
    """
    بارگذاری پیکربندی و انتخاب نماد.

    رفتار:
      - پیش‌فرض: از نماد فعلی پیکربندی استفاده می‌کند (بدون پرسش)
      - با --prompt: از کاربر می‌پرسد
      - با --symbol X: جستجوی X و استفاده از آن
      - با --symbol X --ins-code Y: مستقیم
    """
    config = load_config()

    # حالت ۱: نماد و کد داده شده → مستقیم
    if args.symbol and args.ins_code:
        return config

    # حالت ۲: فقط symbol داده شده → جستجو
    if args.symbol and not args.ins_code:
        print(f"\n🔍 جستجوی کد نماد '{args.symbol}' در TSETMC...")
        collector = MarketDataCollector(config)
        results = collector.search_symbol(args.symbol)
        if results:
            args.ins_code = results[0]["code"]
            print(f"✓ کد پیدا شد: {args.ins_code}")
            save_symbol_to_config(config, args.symbol, args.ins_code)
        else:
            print(f"❌ نماد '{args.symbol}' پیدا نشد!")
            sys.exit(1)
        return config

    # حالت ۳: --prompt داده شده → منوی تعاملی
    if args.prompt:
        return interactive_symbol_selection(args, config)

    # حالت ۴ (پیش‌فرض): بدون پرسش، از پیکربندی استفاده کن
    args.symbol = config["test_symbol"]["name"]
    args.ins_code = config["test_symbol"]["ins_code"]
    print(f"📋 نماد از پیکربندی: {args.symbol} (کد: {args.ins_code})")
    print(f"💡 برای تغییر: در مرورگر داشبورد نماد جدید را انتخاب کنید")
    print(f"   یا از پارامتر --symbol استفاده کنید")
    return config


def interactive_symbol_selection(args, config) -> dict:
    """منوی تعاملی انتخاب نماد (فقط با --prompt)."""
    current_symbol = config["test_symbol"]["name"]
    current_code = config["test_symbol"]["ins_code"]

    print("=" * 70)
    print("  انتخاب نماد برای پایش زنده")
    print("=" * 70)
    print(f"\n📝 نماد فعلی: {current_symbol} (کد: {current_code})")
    print()
    print("گزینه‌ها:")
    print(f"  1) استفاده از نماد فعلی ({current_symbol})")
    print(f"  2) وارد کردن نماد جدید")
    print(f"  3) خروج")
    print()

    while True:
        try:
            choice = input("انتخاب شما (1/2/3): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nخروج...")
            sys.exit(0)

        if choice == "1":
            args.symbol = current_symbol
            args.ins_code = current_code
            print(f"\n✓ نماد: {args.symbol}")
            break
        elif choice == "2":
            try:
                new_symbol = input("نام نماد جدید (مثلا ریتون، دابور، فملی): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nخروج...")
                sys.exit(0)
            if not new_symbol:
                print("⚠ نام نماد خالی است!")
                continue

            print(f"\n🔍 جستجوی '{new_symbol}' در TSETMC...")
            collector = MarketDataCollector(config)
            results = collector.search_symbol(new_symbol)

            if not results:
                print(f"❌ نماد '{new_symbol}' پیدا نشد!")
                print("   ممکن است نام اشتباه باشد یا اینترنت قطع باشد.")
                continue

            print(f"\n✓ {len(results)} نتیجه پیدا شد:")
            for i, r in enumerate(results[:5], 1):
                print(f"  {i}) کد: {r.get('code', 'N/A')}")
                print(f"     نام فارسی: {r.get('name_fa', 'N/A')}")
                print(f"     نام انگلیسی: {r.get('name_en', 'N/A')}")
                print(f"     ISIN: {r.get('isin', 'N/A')}")
                print()

            try:
                sel = input(f"کدام را انتخاب می‌کنید؟ (1-{min(5, len(results))}): ").strip()
                sel_idx = int(sel) - 1
                if 0 <= sel_idx < len(results):
                    selected = results[sel_idx]
                    args.symbol = new_symbol
                    args.ins_code = selected["code"]
                    print(f"\n✓ نماد انتخاب شده: {new_symbol} (کد: {args.ins_code})")
                    save_symbol_to_config(config, new_symbol, args.ins_code)
                    break
                else:
                    print("⚠ انتخاب نامعتبر!")
            except (ValueError, EOFError, KeyboardInterrupt):
                print("⚠ ورودی نامعتبر!")
        elif choice == "3":
            print("خروج...")
            sys.exit(0)
        else:
            print("⚠ انتخاب نامعتبر! 1، 2 یا 3 وارد کنید.")

    return config


def save_symbol_to_config(config: dict, symbol: str, ins_code: str):
    """ذخیره نماد انتخاب‌شده در فایل پیکربندی."""
    try:
        config["test_symbol"]["name"] = symbol
        config["test_symbol"]["ticker"] = symbol
        config["test_symbol"]["ins_code"] = str(ins_code)
        # اگر قیمت پایه تغییر نکرده، همان بماند
        cfg_path = ROOT / "config" / "warning_thresholds.json"
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"✓ نماد '{symbol}' در پیکربندی ذخیره شد (برای دفعات بعد)")
    except Exception as e:
        print(f"⚠ خطا در ذخیره پیکربندی: {e}")


def load_price_range(args, config: dict, collector, storage):
    """
    محاسبه، ذخیره و بارگذاری پارامترهای ثابت روز — یک بار در ابتدای اجرا.

    مراحل:
      ۱. دسته نماد از config/symbol_categories.json (نگاشت دستی) خوانده می‌شود
      ۲. درصد مجاز از config/tse_range_rules.json خوانده می‌شود
      ۳. yesterday_price از اولین فراخوانی API دریافت می‌شود
      ۴. min/max_allowed_price = yesterday_price × (1 ± pct/100) محاسبه می‌شود
      ۵. مقادیر در جدول daily_params بانک ذخیره می‌شوند (یک ردیف در روز)
      ۶. مقادیر ثابت در config['test_symbol']['fixed_price_range'] تزریق می‌شوند

    این مقادیر در طول روز ثابت می‌مانند و در هر رکورد snapshot تکرار نمی‌شوند.
    data_collector در هر نمونه فقط fixed_price_range را از پیکربندی می‌خواند.

    fallback: اگر دسته نماد در symbol_categories.json نبود، هشدار می‌دهد و
    از limit_percent پیکربندی استفاده می‌کند.
    """
    symbol = args.symbol or config.get("test_symbol", {}).get("name", "")
    ins_code = args.ins_code or config.get("test_symbol", {}).get("ins_code", "")
    config_dir = ROOT / "config"
    if not symbol:
        return

    print("─" * 60)
    print("  محاسبه پارامترهای ثابت روز (یک بار، ثابت برای کل جلسه)")
    print("─" * 60)

    # ── ۱. دسته نماد از symbol_categories.json (دستی) ──
    category = get_symbol_category(symbol, config_dir)
    if not category:
        print(f"  ⚠ نماد «{symbol}» در config/symbol_categories.json یافت نشد.")
        print(f"    لطفاً دسته این نماد را در فایل اضافه کنید.")
        print(f"    دسته‌های موجود در tse_range_rules.json:")
        for r in load_range_rules(config_dir):
            print(f"      • {r['cat']} ({r['pct']}%)")
        print(f"  ⚠ از limit_percent پیکربندی استفاده می‌شود.")
        print("─" * 60)
        return

    # ── ۲. درصد مجاز از tse_range_rules.json ──
    pct = get_category_percent(category, config_dir)
    if pct is None:
        print(f"  ⚠ دسته «{category}» در tse_range_rules.json یافت نشد.")
        print(f"  ⚠ از limit_percent پیکربندی استفاده می‌شود.")
        print("─" * 60)
        return

    print(f"  ✓ نماد: {symbol}")
    print(f"  ✓ دسته (از symbol_categories.json): {category}")
    print(f"  ✓ درصد مجاز (از tse_range_rules.json): {pct}%")

    # ── ۳. دریافت yesterday_price از TSETMC ──
    yesterday_price = 0.0
    if ins_code:
        inst = collector.fetch_intraday(str(ins_code))
        if inst:
            yesterday_price = float(inst.get("yesterday_price", 0) or 0)
    if yesterday_price <= 0:
        base = float(config.get("test_symbol", {}).get("base_price", 0) or 0)
        if base > 0:
            yesterday_price = base
            print(f"  ⚠ yesterday_price از API دریافت نشد — استفاده از base_price: {yesterday_price:,.0f}")
        else:
            print("  [!] قیمت دیروز دریافت نشد — محاسبه کف/سقف ممکن نیست.")
            print("─" * 60)
            return
    else:
        print(f"  ✓ قیمت دیروز (yesterday_price): {yesterday_price:,.0f}")

    # ── ۴. محاسبه min/max ──
    params = compute_daily_params(symbol, yesterday_price, config_dir)
    if not params:
        print("  [!] محاسبه پارامترها ناموفق بود.")
        print("─" * 60)
        return

    print(f"  ✓ کف مجاز: {params['min_allowed_price']:,.0f}")
    print(f"  ✓ سقف مجاز: {params['max_allowed_price']:,.0f}")

    # ── ۵. ذخیره در جدول daily_params (یک ردیف در روز) ──
    date_jalali = to_jalali(date.today())
    daily_record = {
        "date_jalali": date_jalali,
        "symbol": symbol,
        "ins_code": str(ins_code),
        "category": params["category"],
        "range_percent": params["range_percent"],
        "yesterday_price": params["yesterday_price"],
        "first_price": None,  # بعداً از اولین معامله پر می‌شود
        "min_allowed_price": params["min_allowed_price"],
        "max_allowed_price": params["max_allowed_price"],
        "computed_at": datetime.now().isoformat(),
    }
    storage.upsert_daily_params(daily_record)
    print(f"  ✓ در جدول daily_params بانک ذخیره شد (یک ردیف برای امروز).")

    # ── ۶. تزریق مقادیر ثابت در پیکربندی نماد ──
    cfg_sym = config.setdefault("test_symbol", {})
    cfg_sym["fixed_price_range"] = {
        "yesterday_price": params["yesterday_price"],
        "min_allowed_price": params["min_allowed_price"],
        "max_allowed_price": params["max_allowed_price"],
        "range_percent": params["range_percent"],
        "category": params["category"],
    }
    cfg_sym["limit_percent"] = params["range_percent"]
    cfg_sym["base_price"] = params["yesterday_price"]

    print("─" * 60)


def main():
    args = parse_args()
    config = load_config_with_prompt(args)

    # ----- حل پارامترهای زمان‌بندی (CLI > پیکربندی > مقدار پیش‌فرض) -----
    sampling = config.get("sampling", {})
    interval = args.interval if args.interval else int(sampling.get("interval_seconds", 60))
    analysis_interval = (args.analysis_interval if args.analysis_interval
                         else int(sampling.get("analysis_interval_seconds", 60)))
    # پوشش کامل جلسه 08:45 تا 12:30 (۱۳۵۰۰ ثانیه) + حاشیه پیش‌گشایش
    max_samples = args.max_samples if args.max_samples else int(13500 / interval) + 15

    print()
    print("=" * 70)
    print(f"  TSE Early Warning Engine - حالت زنده (نسخه ۱.۲)")
    print(f"  نماد: {args.symbol}  |  کد: {args.ins_code}")
    print(f"  فاصله نمونه‌برداری: {interval} ثانیه")
    print(f"  گام تحلیل موتورها: {analysis_interval} ثانیه")
    print(f"  حداکثر نمونه: {max_samples}")
    print(f"  پایگاه داده: {args.db}")
    print("=" * 70)

    collector = MarketDataCollector(config)
    db_path = ROOT / args.db
    storage = MarketDataStorage(db_path)

    # ----- تشخیص نوع بازار و ساعت‌های معاملات نماد -----
    market_info = detect_market(collector, str(args.ins_code))
    if market_info.get("ok"):
        mh = market_info["trading_hours"]
        print(f"  بازار: {market_info['market_label']}")
        print(f"  نوع سازمت: {market_info['instrument_type']}")
        print(f"  ساعت معاملات: پیش‌گشایش {mh['pre_open'][0]}-{mh['pre_open'][1]} | "
              f"پیوسته {mh['continuous'][0]}-{mh['continuous'][1]}")
        print(f"  روزها: {market_info['days']}")
        print("=" * 70)
    else:
        print(f"  ⚠ تشخیص بازار ناموفق: {market_info.get('error', 'نامشخص')}")
        print("=" * 70)
    # Phase 2: نرمال‌سازی تطبیقی (اگر adaptive.enabled=true در کانفیگ)
    normalizer = AdaptiveNormalizer(storage, config)

    # ----- محاسبه پارامترهای ثابت روز (یک بار، ثابت برای کل جلسه) -----
    # ابتدا collector و storage ساخته می‌شوند چون load_price_range از collector
    # برای دریافت yesterday_price و از storage برای ذخیره در daily_params
    # استفاده می‌کند. مقادیر محاسبه‌شده در config تزریق می‌شود و چون collector
    # به همان reference نگه‌داری می‌کند، در تمام نمونه‌های بعدی از
    # fixed_price_range ثابت استفاده می‌کند.
    load_price_range(args, config, collector, storage)

    validator = DataValidator()
    sp_detector = SellPressureDetector(config, normalizer=normalizer)
    buy_detector = BuyPressureDetector(config, normalizer=normalizer)
    alert_engine = AlertEngine(config)
    speed_engine = SpeedIndicatorEngine(config)

    snapshots = []            # همه نمونه‌ها (هر interval ثانیه) - برای بانک و CSV
    engine_snapshots = []     # نمونه‌های لحظه اجرای موتورها (هر analysis_interval ثانیه)
    engine_prev = None        # نمونه قبلی از دید موتورها (گام تحلیل)
    engine_history = []       # تاریخچه پیوسته برای موتور جمع‌آوری و شاخص‌های سرعتی
    last_engine_eval = 0.0
    sp_results = []
    buy_results = []
    combined_states = []
    all_trades = []

    # توقف نرم: Ctrl+C (SIGINT) یا SIGTERM از run_multi → flag تنظیم می‌شود
    # تا حلقه در ابتدای تکرار بعدی break کند و گزارش Excel (گام ۷-۸) تولید شود.
    # بدون این، Ctrl+C یا kill کردن پروسه‌ی run_live از run_multi باعث می‌شد
    # گزارش Excel هرگز تولید نشود.
    _stop = False
    def _on_stop(signum, frame):
        nonlocal _stop
        _stop = True
    signal.signal(signal.SIGINT, _on_stop)
    signal.signal(signal.SIGTERM, _on_stop)

    for i in range(max_samples):
        if _stop:
            print("\n  ⏹ توقف دریافت شد — در حال تولید خروجی‌ها...")
            break
        now = tehran_now()  # زمان تهران (UTC+3:30) — نه زمان سیستم
        print(f"\n[نمونه {i+1}/{max_samples}] {now.strftime('%H:%M:%S')}")

        # ۰) بررسی ساعت معاملات — خارج از جلسه، fetch نکن (صرفه‌جویی در API)
        if market_info.get("ok"):
            now_hhmm = now.strftime("%H:%M")
            in_session, status = in_trading_window(market_info["trading_hours"], now_hhmm)
            if not in_session:
                print(f"  ⏸ خارج از جلسه ({status}) — در انتظار باز شدن بازار")
                time.sleep(interval)
                continue
            else:
                print(f"  ✓ {status}")

        # ۱) دریافت داده + معاملات
        prev_snap = snapshots[-1] if snapshots else None
        snap, trades = collector.collect(
            args.symbol, args.ins_code,
            prev_snap=prev_snap,
            fetch_trades=True,
        )
        if snap is None:
            print("  ⚠ خطا در دریافت داده - تلاش مجدد در دوره بعد")
            time.sleep(interval)
            continue

        # ۲) اعتبارسنجی
        q = validator.validate(snap)
        print(f"  فاز: {snap.market_phase}  |  کمال: {q.completeness_pct:.0f}%  |  معتبر: {q.is_valid}")

        # ۲.۵) اعتبارسنجی رنج قیمت — bid/ask باید در [min, max] باشند
        range_ok, out_of_range = snap.validate_bid_ask_range()
        if not range_ok:
            print(f"  ⚠ قیمت‌های bid/ask خارج از رنج مجاز — ذخیره در بانک رد شد")
            for o in out_of_range:
                print(f"    {o['side']}_{o['level']}: {o['price']:,.0f}  (مجاز: {o['min']:,.0f}–{o['max']:,.0f})")
            snapshots.append(snap)  # در حافظه نگه می‌داریم برای موتورها
            time.sleep(interval)
            continue

        # ۳) ذخیره در SQLite (همه نمونه‌ها ذخیره می‌شوند - داشبورد از همین می‌خواند)
        snap_id = storage.insert_snapshot(snap)
        if trades:
            storage.insert_trades(trades, symbol=args.symbol,
                                   snapshot_time=snap.tehran_time)
        snap.snapshot_id = snap_id

        # ۴) اجرای موتورها - فقط در فاز پیوسته و با گام تحلیل
        # تابلو هر interval ثانیه جمع می‌شود ولی موتورهای تحلیلی با گام
        # analysis_interval (پیش‌فرض ۶۰ ثانیه) اجرا می‌شوند تا کالیبراسیون
        # آستانه‌ها (که برای نمونه‌های ۶۰ ثانیه‌ای تنظیم شده) حفظ شود.
        if snap.market_phase == MarketPhase.CONTINUOUS.value:
            now_ts = time.time()
            due = (last_engine_eval == 0.0 or
                   (now_ts - last_engine_eval) >= analysis_interval)
            if due:
                sp = sp_detector.evaluate(snap, engine_prev)
                buy = buy_detector.evaluate(snap, engine_prev, engine_history)
                # Phase 2: ثبت raw_valueها برای نرمال‌سازی تطبیقی آینده
                normalizer.record_factors(snap.symbol, "sell", sp.factors,
                                          date_jalali=snap.date_jalali)
                normalizer.record_factors(snap.symbol, "buy", buy.factors,
                                          date_jalali=snap.date_jalali)
                # شاخص‌های سرعتی نردبان (فقط برای نمایش؛ در v2 جزو alert_engine نیست)
                speed = speed_engine.compute(snap, engine_history)
                combined = alert_engine.evaluate(sp, buy)

                engine_prev = snap
                engine_history.append(snap)
                engine_history = engine_history[-36:]   # buy_support به ۳۶ نمونه نیاز دارد
                engine_snapshots.append(snap)
                last_engine_eval = now_ts

                sp_results.append(sp)
                buy_results.append(buy)
                combined_states.append(combined)

                print(f"  Sell Pressure : {sp.total_score:5.1f}/100  - {sp.level}")
                print(f"  Buy Pressure  : {buy.total_score:5.1f}/100  - {buy.level}")
                if speed.speed_pressure_score is not None:
                    print(f"  Speed Pressure: {speed.speed_pressure_score:5.1f}/100  "
                          f"({speed.data_status})")
                else:
                    print(f"  Speed Pressure:     —/100  ({speed.data_status})")
                print(f"  طبقه‌بندی    : {combined.classification}")
                print(f"  وضعیت ترکیب  : {combined.combination_label}")
                if combined.alert and combined.alert.level.value != "بدون هشدار":
                    print(f"  🚨 {combined.alert.level.value}")
                    print(f"     {combined.alert.message}")

        snapshots.append(snap)
        all_trades.extend(trades)

        # ۵) انتظار تا نمونه بعدی
        if i < max_samples - 1:
            time.sleep(interval)

    # ۶) ثبت metadata
    if snapshots:
        first = snapshots[0]
        last = snapshots[-1]
        phases = {}
        for s in snapshots:
            phases[s.market_phase] = phases.get(s.market_phase, 0) + 1
        phase_summary = "؛ ".join(f"{p}: {n}" for p, n in phases.items())
        storage.insert_metadata({
            "date_jalali": first.date_jalali or datetime.now().strftime("%Y-%m-%d"),
            "symbol": args.symbol,
            "ins_code": args.ins_code,
            "open_time": first.tehran_time,
            "close_time": last.tehran_time,
            "last_update": last.tehran_time,
            "price_unit": "تومان",
            "volume_unit": "سهم",
            "data_source": "TSETMC Live",
            "market_phase_summary": phase_summary,
            "total_snapshots": len(snapshots),
            "total_trades": len(all_trades),
            "notes": "جلسه زنده",
        })

    # ۷) خروجی CSV
    storage.export_snapshots_csv(
        ROOT / "data" / f"snapshots_live_{args.symbol}.csv",
        symbol=args.symbol,
    )
    storage.export_trades_csv(
        ROOT / "data" / f"trades_live_{args.symbol}.csv",
        symbol=args.symbol,
    )

    # ۸) تولید گزارش Excel نهایی
    # داده‌ها از بانک بازخوانی می‌شوند تا اکسل همه‌ی نمونه‌های امروز را شامل شود،
    # حتی اگر توسط داشبورد adaptive یا session قبلی run_live جمع‌آوری شده باشند.
    # (in-memory snapshots فقط نمونه‌های همین session را دارد؛ بانک همه را دارد.)
    print("\n" + "=" * 70)
    print("  تولید گزارش Excel نهایی...")
    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # بازخوانی همه‌ی snapshot‌ها و معاملات از بانک
    db_rows = storage.get_snapshots_for_symbol(args.symbol)
    db_snaps = [MarketSnapshot.from_flat_dict(r) for r in db_rows]
    db_trade_rows = storage.get_trades_for_symbol(args.symbol)
    db_trades = [
        Trade(
            trade_time=t.get("trade_time", ""),
            trade_price=float(t.get("trade_price") or 0),
            trade_volume=int(t.get("trade_volume") or 0),
            trade_id=t.get("trade_id"),
            aggressor_side=t.get("aggressor_side"),
        )
        for t in db_trade_rows
    ]

    if db_snaps:
        print(f"  بازخوانی از بانک: {len(db_snaps)} نمونه، {len(db_trades)} معامله")
        # اجرای مجدد موتورها روی داده‌ی بانک (detectorهای تازه برای reset حالت)
        replay_sp = SellPressureDetector(config, normalizer=normalizer)
        replay_buy = BuyPressureDetector(config, normalizer=normalizer)
        replay_alert = AlertEngine(config)
        excel_sp, excel_buy, excel_combined = [], [], []
        prev = None
        hist = []
        for snap in db_snaps:
            sp = replay_sp.evaluate(snap, prev)
            buy = replay_buy.evaluate(snap, prev, hist)
            excel_sp.append(sp)
            excel_buy.append(buy)
            excel_combined.append(replay_alert.evaluate(sp, buy))
            prev = snap
            hist.append(snap)
        excel_snapshots = db_snaps
        excel_alert = replay_alert
        excel_trades = db_trades
    else:
        # fallback: داده‌ی in-memory (بانک خالی)
        print(f"  بانک خالی — استفاده از داده‌ی in-memory ({len(snapshots)} نمونه)")
        excel_snapshots = engine_snapshots if engine_snapshots else snapshots
        excel_sp = sp_results
        excel_buy = buy_results
        excel_combined = combined_states
        excel_alert = alert_engine
        excel_trades = all_trades

    gen = ExcelReportGenerator(config)
    gen.generate(
        symbol=args.symbol,
        snapshots=excel_snapshots,
        sp_results=excel_sp,
        acc_results=excel_buy,   # buy_results → acc_results (نام پارامتر در ExcelReport)
        combined_states=excel_combined,
        alert_events=excel_alert.get_all_events(),
        output_path=out_path,
        trades=excel_trades,
    )
    print(f"  گزارش: {out_path}")
    print(f"  پایگاه داده: {db_path}")
    storage.close()
    print("=" * 70)


if __name__ == "__main__":
    main()
