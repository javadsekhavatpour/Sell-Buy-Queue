"""
debug_clienttype_detailed.py
ذخیره و تحلیل دقیق پاسخ خام ClientType از TSETMC.

این اسکریپت:
  ۱. به چند endpoint مختلف ClientType وصل می‌شود
  ۲. پاسخ خام JSON را نمایش می‌دهد
  ۳. تمام فیلدها و ساختار را parse می‌کند
  ۴. در فایل ذخیره می‌کند

نحوه اجرا:
  python debug_clienttype_detailed.py
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

# چندین endpoint و پارامتر مختلف را امتحان می‌کنیم
ENDPOINTS = [
    # Endpoint اصلی با پارامترهای مختلف
    ("ClientType_1_0", "https://cdn.tsetmc.com/api/ClientType/GetClientType/4674107287748763521/1/0"),
    ("ClientType_0_0", "https://cdn.tsetmc.com/api/ClientType/GetClientType/4674107287748763521/0/0"),
    ("ClientType_2_0", "https://cdn.tsetmc.com/api/ClientType/GetClientType/4674107287748763521/2/0"),
    # بدون پارامتر اضافی
    ("ClientType_simple", "https://cdn.tsetmc.com/api/ClientType/GetClientType/4674107287748763521"),
    # نماد ریتون برای مقایسه
    ("ClientType_riton_1_0", "https://cdn.tsetmc.com/api/ClientType/GetClientType/14035144070182412/1/0"),
    # All - همه نمادها در یک پاسخ
    ("ClientTypeAll", "https://cdn.tsetmc.com/api/ClientType/GetClientTypeAll"),
]

output_log = []

def log(msg=""):
    print(msg)
    output_log.append(str(msg))

def main():
    log("=" * 70)
    log("  TSETMC ClientType API - Detailed Debug")
    log("=" * 70)
    log()
    log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log()

    raw_dir = ROOT / "data" / "raw_responses"
    raw_dir.mkdir(parents=True, exist_ok=True)

    for name, url in ENDPOINTS:
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

                if not content.strip():
                    log("⚠ Empty response")
                    log()
                    continue

                # ذخیره پاسخ خام
                raw_path = raw_dir / f"clienttype_{name}.json"
                with open(raw_path, "w", encoding="utf-8") as f:
                    f.write(content)
                log(f"✓ Saved to: {raw_path}")
                log()

                # نمایش پاسخ خام (کوتاه)
                log("RAW RESPONSE (first 1500 chars):")
                log(content[:1500])
                if len(content) > 1500:
                    log(f"... ({len(content) - 1500} more chars)")
                log()

                # parse JSON
                try:
                    data = json.loads(content)
                    log("PARSED JSON STRUCTURE:")
                    log()

                    if isinstance(data, dict):
                        log(f"Top-level keys: {list(data.keys())}")
                        log()

                        for k, v in data.items():
                            log(f"  Key: '{k}'")
                            log(f"    Type: {type(v).__name__}")
                            if isinstance(v, list):
                                log(f"    Length: {len(v)}")
                                if v:
                                    log(f"    First item type: {type(v[0]).__name__}")
                                    if isinstance(v[0], dict):
                                        log(f"    First item keys: {list(v[0].keys())}")
                                        log(f"    First item values:")
                                        for ik, iv in v[0].items():
                                            log(f"      {ik}: {iv}")
                                    log()
                                    if len(v) > 1:
                                        log(f"    Last item values:")
                                        if isinstance(v[-1], dict):
                                            for ik, iv in v[-1].items():
                                                log(f"      {ik}: {iv}")
                                        log()
                            elif isinstance(v, dict):
                                log(f"    Keys: {list(v.keys())}")
                                log(f"    Values:")
                                for ik, iv in v.items():
                                    log(f"      {ik}: {iv}")
                                log()
                            else:
                                log(f"    Value: {v}")
                                log()

                    elif isinstance(data, list):
                        log(f"List with {len(data)} items")
                        if data:
                            log(f"First item: {data[0]}")
                    log()

                except Exception as e:
                    log(f"JSON parse error: {e}")
                    log()

        except Exception as e:
            log(f"ERROR: {e}")
            log()

    # جستجوی فیلدهای احتمالی
    log("=" * 70)
    log("  Searching for client-type field names")
    log("=" * 70)
    log()

    # فیلدهای احتمالی بر اساس قراردادهای مختلف TSETMC
    possible_fields = [
        # Standard TSETMC new API
        "nIndividualBuy", "nIndividualSell",
        "nVolIndividualBuy", "nVolIndividualSell",
        "nCorporateBuy", "nCorporateSell",
        "nVolCorporateBuy", "nVolCorporateSell",
        # Alternative naming
        "nIndBuyCount", "nIndSellCount",
        "nIndBuyVol", "nIndSellVol",
        "nCorpBuyCount", "nCorpSellCount",
        "nCorpBuyVol", "nCorpSellVol",
        # Another common naming
        "buyCountInd", "sellCountInd",
        "buyVolInd", "sellVolInd",
        "buyCountCorp", "sellCountCorp",
        "buyVolCorp", "sellVolCorp",
        # Persian-style
        "Buy_N_Individual", "Sell_N_Individual",
        # Old API style (CSV-based)
        "buyCountReal", "sellCountReal",
    ]

    # در پاسخ‌های ذخیره شده جستجو کن
    for raw_path in raw_dir.glob("clienttype_*.json"):
        log(f"Searching in: {raw_path.name}")
        with open(raw_path, 'r', encoding='utf-8') as f:
            content = f.read()

        for field in possible_fields:
            if field in content:
                # پیدا شد
                idx = content.find(field)
                snippet = content[max(0, idx-20):idx+50]
                log(f"  ✓ FOUND '{field}': ...{snippet}...")
        log()

    # ذخیره گزارش
    report_path = ROOT / "data" / "debug_clienttype_detailed_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))

    log("=" * 70)
    log(f"Report saved to: {report_path}")
    log(f"Raw responses in: {raw_dir}")
    log("=" * 70)

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
