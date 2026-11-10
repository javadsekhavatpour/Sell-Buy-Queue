"""
debug_clienttype.py
ذخیره پاسخ خام ClientType از TSETMC برای ریتون.

این اسکریپت:
  ۱. به endpoint ClientType/GetClientType/14035144070182412/1/0 وصل می‌شود
  ۲. پاسخ خام JSON را نمایش می‌دهد
  ۳. در فایل ذخیره می‌کند

نحوه اجرا:
  python debug_clienttype.py
"""

import sys
import json
import urllib.request
from pathlib import Path
from datetime import datetime

# تنظیم encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent

# ذخیره گزارش
output_log = []

def log(msg=""):
    print(msg)
    output_log.append(str(msg))


def main():
    log("=" * 70)
    log("  Debug ClientType API Response")
    log("=" * 70)
    log()
    log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log()

    # چند endpoint مختلف را امتحان می‌کنیم
    endpoints = [
        ("ClientType v1", "https://cdn.tsetmc.com/api/ClientType/GetClientType/14035144070182412/1/0"),
        ("ClientType v2 (no params)", "https://cdn.tsetmc.com/api/ClientType/GetClientType/14035144070182412"),
        ("ClientType All", "https://cdn.tsetmc.com/api/ClientType/GetClientTypeAll"),
        ("ClosingPrice Info", "https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceInfo/14035144070182412"),
        ("BestLimits", "https://cdn.tsetmc.com/api/BestLimits/14035144070182412"),
    ]

    raw_dir = ROOT / "data" / "raw_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for name, url in endpoints:
        log("=" * 70)
        log(f"  {name}")
        log("=" * 70)
        log(f"URL: {url}")
        log()

        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "application/json",
                "Referer": "http://www.tsetmc.com/",
                "Origin": "http://www.tsetmc.com",
            })
            with urllib.request.urlopen(req, timeout=15) as r:
                content = r.read().decode('utf-8', errors='replace')
                log(f"HTTP Status: {r.status}")
                log(f"Content-Length: {len(content)} chars")
                log()
                log("RAW RESPONSE:")
                log(content)
                log()

                # ذخیره در فایل
                safe_name = name.replace(" ", "_").replace("(", "").replace(")", "")
                raw_path = raw_dir / f"debug_{safe_name}.txt"
                with open(raw_path, "w", encoding="utf-8") as f:
                    f.write(content)
                log(f"Saved to: {raw_path}")
                log()

                # تلاش برای parse JSON و نمایش ساختار
                try:
                    data = json.loads(content)
                    log("PARSED JSON (top-level keys):")
                    if isinstance(data, dict):
                        for key, value in data.items():
                            type_name = type(value).__name__
                            if isinstance(value, list):
                                log(f"  {key}: list ({len(value)} items)")
                                if value:
                                    log(f"    First item type: {type(value[0]).__name__}")
                                    if isinstance(value[0], dict):
                                        log(f"    First item keys: {list(value[0].keys())}")
                            elif isinstance(value, dict):
                                log(f"  {key}: dict (keys: {list(value.keys())})")
                            else:
                                log(f"  {key}: {type_name} = {value}")
                    elif isinstance(data, list):
                        log(f"  List with {len(data)} items")
                        if data and isinstance(data[0], dict):
                            log(f"  First item keys: {list(data[0].keys())}")
                    log()
                except Exception as e:
                    log(f"JSON parse error: {e}")
                    log()

        except Exception as e:
            log(f"ERROR: {e}")
            log()

    # ذخیره گزارش
    report_path = ROOT / "data" / "debug_clienttype_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))
    log("=" * 70)
    log(f"Report saved to: {report_path}")
    log(f"Raw responses saved in: {raw_dir}")
    log("=" * 70)

    # باز کردن خودکار در Notepad
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
        report_path = ROOT / "data" / "debug_clienttype_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_log))
