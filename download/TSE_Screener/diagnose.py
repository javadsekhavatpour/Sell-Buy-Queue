"""
diagnose.py
اسکریپت تشخیصی کامل - همه چیز را در یک گزارش ذخیره می‌کند.

این اسکریپت:
  ۱. نسخه فعلی data_collector.py را بررسی می‌کند
  ۲. اتصال اینترنت به TSETMC را تست می‌کند
  ۳. جستجوی ریتون را انجام می‌دهد
  ۴. پاسخ‌های خام TSETMC را ذخیره می‌کند
  ۵. همه چیز را در data/diagnose_report.txt ذخیره می‌کند

نحوه اجرا:
  python diagnose.py
"""

import sys
import os
import json
import io
import urllib.request
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

# ذخیره همه خروجی‌ها
output_log = []

def log(msg=""):
    print(msg)
    output_log.append(str(msg))

def save_report():
    report_path = ROOT / "data" / "diagnose_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))
    return report_path

def main():
    log("=" * 70)
    log("  TSE Early Warning - Complete Diagnostic Report")
    log("=" * 70)
    log()
    log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Working directory: {Path.cwd()}")
    log()

    # ========== بخش ۱: بررسی نسخه data_collector.py ==========
    log("=" * 70)
    log("PART 1: Checking data_collector.py version")
    log("=" * 70)
    log()

    dc_path = ROOT / "early_warning" / "data_collector.py"
    log(f"Expected path: {dc_path}")
    log(f"File exists: {dc_path.exists()}")

    if not dc_path.exists():
        # جستجوی بازگشتی
        log("File not found at expected location. Searching...")
        for p in ROOT.rglob("data_collector.py"):
            log(f"  Found: {p}")
            with open(p, 'r', encoding='utf-8') as f:
                content = f.read()
            has_cdn = "cdn.tsetmc.com" in content
            log(f"    Has cdn.tsetmc.com (NEW v3): {has_cdn}")
            log(f"    File size: {len(content)} chars")
        log()
        log("ERROR: data_collector.py not found in early_warning/")
        report_path = save_report()
        log()
        log(f"Report saved to: {report_path}")
        try:
            input("Press Enter to exit...")
        except:
            pass
        return

    with open(dc_path, 'r', encoding='utf-8') as f:
        content = f.read()

    has_cdn = "cdn.tsetmc.com" in content
    has_old = "tsev2/data/instinfodata.aspx" in content
    has_enable_debug = "def enable_debug" in content
    has_search_symbol = "def search_symbol" in content

    log(f"File size: {len(content)} chars")
    log(f"Has cdn.tsetmc.com (NEW v3):  {has_cdn}")
    log(f"Has old API (OLD v2):        {has_old}")
    log(f"Has enable_debug method:     {has_enable_debug}")
    log(f"Has search_symbol method:   {has_search_symbol}")
    log()

    if has_cdn:
        log(">>> VERSION: NEW (v3.0 with cdn.tsetmc.com) ✓")
    elif has_old:
        log(">>> VERSION: OLD (v2.0 with tsev2/data) ✗")
        log(">>> You need to run update_from_github.bat")
    else:
        log(">>> VERSION: UNKNOWN")
    log()

    # ========== بخش ۲: تست اتصال اینترنت به TSETMC ==========
    log("=" * 70)
    log("PART 2: Testing internet connection to TSETMC")
    log("=" * 70)
    log()

    test_urls = [
        ("https://cdn.tsetmc.com", "API Base (NEW)"),
        ("http://www.tsetmc.com", "Main site (OLD)"),
    ]

    for url, desc in test_urls:
        log(f"Testing: {desc}")
        log(f"  URL: {url}")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                content_length = len(r.read(2000))
                log(f"  Status: HTTP {r.status}")
                log(f"  Response length (first 2000 bytes): {content_length}")
                log(f"  SUCCESS - connection works")
        except Exception as e:
            log(f"  FAILED: {e}")
        log()

    # ========== بخش ۳: جستجوی ریتون ==========
    log("=" * 70)
    log("PART 3: Searching for ریتون symbol")
    log("=" * 70)
    log()

    try:
        from early_warning import MarketDataCollector
        config = json.loads((ROOT / "config" / "warning_thresholds.json").read_text(encoding='utf-8'))
        collector = MarketDataCollector(config)

        # تست با عبارت فارسی و انگلیسی
        search_terms = ["ریتون", "rhyton", "Riton", "Rhyton"]

        for term in search_terms:
            log(f"Searching: '{term}'")
            try:
                results = collector.search_symbol(term)
                log(f"  Found {len(results)} results")
                for i, r in enumerate(results[:3], 1):
                    log(f"  Result {i}:")
                    log(f"    code:    {r.get('code', 'N/A')}")
                    log(f"    name_fa: {r.get('name_fa', 'N/A')}")
                    log(f"    name_en: {r.get('name_en', 'N/A')}")
                    log(f"    isin:    {r.get('isin', 'N/A')}")
                log()
            except Exception as e:
                log(f"  ERROR: {e}")
                import traceback
                log(f"  {traceback.format_exc()}")
                log()

    except Exception as e:
        log(f"Import ERROR: {e}")
        import traceback
        log(f"  {traceback.format_exc()}")
        log()

    # ========== بخش ۴: ذخیره پاسخ خام TSETMC ==========
    log("=" * 70)
    log("PART 4: Saving raw TSETMC responses")
    log("=" * 70)
    log()

    raw_dir = ROOT / "data" / "raw_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # ذخیره پاسخ خام از API جدید
    test_endpoints = [
        ("ClosingPrice_GetClosingPriceInfo_riton", "https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceInfo/14035144070182412"),
        ("BestLimits_riton", "https://cdn.tsetmc.com/api/BestLimits/14035144070182412"),
        ("ClientType_riton", "https://cdn.tsetmc.com/api/ClientType/GetClientType/14035144070182412/1/0"),
        ("InstrumentSearch_rhyton", "https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/rhyton"),
        ("InstrumentSearch_riton", "https://cdn.tsetmc.com/api/Instrument/GetInstrumentSearch/ریتون"),
    ]

    for name, url in test_endpoints:
        log(f"Testing: {name}")
        log(f"  URL: {url}")
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Referer": "http://www.tsetmc.com/",
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                content = r.read().decode('utf-8', errors='replace')
                log(f"  Status: HTTP {r.status}")
                log(f"  Response length: {len(content)} chars")
                # ذخیره پاسخ خام
                raw_path = raw_dir / f"{name}.txt"
                with open(raw_path, "w", encoding="utf-8") as f:
                    f.write(content)
                log(f"  Saved to: {raw_path}")
                # نمایش 500 کاراکتر اول
                log(f"  First 500 chars:")
                log(f"    {content[:500]}")
                log()
        except Exception as e:
            log(f"  FAILED: {e}")
            log()

    # ========== گزارش نهایی ==========
    log("=" * 70)
    log("FINAL REPORT")
    log("=" * 70)
    log()

    report_path = save_report()
    log(f"Full report saved to: {report_path}")
    log(f"Raw responses saved in: {raw_dir}")
    log()
    log("Please send me:")
    log(f"  1) The content of {report_path}")
    log(f"  2) All files in {raw_dir}/ folder")
    log()
    log("These will help me understand what TSETMC returns and fix any issues.")
    log()

    # باز کردن خودکار در Notepad
    try:
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
        save_report()
        try:
            input("Press Enter to exit...")
        except:
            pass
