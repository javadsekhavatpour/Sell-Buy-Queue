"""
search_riton.py
اسکریپت پیدا کردن کد TSETMC نماد ریتون.

این اسکریپت از API جدید cdn.tsetmc.com برای جستجوی "ریتون" استفاده می‌کند.

نحوه اجرا:
  python search_riton.py
  python search_riton.py --search ریتون
"""

import sys
import argparse
import json
from pathlib import Path
from datetime import datetime

# تنظیم encoding برای Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import MarketDataCollector


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="پیدا کردن کد TSETMC نماد ریتون")
    parser.add_argument("--search", default="ریتون",
                        help="نماد برای جستجو (پیش‌فرض: ریتون)")
    parser.add_argument("--english", default="rhyton",
                        help="نام انگلیسی برای جستجو (پیش‌فرض: rhyton)")
    args = parser.parse_args()

    print("=" * 70)
    print("  Find TSETMC Code for ریتون")
    print("=" * 70)
    print()
    print(f"Search term (Farsi): {args.search}")
    print(f"Search term (English): {args.english}")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    config = load_config()
    collector = MarketDataCollector(config)
    collector.enable_debug(ROOT / "data" / "raw_responses")

    # ذخیره خروجی
    output_log = []

    def log(msg=""):
        print(msg)
        output_log.append(str(msg))

    # جستجوی فارسی
    log("=" * 70)
    log(f"Search 1: '{args.search}' (Farsi)")
    log("=" * 70)
    try:
        results = collector.search_symbol(args.search)
        log(f"Found {len(results)} results")
        log()
        for i, r in enumerate(results, 1):
            log(f"  Result {i}:")
            log(f"    code:    {r.get('code', 'N/A')}")
            log(f"    name_fa: {r.get('name_fa', 'N/A')}")
            log(f"    name_en: {r.get('name_en', 'N/A')}")
            log(f"    isin:    {r.get('isin', 'N/A')}")
            log()
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()

    # جستجوی انگلیسی
    log("=" * 70)
    log(f"Search 2: '{args.english}' (English)")
    log("=" * 70)
    try:
        results = collector.search_symbol(args.english)
        log(f"Found {len(results)} results")
        log()
        for i, r in enumerate(results, 1):
            log(f"  Result {i}:")
            log(f"    code:    {r.get('code', 'N/A')}")
            log(f"    name_fa: {r.get('name_fa', 'N/A')}")
            log(f"    name_en: {r.get('name_en', 'N/A')}")
            log(f"    isin:    {r.get('isin', 'N/A')}")
            log()
    except Exception as e:
        log(f"ERROR: {e}")

    # اگر نتیجه‌ای پیدا شد، آن را تست کن
    if results:
        log("=" * 70)
        log("Testing first result with fetch_intraday")
        log("=" * 70)
        first_code = results[0].get("code")
        if first_code:
            log(f"Testing ins_code: {first_code}")
            try:
                inst = collector.fetch_intraday(first_code)
                if inst:
                    log(f"  last_price:      {inst.get('last_price', 0):,}")
                    log(f"  close_price:     {inst.get('close_price', 0):,}")
                    log(f"  yesterday_price: {inst.get('yesterday_price', 0):,}")
                    log(f"  trade_volume:    {inst.get('trade_volume', 0):,}")
                    log(f"  buy_rows:         {len(inst.get('buy_rows', []))}")
                    log(f"  sell_rows:        {len(inst.get('sell_rows', []))}")
                else:
                    log("  Failed to fetch intraday data")
            except Exception as e:
                log(f"  ERROR: {e}")

    # ذخیره خروجی
    log_path = ROOT / "data" / "search_riton_result.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))
    print()
    print("=" * 70)
    print(f"Result saved to: {log_path}")
    print("=" * 70)
    print()
    print("Please send me the content of:")
    print(f"  1) {log_path}")
    print(f"  2) data/raw_responses/ folder (all files)")
    print()
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        try:
            input("\nPress Enter to exit...")
        except:
            pass
