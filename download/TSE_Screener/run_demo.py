"""
run_demo.py
اجرای نمونه کامل ماژول هشدار زودهنگام با داده‌های شبیه‌سازی شده دابور.

این اسکریپت نشان می‌دهد چگونه دو موتور تحلیلی مستقل (Sell Pressure و
Smart Accumulation) به‌صورت هم‌زمان روی زنجیره‌ای از نمونه‌های زمانی
اجرا می‌شوند و خروجی نهایی به‌صورت گزارش Excel چهار شیت تحویل می‌شود.

نحوه اجرا (Windows 10 + Python 3.10+):
    cd C:\\TSE_Screener
    python run_demo.py

خروجی: reports/early_warning_report.xlsx
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

# اضافه کردن مسیر روت برای import
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import (
    SimulationDataCollector,
    DataValidator,
    SellPressureDetector,
    SmartAccumulationDetector,
    AlertEngine,
    ExcelReportGenerator,
)


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_scenario(scenario: str, num_samples: int = 90) -> dict:
    """اجرای یک سناریوی شبیه‌سازی کامل و بازگشت نتایج."""
    config = load_config()

    # ۱) تولید داده‌های شبیه‌سازی
    print(f"\n[۱] تولید {num_samples} نمونه شبیه‌سازی - سناریو: {scenario}")
    sim = SimulationDataCollector(config, scenario=scenario, seed=42)
    snapshots = sim.generate_series(num_samples=num_samples)
    print(f"     → {len(snapshots)} نمونه تولید شد ({snapshots[0].tehran_time} تا {snapshots[-1].tehran_time})")

    # ۲) اعتبارسنجی داده‌ها
    print("[۲] اعتبارسنجی داده‌ها")
    validator = DataValidator()
    quality_reports = validator.validate_series(snapshots)
    valid_count = sum(1 for q in quality_reports if q.is_valid)
    print(f"     → {valid_count}/{len(quality_reports)} نمونه معتبر")

    # ۳) اجرای دو موتور به‌صورت هم‌زمان روی همه نمونه‌ها
    print("[۳] اجرای موتور فشار فروش و موتور جمع‌آوری")
    sp_detector = SellPressureDetector(config)
    acc_detector = SmartAccumulationDetector(config)
    alert_engine = AlertEngine(config)

    sp_results = []
    acc_results = []
    combined_states = []

    for i, snap in enumerate(snapshots):
        prev_snap = snapshots[i - 1] if i > 0 else None
        history = snapshots[max(0, i - 5):i]   # ۵ نمونه قبلی برای تداوم

        # هر دو موتور از همان داده معتبر استفاده می‌کنند
        sp_res = sp_detector.evaluate(snap, prev_snap)
        acc_res = acc_detector.evaluate(snap, prev_snap, history)
        combined = alert_engine.evaluate(sp_res, acc_res)

        sp_results.append(sp_res)
        acc_results.append(acc_res)
        combined_states.append(combined)

    # ۴) جمع‌آوری هشدارها
    alert_events = alert_engine.get_all_events()
    print(f"     → {len(alert_events)} رویداد هشدار صادر شد")
    for ev in alert_events:
        marker = "🔴" if ev.is_critical else ("🟢" if "سبز" in ev.level.value else ("🟠" if "نارنجی" in ev.level.value else "🟡"))
        print(f"     {marker} [{ev.timestamp}] {ev.level.value}: {ev.title}")

    # ۵) نمایش امتیاز آخرین نمونه
    print("\n[۴] امتیاز آخرین نمونه:")
    last_sp = sp_results[-1]
    last_acc = acc_results[-1]
    print(f"     فشار فروش:   {last_sp.total_score:.1f}/100 - {last_sp.level}")
    print(f"     جمع‌آوری:    {last_acc.total_score:.1f}/100 - {last_acc.level}")
    print(f"     وضعیت ترکیب: {combined_states[-1].combination_label}")

    return {
        "snapshots": snapshots,
        "sp_results": sp_results,
        "acc_results": acc_results,
        "combined_states": combined_states,
        "alert_events": alert_events,
    }


def generate_excel_report(results: dict, output_path: Path):
    """تولید گزارش Excel."""
    config = load_config()
    symbol = config["test_symbol"]["name"]

    print(f"\n[۵] تولید گزارش Excel: {output_path}")
    gen = ExcelReportGenerator(config)
    gen.generate(
        symbol=symbol,
        snapshots=results["snapshots"],
        sp_results=results["sp_results"],
        acc_results=results["acc_results"],
        combined_states=results["combined_states"],
        alert_events=results["alert_events"],
        output_path=output_path,
    )
    print(f"     → گزارش با موفقیت تولید شد: {output_path}")


def main():
    print("=" * 70)
    print("  TSE Early Warning Engine - اجرای نمونه دابور")
    print("=" * 70)

    # سناریوی اصلی: فشار فروش که منتهی به صف فروش می‌شود
    # (این سناریو نشان می‌دهد که موتور پیش از قفل شدن سهم هشدار می‌دهد)
    print("\n>>> سناریوی اصلی: فشار فروش (sell_pressure)")
    results = run_scenario("sell_pressure", num_samples=90)

    # تولید گزارش
    output_path = ROOT / "reports" / "early_warning_report.xlsx"
    generate_excel_report(results, output_path)

    # ----- سناریوی اضافی: جمع‌آوری پنهان در روز منفی -----
    print("\n" + "=" * 70)
    print(">>> سناریوی اضافی: جمع‌آوری در روز منفی (accumulation)")
    print("=" * 70)
    results_acc = run_scenario("accumulation", num_samples=90)

    output_path_acc = ROOT / "reports" / "early_warning_report_accumulation.xlsx"
    generate_excel_report(results_acc, output_path_acc)

    # ----- سناریوی اضافی: ترکیب فشار فروش و جمع‌آوری هم‌زمان -----
    print("\n" + "=" * 70)
    print(">>> سناریوی اضافی: ترکیب فشار فروش و جمع‌آوری هم‌زمان (mixed)")
    print("=" * 70)
    results_mixed = run_scenario("mixed", num_samples=90)

    output_path_mixed = ROOT / "reports" / "early_warning_report_mixed.xlsx"
    generate_excel_report(results_mixed, output_path_mixed)

    print("\n" + "=" * 70)
    print("  اجرای نمونه با موفقیت کامل شد!")
    print(f"  فایل‌های تولید شده در: {ROOT / 'reports'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
