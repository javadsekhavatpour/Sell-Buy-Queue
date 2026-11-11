"""
run_live.py
اجرای ماژول هشدار زودهنگام با داده واقعی TSETMC در بازار زنده.

این نسخه به جای تولید گزارش در پایان، داده‌ها را زنده در SQLite
ذخیره می‌کند و هر نمونه را هم‌زمان تحلیل می‌کند.

نحوه اجرا (Windows 10):
    cd C:\\TSE_Screener
    python run_live.py --symbol دابور --ins-code 4674107287748763521

این اسکریپت هر ۶۰ ثانیه یک نمونه از تابلو دریافت می‌کند، در SQLite
ذخیره می‌کند و موتورها را به‌صورت زنده اجرا می‌کند. هشدارها در کنسول
چاپ می‌شوند و در پایان یک گزارش Excel کامل تولید می‌شود.

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
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import (
    MarketDataCollector,
    DataValidator,
    SellPressureDetector,
    SmartAccumulationDetector,
    AlertEngine,
    ExcelReportGenerator,
    MarketDataStorage,
    MarketPhase,
)


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
    p.add_argument("--interval", type=int, default=60, help="فاصله نمونه‌برداری (ثانیه)")
    p.add_argument("--max-samples", type=int, default=226, help="حداکثر تعداد نمونه")
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


def main():
    args = parse_args()
    config = load_config_with_prompt(args)

    print()
    print("=" * 70)
    print(f"  TSE Early Warning Engine - حالت زنده (نسخه ۱.۱)")
    print(f"  نماد: {args.symbol}  |  کد: {args.ins_code}")
    print(f"  فاصله نمونه‌برداری: {args.interval} ثانیه")
    print(f"  پایگاه داده: {args.db}")
    print("=" * 70)

    collector = MarketDataCollector(config)
    validator = DataValidator()
    sp_detector = SellPressureDetector(config)
    acc_detector = SmartAccumulationDetector(config)
    alert_engine = AlertEngine(config)

    db_path = ROOT / args.db
    storage = MarketDataStorage(db_path)

    snapshots = []
    sp_results = []
    acc_results = []
    combined_states = []
    all_trades = []

    for i in range(args.max_samples):
        now = datetime.now()
        print(f"\n[نمونه {i+1}/{args.max_samples}] {now.strftime('%H:%M:%S')}")

        # ۱) دریافت داده + معاملات
        prev_snap = snapshots[-1] if snapshots else None
        snap, trades = collector.collect(
            args.symbol, args.ins_code,
            prev_snap=prev_snap,
            fetch_trades=True,
        )
        if snap is None:
            print("  ⚠ خطا در دریافت داده - تلاش مجدد در دوره بعد")
            time.sleep(args.interval)
            continue

        # ۲) اعتبارسنجی
        q = validator.validate(snap)
        print(f"  فاز: {snap.market_phase}  |  کمال: {q.completeness_pct:.0f}%  |  معتبر: {q.is_valid}")

        # ۳) ذخیره در SQLite
        snap_id = storage.insert_snapshot(snap)
        if trades:
            storage.insert_trades(trades, symbol=args.symbol,
                                   snapshot_time=snap.tehran_time)
        snap.snapshot_id = snap_id

        # ۴) اجرای موتورها فقط در فاز پیوسته
        if snap.market_phase == MarketPhase.CONTINUOUS.value:
            history = [s for s in snapshots[-5:]
                        if s.market_phase == MarketPhase.CONTINUOUS.value]
            sp = sp_detector.evaluate(snap, prev_snap)
            acc = acc_detector.evaluate(snap, prev_snap, history)
            combined = alert_engine.evaluate(sp, acc)

            sp_results.append(sp)
            acc_results.append(acc)
            combined_states.append(combined)

            print(f"  Sell Pressure : {sp.total_score:5.1f}/100  - {sp.level}")
            print(f"  Accumulation  : {acc.total_score:5.1f}/100  - {acc.level}")
            print(f"  وضعیت ترکیب  : {combined.combination_label}")
            if combined.alert and combined.alert.level.value != "بدون هشدار":
                print(f"  🚨 {combined.alert.level.value}")
                print(f"     {combined.alert.message}")

        snapshots.append(snap)
        all_trades.extend(trades)

        # ۵) انتظار تا نمونه بعدی
        if i < args.max_samples - 1:
            time.sleep(args.interval)

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
    print("\n" + "=" * 70)
    print("  تولید گزارش Excel نهایی...")
    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)

    gen = ExcelReportGenerator(config)
    gen.generate(
        symbol=args.symbol,
        snapshots=snapshots,
        sp_results=sp_results,
        acc_results=acc_results,
        combined_states=combined_states,
        alert_events=alert_engine.get_all_events(),
        output_path=out_path,
        trades=all_trades,
    )
    print(f"  گزارش: {out_path}")
    print(f"  پایگاه داده: {db_path}")
    storage.close()
    print("=" * 70)


if __name__ == "__main__":
    main()
