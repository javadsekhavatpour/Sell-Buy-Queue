"""
run_multi.py — اجرای همزمان جمع‌آوری داده برای چند نماد (تنها فایل جمع‌آوری).

می‌خواند config/symbols.json، برای هر نماد یک subprocess از
run_live.py (worker داخلی — مستقیم اجرا نمی‌شود) راه‌اندازی می‌کند. هر collector:
  - نماد و کد خود را از آرگومان می‌گیرد
  - نوع بازار و ساعت معاملات را به‌صورت خودکار تشخیص می‌دهد (market_detector)
  - خارج از جلسه fetch نمی‌کند (صرفه‌جویی در API TSETMC)
  - در DB جداگانه می‌نویسد (data/multi/{symbol}.sqlite) تا تداخل نباشد

استفاده:
  python run_multi.py
  python run_multi.py --symbols سرود,دابور     # فقط برخی نمادها
  python run_multi.py --interval 30             # فاصله نمونه‌برداری

سپس داشبورد را در ترمینال جدا اجرا کنید (یک سرور، سه حالت):
  python web_dashboard_adaptive.py --port 8052
  سپس: http://localhost:8052/live  یا  /db  یا  /sim
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
SYMBOLS_PATH = ROOT / "config" / "symbols.json"


def load_symbols(selected: list[str] | None = None) -> list[dict]:
    """بارگذاری لیست نمادها از config/symbols.json."""
    if not SYMBOLS_PATH.exists():
        print(f"\u274c {SYMBOLS_PATH} پیدا نشد.")
        print("   ابتدا اجرا کنید: python scripts/detect_4_symbols.py")
        sys.exit(1)
    data = json.loads(SYMBOLS_PATH.read_text(encoding="utf-8"))
    symbols = data.get("symbols", [])
    if selected:
        symbols = [s for s in symbols if s.get("name") in selected]
    return symbols


def main():
    ap = argparse.ArgumentParser(
        description="\u062c\u0645\u0639\u200c\u0622\u0648\u0631\u06cc \u0647\u0645\u0632\u0645\u0627\u0646 \u0686\u0646\u062f \u0646\u0645\u0627\u062f"
    )
    ap.add_argument("--symbols", default=None,
                    help="\u0644\u06cc\u0633\u062a \u0646\u0645\u0627\u062f\u0647\u0627 \u0628\u0627 \u06a9\u0627\u0645\u0627 (مثلا سرود,دابور,ریتون)")
    ap.add_argument("--interval", type=int, default=None,
                    help="\u0641\u0627\u0635\u0644\u0647 \u0646\u0645\u0648\u0646\u0647\u200c\u0628\u0631\u062f\u0627\u0631\u06cc (ثانیه)")
    ap.add_argument("--analysis-interval", type=int, default=None,
                    help="\u06af\u0627\u0645 \u062a\u062d\u0644\u06cc\u0644 \u0645\u0648\u062a\u0648\u0631\u0647\u0627 (ثانیه)")
    ap.add_argument("--max-samples", type=int, default=None,
                    help="\u062d\u062f\u0627\u06a9\u062b\u0631 \u0646\u0645\u0648\u0646\u0647\u200c\u0647\u0627")
    args = ap.parse_args()

    selected = args.symbols.split(",") if args.symbols else None
    symbols = load_symbols(selected)
    if not symbols:
        print("\u274c \u0646\u0645\u0627\u062f\u06cc \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f.")
        sys.exit(1)

    # پوشه DBها
    multi_dir = ROOT / "data" / "multi"
    multi_dir.mkdir(parents=True, exist_ok=True)

    print()
    print("=" * 78)
    print("  \u062c\u0645\u0639\u200c\u0622\u0648\u0631\u06cc \u0647\u0645\u0632\u0645\u0627\u0646 \u0686\u0646\u062f \u0646\u0645\u0627\u062f — TSE Early Warning")
    print("=" * 78)
    print(f"  \u062a\u0639\u062f\u0627\u062f \u0646\u0645\u0627\u062f\u0647\u0627: {len(symbols)}")
    if args.interval:
        print(f"  \u0641\u0627\u0635\u0644\u0647 \u0646\u0645\u0648\u0646\u0647\u200c\u0628\u0631\u062f\u0627\u0631\u06cc: {args.interval} \u062b\u0627\u0646\u06cc\u0647")
    print()
    # جدول خلاصه
    hdr = f"  {'\u0646\u0645\u0627\u062f':<8} {'\u0628\u0627\u0632\u0627\u0631':<20} {'\u0633\u0627\u0639\u062a \u067e\u06cc\u0648\u0633\u062a\u0647':<16} {'DB':<32}"
    print(hdr)
    print("  " + "-" * 76)

    procs = []
    for s in symbols:
        if not s.get("ok", True) and "error" in s:
            print(f"  {s.get('name','?'):<8} \u274c {s['error'][:40]}")
            continue
        name = s["name"]
        th = s["trading_hours"]["continuous"]
        db_rel = f"data/multi/{name}.sqlite"
        db_path = ROOT / db_rel
        print(f"  {name:<8} {s['market_label']:<20} {th[0]}-{th[1]:<11} {db_rel:<32}")

        cmd = [
            sys.executable, str(ROOT / "run_live.py"),
            "--symbol", name,
            "--ins-code", str(s["ins_code"]),
            "--db", db_rel,
            "--output", f"reports/early_warning_report_live_{name}.xlsx",
        ]
        if args.interval:
            cmd += ["--interval", str(args.interval)]
        if args.analysis_interval:
            cmd += ["--analysis-interval", str(args.analysis_interval)]
        if args.max_samples:
            cmd += ["--max-samples", str(args.max_samples)]

        p = subprocess.Popen(cmd, cwd=str(ROOT))
        procs.append((name, p))

    if not procs:
        print("\n\u274c \u0647\u06cc\u0686 collector \u0631\u0627\u0647\u200c\u0627\u0646\u062f\u0627\u0632\u06cc \u0646\u0634\u062f.")
        sys.exit(1)

    print()
    print(f"  {len(procs)} collector راه‌اندازی شد.")
    print("  برای توقف: Ctrl+C")
    print("  برای داشبورد (ترمینال جدا — یک سرور، سه حالت):")
    print("    python web_dashboard_adaptive.py --port 8052")
    print("    سپس: http://localhost:8052/  (نمایه) → /live  /db  /sim")
    print("=" * 78)

    # مدیریت سیگنال برای توقف تمیز
    def stop_all(*_):
        print("\n\u062a\u0648\u0642\u0641 \u062a\u0645\u0627\u0645 collectors...")
        for name, p in procs:
            try:
                p.terminate()
                print(f"  \u2717 {name} \u062a\u0648\u0642\u0641 \u0634\u062f")
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    # انتظار برای پایان همه
    for name, p in procs:
        try:
            p.wait()
        except KeyboardInterrupt:
            stop_all()


if __name__ == "__main__":
    main()
