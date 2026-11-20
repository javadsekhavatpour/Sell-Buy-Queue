"""request_report.py — درخواست ریپورت Excel فوری از یک نماد در طول جلسه.

وقتی run_multi.py در حال جمع‌آوری است، اجرای این اسکریپت یک فایل trigger می‌سازد.
workerِ run_live.py (همان نماد) در تکرار بعدیِ حلقه، ریپورت Excel را از بانک فعلی
می‌سازد و فایل trigger را حذف می‌کند.

استفاده:
    python request_report.py اهرم
    python request_report.py --all          # برای همهٔ نمادهای config/symbols.json
"""
from __future__ import annotations
import sys
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).parent
TRIG = ROOT / "triggers"


def _symbols_from_config() -> list[str]:
    cfg = ROOT / "config" / "symbols.json"
    if not cfg.exists():
        return []
    return [s["name"] for s in json.loads(cfg.read_text(encoding="utf-8")).get("symbols", [])]


def trigger(symbol: str) -> Path:
    TRIG.mkdir(parents=True, exist_ok=True)
    p = TRIG / f"report_{symbol}"
    p.touch()
    return p


def main():
    ap = argparse.ArgumentParser(description="درخواست ریپورت فوری در طول جلسه")
    ap.add_argument("symbol", nargs="?", help="نام نماد (مثلاً اهرم)")
    ap.add_argument("--all", action="store_true", help="درخواست برای همهٔ نمادهای config")
    args = ap.parse_args()

    if args.all:
        syms = _symbols_from_config()
        if not syms:
            print("هیچ نمادی در config/symbols.json یافت نشد.")
            sys.exit(1)
        for s in syms:
            p = trigger(s)
            print(f"✓ trigger ساخته شد: {p}  (worker در تکرار بعدی ریپورت می‌سازد)")
        return

    if not args.symbol:
        ap.error("نماد را مشخص کنید یا از --all استفاده کنید.")

    p = trigger(args.symbol)
    print(f"✓ trigger ساخته شد: {p}")
    print("  workerِ run_live.py در تکرار بعدیِ حلقه ریپورت Excel از بانک فعلی می‌سازد")
    print("  و فایل trigger را حذف می‌کند. خروجی: reports/..._snapshot.xlsx")


if __name__ == "__main__":
    main()
