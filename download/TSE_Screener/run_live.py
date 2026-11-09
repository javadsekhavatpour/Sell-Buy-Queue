"""
run_live.py
اجرای ماژول هشدار زودهنگام با داده واقعی TSETMC در بازار زنده.

نحوه اجرا (Windows 10):
    cd C:\\TSE_Screener
    python run_live.py --symbol دابور --ins-code 4674107287748763521

این اسکریپت هر ۶۰ ثانیه یک نمونه از تابلو دریافت می‌کند و موتورها را
به‌صورت زنده اجرا می‌کند. هشدارها در کنسول چاپ می‌شوند و در پایان
یک گزارش Excel کامل تولید می‌شود.

نکته: در بازار بسته (یعنی قبل از ۰۹:۰۰ یا بعد از ۱۲:۳۰ به وقت تهران)
داده‌ها ممکن است همان داده آخرین روز معاملاتی باشند.
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
)
from early_warning.data_collector import save_snapshot_json


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_args():
    p = argparse.ArgumentParser(description="TSE Early Warning - Live Mode")
    p.add_argument("--symbol", default="دابور", help="نام نماد")
    p.add_argument("--ins-code", default="4674107287748763521", help="کد TSETMC")
    p.add_argument("--interval", type=int, default=60, help="فاصله نمونه‌برداری (ثانیه)")
    p.add_argument("--max-samples", type=int, default=210, help="حداکثر تعداد نمونه")
    p.add_argument("--output", default="reports/early_warning_report_live.xlsx")
    return p.parse_args()


def main():
    args = parse_args()
    config = load_config()

    print("=" * 70)
    print(f"  TSE Early Warning Engine - حالت زنده")
    print(f"  نماد: {args.symbol}  |  کد: {args.ins_code}")
    print(f"  فاصله نمونه‌برداری: {args.interval} ثانیه")
    print("=" * 70)

    collector = MarketDataCollector(config)
    validator = DataValidator()
    sp_detector = SellPressureDetector(config)
    acc_detector = SmartAccumulationDetector(config)
    alert_engine = AlertEngine(config)

    snapshots = []
    sp_results = []
    acc_results = []
    combined_states = []

    raw_dir = ROOT / "data" / "raw_snapshots"

    for i in range(args.max_samples):
        now = datetime.now()
        print(f"\n[نمونه {i+1}/{args.max_samples}] {now.strftime('%H:%M:%S')}")

        # ۱) دریافت داده
        snap = collector.collect(args.symbol, args.ins_code)
        if snap is None:
            print("  ⚠ خطا در دریافت داده - تلاش مجدد در دوره بعد")
            time.sleep(args.interval)
            continue

        # ۲) ذخیره خام
        save_snapshot_json(snap, raw_dir)

        # ۳) اعتبارسنجی
        q = validator.validate(snap)
        print(f"  کمال داده: {q.completeness_pct:.0f}%  |  معتبر: {q.is_valid}")
        if not q.is_valid:
            print(f"  ⚠ فیلدهای حیاتی مفقود: {q.missing_critical_fields}")

        # ۴) اجرای موتورها
        prev = snapshots[-1] if snapshots else None
        history = snapshots[-5:] if snapshots else []
        sp = sp_detector.evaluate(snap, prev)
        acc = acc_detector.evaluate(snap, prev, history)
        combined = alert_engine.evaluate(sp, acc)

        snapshots.append(snap)
        sp_results.append(sp)
        acc_results.append(acc)
        combined_states.append(combined)

        # ۵) چاپ وضعیت لحظه‌ای
        print(f"  Sell Pressure : {sp.total_score:5.1f}/100  - {sp.level}")
        print(f"  Accumulation  : {acc.total_score:5.1f}/100  - {acc.level}")
        print(f"  وضعیت ترکیب  : {combined.combination_label}")
        if combined.alert:
            level = combined.alert.level.value
            print(f"  🚨 {level}")
            print(f"     {combined.alert.message}")

        # ۶) انتظار تا نمونه بعدی
        if i < args.max_samples - 1:
            time.sleep(args.interval)

    # ۷) تولید گزارش Excel نهایی
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
    )
    print(f"  گزارش: {out_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
