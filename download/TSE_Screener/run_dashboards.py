"""
run_dashboards.py — راه‌اندازی همزمان داشبوردهای ۴ نماد + صفحه‌ی نمایه.

خروجی:
  - صفحه‌ی نمایه روی پورت ۸۰۵۱ (http://127.0.0.1:8051)
  - داشبورد هر نماد روی پورت ۸۰۵۲ تا ۸۰۵۵

با کلیک روی کارت هر نماد در صفحه‌ی نمایه، داشبورد آن نماد در تب جدید باز می‌شود.

استفاده:
  python run_dashboards.py
  python run_dashboards.py --symbols سرود,ریتون   # فقط برخی نمادها
  python run_dashboards.py --no-browser            # بدون باز کردن مرورگر
"""
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).parent
SYMBOLS_PATH = ROOT / "config" / "symbols.json"
INDEX_PORT = 8051
BASE_PORT = 8052


def main():
    ap = argparse.ArgumentParser(description="راه‌اندازی داشبوردهای چندنمادی")
    ap.add_argument("--symbols", default=None,
                    help="لیست نمادها با کاما (مثلا سرود,ریتون)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true",
                    help="مرورگر را به‌صورت خودکار باز نکن")
    args = ap.parse_args()

    if not SYMBOLS_PATH.exists():
        print(f"\u274c {SYMBOLS_PATH} پیدا نشد.")
        print("   ابتدا: python scripts/detect_4_symbols.py")
        sys.exit(1)

    data = json.loads(SYMBOLS_PATH.read_text(encoding="utf-8"))
    symbols = data.get("symbols", [])
    if args.symbols:
        sel = args.symbols.split(",")
        symbols = [s for s in symbols if s["name"] in sel]
    if not symbols:
        print("\u274c \u0646\u0645\u0627\u062f\u06cc \u067e\u06cc\u062f\u0627 \u0646\u0634\u062f.")
        sys.exit(1)

    procs = []

    print()
    print("=" * 70)
    print("  \u0631\u0627\u0647\u200c\u0627\u0646\u062f\u0627\u0632\u06cc \u062f\u0627\u0634\u0628\u0648\u0631\u062f\u0647\u0627\u06cc \u0686\u0646\u062f\u0646\u0645\u0627\u062f\u06cc — TSE Early Warning")
    print("=" * 70)
    print(f"  \u0635\u0641\u062d\u0647\u0647 \u0646\u0645\u0627\u06cc\u0647: http://{args.host}:{INDEX_PORT}")
    print()
    print(f"  {'\u0646\u0645\u0627\u062f':<8} {'\u0628\u0627\u0632\u0627\u0631':<20} {'\u067e\u0648\u0631\u062a':<6} {'URL':<32}")
    print("  " + "-" * 68)

    # داشبورد هر نماد
    for i, s in enumerate(symbols):
        port = BASE_PORT + i
        db = f"data/multi/{s['name']}.sqlite"
        url = f"http://{args.host}:{port}"
        print(f"  {s['name']:<8} {s['market_label']:<20} {port:<6} {url:<32}")
        cmd = [
            sys.executable, str(ROOT / "web_dashboard_adaptive.py"),
            "--symbol", s["name"],
            "--ins-code", str(s["ins_code"]),
            "--db", db,
            "--port", str(port),
            "--host", args.host,
        ]
        p = subprocess.Popen(cmd, cwd=str(ROOT),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        procs.append((s["name"], p))
        # stagger: هر داشبورد در startup از TSETMC fetch می‌کند؛
        # ۳ ثانیه فاصله تا rate-limit همزمان نشود
        if i < len(symbols) - 1:
            time.sleep(3)

    # صفحه‌ی نمایه
    print(f"  {'\u0646\u0645\u0627\u06cc\u0647':<8} {'—':<20} {INDEX_PORT:<6} http://{args.host}:{INDEX_PORT:<24}")
    idx_cmd = [
        sys.executable, str(ROOT / "dashboard_index.py"),
        "--port", str(INDEX_PORT),
        "--host", args.host,
    ]
    idx_proc = subprocess.Popen(idx_cmd, cwd=str(ROOT),
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    procs.append(("\u0646\u0645\u0627\u06cc\u0647", idx_proc))

    print()
    print(f"  {len(procs)} \u0633\u0631\u0648\u06cc\u0633 \u0631\u0627\u0647\u200c\u0627\u0646\u062f\u0627\u0632\u06cc \u0634\u062f.")
    print(f"  \u0635\u0641\u062d\u0647\u0647 \u0646\u0645\u0627\u06cc\u0647: http://{args.host}:{INDEX_PORT}")
    print("  \u0628\u0631\u0627\u06cc \u062a\u0648\u0642\u0641: Ctrl+C")
    print("=" * 70)

    # باز کردن مرورگر
    if not args.no_browser:
        time.sleep(1.5)
        webbrowser.open(f"http://{args.host}:{INDEX_PORT}")

    # مدیریت توقف تمیز
    def stop_all(*_):
        print("\n\u062a\u0648\u0642\u0641 \u062a\u0645\u0627\u0645 \u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627...")
        for name, p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        print("  \u062a\u0645\u0627\u0645 \u0633\u0631\u0648\u06cc\u0633\u200c\u0647\u0627 \u062a\u0648\u0642\u0641 \u0634\u062f\u0646\u062f.")
        sys.exit(0)

    signal.signal(signal.SIGINT, stop_all)
    signal.signal(signal.SIGTERM, stop_all)

    for name, p in procs:
        try:
            p.wait()
        except KeyboardInterrupt:
            stop_all()


if __name__ == "__main__":
    main()
