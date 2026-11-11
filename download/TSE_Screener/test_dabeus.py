"""
test_dabeus.py
تست اتصال به دابور و جستجوی کد صحیح آن.

این اسکریپت:
  ۱. کلمه 'دابور' را در TSETMC جستجو می‌کند
  ۲. تمام کدهای پیدا شده را نمایش می‌دهد
  ۳. هر کد را با fetch_intraday تست می‌کند
  ۴. پاسخ خام را ذخیره می‌کند

نحوه اجرا:
  python test_dabeus.py
"""

import sys
import json
import urllib.request
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import MarketDataCollector

output_log = []

def log(msg=""):
    print(msg)
    output_log.append(str(msg))

def main():
    log("=" * 70)
    log("  Test Dabeus (دابور) Connection")
    log("=" * 70)
    log()
    log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Current ins_code in config: 4674107287748763521")
    log()

    config = json.loads((ROOT / "config" / "warning_thresholds.json").read_text(encoding='utf-8'))
    collector = MarketDataCollector(config)
    collector.enable_debug(ROOT / "data" / "raw_responses")

    # مرحله ۱: جستجوی دابور در TSETMC
    log("=" * 70)
    log("STEP 1: Search for 'دابور' in TSETMC")
    log("=" * 70)
    log()

    search_terms = ["دابور", "dabeus", "Dabeus", "DABEUS"]
    all_results = []

    for term in search_terms:
        log(f"Searching: '{term}'")
        try:
            results = collector.search_symbol(term)
            log(f"  Found {len(results)} results")
            for r in results:
                log(f"    code: {r.get('code', 'N/A')}")
                log(f"    name_fa: {r.get('name_fa', 'N/A')}")
                log(f"    name_en: {r.get('name_en', 'N/A')}")
                log(f"    isin: {r.get('isin', 'N/A')}")
                log()
                all_results.append(r)
        except Exception as e:
            log(f"  ERROR: {e}")
        log()

    if not all_results:
        log("⚠ No results found for دابور!")
        log("The symbol may not exist or the search API is not working.")
        log()

    # مرحله ۲: تست کد فعلی (4674107287748763521)
    log("=" * 70)
    log("STEP 2: Test current ins_code 4674107287748763521")
    log("=" * 70)
    log()

    test_code = "4674107287748763521"

    # تست مستقیم با urllib
    log("Direct API test:")
    urls = [
        ("ClosingPrice", f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceInfo/{test_code}"),
        ("BestLimits", f"https://cdn.tsetmc.com/api/BestLimits/{test_code}"),
        ("ClientType", f"https://cdn.tsetmc.com/api/ClientType/GetClientType/{test_code}/1/0"),
        ("InstrumentSearch_dabeus", "https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/dabeus"),
    ]

    for name, url in urls:
        log(f"  {name}:")
        log(f"    URL: {url}")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Referer": "http://www.tsetmc.com/",
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                content = r.read().decode('utf-8', errors='replace')
                log(f"    HTTP Status: {r.status}")
                log(f"    Length: {len(content)} chars")
                log(f"    First 300 chars: {content[:300]}")
                log()

                # ذخیره
                raw_dir = ROOT / "data" / "raw_responses"
                raw_dir.mkdir(parents=True, exist_ok=True)
                with open(raw_dir / f"dabeus_{name}.json", "w", encoding="utf-8") as f:
                    f.write(content)
        except Exception as e:
            log(f"    ERROR: {e}")
            log()

    # مرحله ۳: تست هر کد پیدا شده با fetch_intraday
    log("=" * 70)
    log("STEP 3: Test all found codes with fetch_intraday")
    log("=" * 70)
    log()

    unique_codes = set()
    for r in all_results:
        if r.get("code"):
            unique_codes.add(r["code"])

    # اضافه کردن کد فعلی
    unique_codes.add(test_code)

    for code in unique_codes:
        log(f"Testing code: {code}")
        try:
            inst = collector.fetch_intraday(code)
            if inst is None:
                log(f"  ❌ fetch_intraday returned None")
            else:
                log(f"  ✓ Got data:")
                log(f"    last_price: {inst.get('last_price', 0):,}")
                log(f"    close_price: {inst.get('close_price', 0):,}")
                log(f"    yesterday_price: {inst.get('yesterday_price', 0):,}")
                log(f"    buy_rows: {len(inst.get('buy_rows', []))}")
                log(f"    sell_rows: {len(inst.get('sell_rows', []))}")
                if inst.get('last_price', 0) > 0 or inst.get('close_price', 0) > 0:
                    log(f"  ✓✓ This code WORKS!")
                else:
                    log(f"  ⚠ All prices are 0 - symbol may not have traded today")
        except Exception as e:
            log(f"  ERROR: {e}")
        log()

    # خلاصه
    log("=" * 70)
    log("SUMMARY")
    log("=" * 70)
    log()

    if all_results:
        log(f"Found {len(all_results)} results for 'دابور'")
        log(f"Codes found: {[r.get('code') for r in all_results]}")
        log()
        log("If the current code 4674107287748763521 doesn't work,")
        log("try one of the codes found above.")
    else:
        log("No results for 'دابور'. The symbol may have been delisted")
        log("or the search API is not working properly.")
    log()

    # ذخیره گزارش
    report_path = ROOT / "data" / "test_dabeus_result.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))
    log(f"Report saved to: {report_path}")

    try:
        import os
        os.startfile(str(report_path))
    except:
        pass

    try:
        input("Press Enter to exit...")
    except:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        log(traceback.format_exc())
