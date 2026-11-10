"""
find_symbol_code.py
اسکریپت پیدا کردن کد ابزار (ins_code) صحیح نماد از TSETMC.

این اسکریپت با جستجوی نماد "ریتون" در TSETMC، کد صحیح آن را پیدا می‌کند.

نحوه اجرا:
  python find_symbol_code.py
  python find_symbol_code.py --search ریتون
"""

import sys
import argparse
import json
import re
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


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def search_symbol(search_term: str) -> list:
    """جستجوی نماد در TSETMC."""
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "http://www.tsetmc.com/",
    }

    # TSETMC search endpoint
    url = "http://www.tsetmc.com/tsev2/data/instsearch.aspx"
    params = {"s": search_term}

    print(f"Searching for: '{search_term}'...")
    print(f"URL: {url}?s={search_term}")
    print()

    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        print(f"HTTP Status: {r.status_code}")
        print(f"Response length: {len(r.text)}")
        print()
        print("Raw response (first 2000 chars):")
        print("─" * 70)
        print(r.text[:2000])
        print("─" * 70)
        print()

        # ذخیره پاسخ خام
        raw_path = ROOT / "data" / "search_raw_response.txt"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "w", encoding="utf-8") as f:
            f.write(r.text)
        print(f"Raw response saved to: {raw_path}")

        # تلاش برای parse
        results = parse_search_response(r.text, search_term)
        return results

    except Exception as e:
        print(f"ERROR: {e}")
        return []


def parse_search_response(raw: str, search_term: str) -> list:
    """Parse خروجی جستجوی TSETMC."""
    results = []
    print()
    print("Parsing response...")
    print()

    # فرمت معمول: ردیف‌ها با @ یا ; جدا می‌شوند
    # هر ردیف: code,name,name_en,...

    # روش ۱: split با @
    if "@" in raw:
        rows = raw.split("@")
    elif ";" in raw:
        rows = raw.split(";")
    elif "\n" in raw:
        rows = raw.split("\n")
    else:
        rows = [raw]

    print(f"Found {len(rows)} rows in response")

    for i, row in enumerate(rows):
        if not row.strip():
            continue
        # هر ردیف: کد,نام فارسی,نام انگلیسی,...
        cols = row.split(",")
        if len(cols) >= 2:
            code = cols[0].strip()
            name_fa = cols[1].strip() if len(cols) > 1 else ""
            name_en = cols[2].strip() if len(cols) > 2 else ""

            # فقط اگر شامل search_term باشد
            if (search_term in name_fa or
                search_term in name_en or
                search_term in code or
                i < 20):  # ۲۰ ردیف اول را همیشه نشان بده
                results.append({
                    "row_index": i,
                    "code": code,
                    "name_fa": name_fa,
                    "name_en": name_en,
                    "all_cols": cols,
                })

    return results


def test_specific_code(ins_code: str) -> dict:
    """تست یک کد ابزار خاص و نمایش پاسخ خام."""
    import requests

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "fa-IR,fa;q=0.9",
        "Referer": "http://www.tsetmc.com/",
    }

    print()
    print("=" * 70)
    print(f"Testing ins_code: {ins_code}")
    print("=" * 70)

    # تست چند endpoint
    endpoints = [
        ("instinfodata v2", "http://www.tsetmc.com/tsev2/data/instinfodata.aspx", {"i": ins_code, "c": "57+"}),
        ("instinfofast", "http://www.tsetmc.com/tsev2/data/instinfofast.aspx", {"i": ins_code}),
        ("MarketWatch", "http://www.tsetmc.com/tsev2/data/MarketWatchInit.aspx", {"i": ins_code}),
        ("InstrumentInfo", "http://www.tsetmc.com/tsev2/data/InstrumentInfo.aspx", {"i": ins_code}),
    ]

    results = {}

    for name, url, params in endpoints:
        print()
        print(f"  [{name}]")
        print(f"  URL: {url}")
        try:
            r = requests.get(url, params=params, headers=headers, timeout=15)
            print(f"  HTTP: {r.status_code}")
            print(f"  Length: {len(r.text)}")
            print(f"  First 500 chars:")
            print(f"    {r.text[:500]}")

            # ذخیره پاسخ خام
            raw_path = ROOT / "data" / f"raw_{name.replace(' ', '_')}_{ins_code}.txt"
            with open(raw_path, "w", encoding="utf-8") as f:
                f.write(r.text)
            print(f"  Saved to: {raw_path}")

            results[name] = {
                "status": r.status_code,
                "length": len(r.text),
                "raw_path": str(raw_path),
            }
        except Exception as e:
            print(f"  ERROR: {e}")
            results[name] = {"error": str(e)}

    return results


def main():
    parser = argparse.ArgumentParser(description="پیدا کردن کد ابزار نماد")
    parser.add_argument("--search", default="ریتون",
                        help="نماد برای جستجو (پیش‌فرض: ریتون)")
    parser.add_argument("--test-code", default="",
                        help="تست یک کد خاص (مثلا: 14035144070182412)")
    args = parser.parse_args()

    print("=" * 70)
    print("  TSETMC Symbol Code Finder")
    print("=" * 70)
    print()
    print(f"Search term: '{args.search}'")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # ذخیره همه خروجی در فایل
    output_log = []

    def log(msg=""):
        print(msg)
        output_log.append(str(msg))

    # مرحله ۱: جستجوی نماد
    log("=" * 70)
    log("Step 1: Search for symbol")
    log("=" * 70)
    results = search_symbol(args.search)

    log()
    log("=" * 70)
    log(f"Found {len(results)} results:")
    log("=" * 70)

    if results:
        for r in results[:20]:
            log(f"  Row {r['row_index']}: code={r['code']}  name_fa={r['name_fa']}  name_en={r['name_en']}")
            if len(r.get('all_cols', [])) > 3:
                log(f"    All cols: {r['all_cols']}")
    else:
        log("No results parsed - see raw response above")

    # مرحله ۲: تست کد فعلی
    current_code = "14035144070182412"
    log()
    log("=" * 70)
    log(f"Step 2: Test current ins_code: {current_code}")
    log("=" * 70)
    test_specific_code(current_code)

    # مرحله ۳: تست کد دلخواه کاربر
    if args.test_code:
        log()
        log("=" * 70)
        log(f"Step 3: Test custom ins_code: {args.test_code}")
        log("=" * 70)
        test_specific_code(args.test_code)

    # ذخیره لاگ
    log_path = ROOT / "data" / "find_symbol_result.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))
    print()
    print("=" * 70)
    print(f"Result saved to: {log_path}")
    print("=" * 70)
    print()
    print("Please send me:")
    print("  1) The content of data/find_symbol_result.txt")
    print("  2) The content of data/search_raw_response.txt")
    print("  3) The content of data/raw_instinfodata_v2_*.txt")
    print()
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
