"""
run_demo.py
اجرای نمونه کامل ماژول هشدار زودهنگام با داده‌های شبیه‌سازی شده دابور.

این اسکریپت نشان می‌دهد چگونه دو موتور تحلیلی مستقل (Sell Pressure و
Smart Accumulation) به‌صورت هم‌زمان روی زنجیره‌ای از نمونه‌های زمانی
اجرا می‌شوند و خروجی نهایی به‌صورت گزارش Excel هفت شیت + پایگاه داده
SQLite تحویل می‌شود.

نحوه اجرا (Windows 10 + Python 3.10+):
    cd C:\\TSE_Screener
    python run_demo.py

خروجی‌ها:
  - reports/early_warning_report.xlsx (هفت شیت)
  - data/early_warning.sqlite (پایگاه داده)
  - data/snapshots_export.csv
  - data/trades_export.csv
"""

from __future__ import annotations

import sys
import json
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import (
    SimulationDataCollector,
    DataValidator,
    SellPressureDetector,
    SmartAccumulationDetector,
    AlertEngine,
    ExcelReportGenerator,
    MarketDataStorage,
)


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_scenario(scenario: str, num_samples: int = 226) -> dict:
    """اجرای یک سناریوی شبیه‌سازی کامل و بازگشت نتایج."""
    config = load_config()

    # ۱) تولید داده‌های شبیه‌سازی (شامل پیش‌گشایش + معاملات)
    print(f"\n[۱] تولید {num_samples} نمونه شبیه‌سازی - سناریو: {scenario}")
    sim = SimulationDataCollector(config, scenario=scenario, seed=42)
    snapshots, trades = sim.generate_series(num_samples=num_samples)
    pre_open_count = sum(1 for s in snapshots if s.market_phase == "pre_open")
    continuous_count = sum(1 for s in snapshots if s.market_phase == "continuous")
    print(f"     → {len(snapshots)} نمونه ({pre_open_count} پیش‌گشایش + {continuous_count} پیوسته)")
    print(f"     → {len(trades)} معامله تولید شد")

    # ۲) اعتبارسنجی داده‌ها
    print("[۲] اعتبارسنجی داده‌ها")
    validator = DataValidator()
    quality_reports = validator.validate_series(snapshots)
    valid_count = sum(1 for q in quality_reports if q.is_valid)
    print(f"     → {valid_count}/{len(quality_reports)} نمونه معتبر")

    # ۳) ذخیره در SQLite
    print("[۳] ذخیره در پایگاه داده SQLite")
    db_path = ROOT / "data" / "early_warning.sqlite"
    storage = MarketDataStorage(db_path)
    # پاکسازی داده‌های قبلی همان سناریو (با حفظ داده‌های سایر سناریوها)
    storage.conn.execute(
        "DELETE FROM snapshots WHERE symbol = ? AND ins_code = ?",
        (config["test_symbol"]["name"], config["test_symbol"]["ins_code"])
    )
    # نکته: trades در سناریوهای قبلی ممکن است از همان نماد باشد - برای سادگی همه را پاک می‌کنیم
    storage.conn.execute(
        "DELETE FROM trades WHERE symbol = ?",
        (config["test_symbol"]["name"],)
    )
    storage.conn.commit()

    inserted_snapshots = storage.insert_snapshots_bulk(snapshots)
    inserted_trades = storage.insert_trades(trades, symbol=config["test_symbol"]["name"])

    # ثبت metadata
    first = snapshots[0]
    last = snapshots[-1]
    phases = {}
    for s in snapshots:
        phases[s.market_phase] = phases.get(s.market_phase, 0) + 1
    phase_summary = "؛ ".join(f"{p}: {n} نمونه" for p, n in phases.items())
    storage.insert_metadata({
        "date_jalali": first.date_jalali,
        "symbol": first.symbol,
        "ins_code": first.ins_code,
        "open_time": first.tehran_time,
        "close_time": last.tehran_time,
        "last_update": last.tehran_time,
        "price_unit": "تومان",
        "volume_unit": "سهم",
        "data_source": "Simulation",
        "market_phase_summary": phase_summary,
        "total_snapshots": len(snapshots),
        "total_trades": len(trades),
        "notes": f"سناریوی شبیه‌سازی: {scenario}",
    })
    print(f"     → {inserted_snapshots} نمونه + {inserted_trades} معامله در SQLite ذخیره شد")
    print(f"     → پایگاه داده: {db_path}")

    # خروجی CSV
    csv_snap = storage.export_snapshots_csv(
        ROOT / "data" / f"snapshots_export_{scenario}.csv",
        symbol=config["test_symbol"]["name"],
    )
    csv_trades = storage.export_trades_csv(
        ROOT / "data" / f"trades_export_{scenario}.csv",
        symbol=config["test_symbol"]["name"],
    )
    print(f"     → خروجی CSV: {csv_snap.name} و {csv_trades.name}")

    # ۴) اجرای دو موتور به‌صورت هم‌زمان
    print("[۴] اجرای موتور فشار فروش و موتور جمع‌آوری")
    sp_detector = SellPressureDetector(config)
    acc_detector = SmartAccumulationDetector(config)
    alert_engine = AlertEngine(config)

    sp_results = []
    acc_results = []
    combined_states = []

    for i, snap in enumerate(snapshots):
        prev_snap = snapshots[i - 1] if i > 0 else None
        # فقط نمونه‌های فاز پیوسته را در پایش موتورها در نظر می‌گیریم
        history = [s for s in snapshots[max(0, i - 5):i]
                    if s.market_phase == "continuous"][-5:]
        if snap.market_phase == "pre_open":
            # در پیش‌گشایش موتورها را اجرا نمی‌کنیم ولی خروجی خالی ثبت می‌کنیم
            # برای حفظ ساختار
            history = []
            prev_snap = None

        sp_res = sp_detector.evaluate(snap, prev_snap)
        acc_res = acc_detector.evaluate(snap, prev_snap, history)
        combined = alert_engine.evaluate(sp_res, acc_res)

        sp_results.append(sp_res)
        acc_results.append(acc_res)
        combined_states.append(combined)

    # ۵) جمع‌آوری هشدارها
    alert_events = alert_engine.get_all_events()
    print(f"     → {len(alert_events)} رویداد هشدار صادر شد")
    for ev in alert_events:
        if ev.level.value == "بدون هشدار":
            continue  # رخدادهای بازگشت به عادی را در چاپ نهایی نشان نده
        marker = "🔴" if ev.is_critical else (
            "🟢" if "سبز" in ev.level.value else (
                "🟠" if "نارنجی" in ev.level.value or "هم‌زمان" in ev.level.value else "🟡"
            )
        )
        print(f"     {marker} [{ev.timestamp}] {ev.level.value}: {ev.title}")

    # ۶) نمایش امتیاز آخرین نمونه پیوسته
    continuous_results = [(s, sp, acc, c) for s, sp, acc, c in zip(
        snapshots, sp_results, acc_results, combined_states
    ) if s.market_phase == "continuous"]

    if continuous_results:
        last_sp_snap, last_sp, last_acc, last_combined = continuous_results[-1]
        print(f"\n[۵] امتیاز آخرین نمونه پیوسته (t={last_sp_snap.tehran_time}):")
        print(f"     فشار فروش:   {last_sp.total_score:.1f}/100 - {last_sp.level}")
        print(f"     جمع‌آوری:    {last_acc.total_score:.1f}/100 - {last_acc.level}")
        print(f"     وضعیت ترکیب: {last_combined.combination_label}")
        print(f"     آخرین قیمت: {last_sp_snap.last_price:.0f} | پایانی: {last_sp_snap.close_price:.0f}")
        print(f"     قدرت خریدار: {last_sp_snap.buyer_power:.2f}")
        print(f"     ورود/خروج پول حقیقی: {last_sp_snap.real_money_flow/1e9:+.2f} میلیارد تومان")

    storage.close()

    return {
        "snapshots": snapshots,
        "trades": trades,
        "sp_results": sp_results,
        "acc_results": acc_results,
        "combined_states": combined_states,
        "alert_events": alert_events,
    }


def generate_excel_report(results: dict, output_path: Path, scenario: str):
    """تولید گزارش Excel هفت شیت."""
    config = load_config()
    symbol = config["test_symbol"]["name"]

    print(f"\n[۶] تولید گزارش Excel هفت شیت: {output_path.name}")
    gen = ExcelReportGenerator(config)
    gen.generate(
        symbol=symbol,
        snapshots=results["snapshots"],
        sp_results=results["sp_results"],
        acc_results=results["acc_results"],
        combined_states=results["combined_states"],
        alert_events=results["alert_events"],
        output_path=output_path,
        trades=results["trades"],
    )
    print(f"     → گزارش با موفقیت تولید شد: {output_path}")


def main():
    print("=" * 70)
    print("  TSE Early Warning Engine - اجرای نمونه دابور (نسخه ۱.۱)")
    print("  با پایگاه داده SQLite + معاملات + پیش‌گشایش")
    print("=" * 70)

    # سناریوی اصلی: فشار فروش که منتهی به صف فروش می‌شود
    print("\n>>> سناریوی اصلی: فشار فروش (sell_pressure)")
    results = run_scenario("sell_pressure", num_samples=226)
    generate_excel_report(results,
                          ROOT / "reports" / "early_warning_report.xlsx",
                          "sell_pressure")

    # ----- سناریوی اضافی: جمع‌آوری پنهان در روز منفی -----
    print("\n" + "=" * 70)
    print(">>> سناریوی اضافی: جمع‌آوری در روز منفی (accumulation)")
    print("=" * 70)
    results_acc = run_scenario("accumulation", num_samples=226)
    generate_excel_report(results_acc,
                          ROOT / "reports" / "early_warning_report_accumulation.xlsx",
                          "accumulation")

    # ----- سناریوی اضافی: ترکیب فشار فروش و جمع‌آوری هم‌زمان -----
    print("\n" + "=" * 70)
    print(">>> سناریوی اضافی: ترکیب فشار فروش و جمع‌آوری هم‌زمان (mixed)")
    print("=" * 70)
    results_mixed = run_scenario("mixed", num_samples=226)
    generate_excel_report(results_mixed,
                          ROOT / "reports" / "early_warning_report_mixed.xlsx",
                          "mixed")

    print("\n" + "=" * 70)
    print("  اجرای نمونه با موفقیت کامل شد!")
    print(f"  فایل‌های تولید شده در: {ROOT / 'reports'} و {ROOT / 'data'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
