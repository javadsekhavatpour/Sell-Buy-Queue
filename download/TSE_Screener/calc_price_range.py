#!/usr/bin/env python3
"""
calc_price_range.py
محاسبه درصد نوسان مجاز و کف/سقف قیمت روز برای یک نماد.

این اسکریپت یک بار در ابتدای روز (یا شروع run_live.py) اجرا می‌شود و:
  ۱. نام نماد را می‌گیرد
  ۲. از TSETMC اطلاعات پایه نماد را دریافت می‌کند:
       - نوع نماد و بازار (از فیلدهای yVal/yValTitle/flow/flowTitle/lVal30File/lMarket)
       - قیمت دیروز (pPriceYesterday از ClosingPrice API)
  ۳. دسته نماد را با تحلیل فیلدهای بالا تشخیص می‌دهد
  ۴. درصد نوسان مجاز را از RANGE_RULES می‌خواند
  ۵. min_allowed_price و max_allowed_price را نسبت به yesterday_price محاسبه می‌کند
  ۶. مقادیر را در جدول price_range بانک اطلاعاتی ذخیره می‌کند

اصل مهم: این محاسبات یک بار انجام می‌شوند و در طول روز ثابت می‌مانند.
run_live.py در هر نمونه فقط این مقادیر را از بانک می‌خواند و در نمونه ثبت می‌کند.

نحوه اجرا:
  python calc_price_range.py اهرم
  python calc_price_range.py --symbol ریتون
  python calc_price_range.py --symbol اهرم --db data/early_warning_live.sqlite
  python calc_price_range.py --symbol اهرم --debug     # نمایش همه فیلدهای خام API
  python calc_price_range.py --symbol اهرم --show       # فقط نمایش مقدار ذخیره‌شده
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# رفع مشکل نمایش فارسی در کنسول ویندوز
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────
#  جدول درصد نوسان مجاز بر اساس دسته نماد
#  (منبع: قواعد بورس و فرابورس ایران)
# ─────────────────────────────────────────────────────────────────────
RANGE_RULES: dict[str, float] = {
    # سهام و حق تقدم — بازار اصلی
    "سهام بازار اصلی (تابلوی اصلی و فرعی)": 6.0,
    "حق تقدم بازار اصلی (تابلوی اصلی و فرعی)": 6.0,
    "سهام بازار سرمایه‌گذاری حرفه‌ای": 3.0,
    "حق تقدم بازار سرمایه‌گذاری حرفه‌ای": 3.0,
    # بازار پایه (فرابورس)
    "بازار پایه - تابلوی زرد (الف)": 3.0,
    "بازار پایه - تابلوی نارنجی (ب)": 2.0,
    "بازار پایه - تابلوی قرمز (ج)": 1.0,
    # صندوق‌های قابل معامله
    "صندوق سهامی و مختلط": 10.0,
    "صندوق اهرمی": 6.0,
    "صندوق طلا (و نقره)": 10.0,
    "صندوق کالایی (سایر)": 10.0,
    "صندوق درآمد ثابت": 1.0,
    # اوراق
    "اوراق بدهی (اختیار معامله، اختیار فروش تبعی و ...)": 5.0,
    "اوراق تسهیلات مسکن": 5.0,
    # بورس کالا
    "قرارداد آتی (شمش طلا، نقره، مس)": 10.0,
    "قرارداد آتی (سایر کالاها)": 5.0,
    "گواهی سپرده کالایی (شمش و سکه)": 5.0,
}

# درصد پیش‌فرض اگر دسته به‌طور قطعی تشخیص داده نشود
DEFAULT_RANGE_PERCENT = 5.0

# ─────────────────────────────────────────────────────────────────────
#  تنظیمات API تی‌اس‌ای
# ─────────────────────────────────────────────────────────────────────
API_BASE = "https://cdn.tsetmc.com/api"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fa,en;q=0.9",
    "Referer": "http://www.tsetmc.com/",
    "Origin": "http://www.tsetmc.com",
}


# ─────────────────────────────────────────────────────────────────────
#  توابع ارتباط با API تی‌اس‌ای
# ─────────────────────────────────────────────────────────────────────
def api_get(endpoint: str, debug: bool = False):
    """درخواست GET به API تی‌اس‌ای و بازگرداندن JSON (یا متن خام)."""
    url = f"{API_BASE}/{endpoint.lstrip('/')}"
    req = Request(url, headers=HEADERS)
    try:
        with urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return None
            if debug:
                print(f"\n  [DEBUG] GET {endpoint}")
                print(f"  [DEBUG] طول پاسخ: {len(raw)} کاراکتر")
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                return raw
    except (HTTPError, URLError) as e:
        print(f"  [!] خطا در {endpoint}: {e}")
        return None
    except Exception as e:
        print(f"  [!] خطای غیرمنتظره در {endpoint}: {e}")
        return None


def search_symbol(symbol: str, debug: bool = False) -> dict | None:
    """
    جستجوی نماد در تی‌اس‌ای و بازگرداندن آیتم کامل (تمام فیلدهای خام).
    در صورت یافت نشدن مطابقت دقیق، اولین نتیجه بازگردانده می‌شود.
    """
    data = api_get(f"Instrument/GetInstrumentSearch/{symbol}", debug=debug)
    if not data or not isinstance(data, dict):
        return None

    results = data.get("instrumentSearch") or data.get("InstrumentSearch") or []
    if not isinstance(results, list) or not results:
        return None

    # اولویت: مطابقت دقیق نام نماد (lVal18Afc)
    for item in results:
        if not isinstance(item, dict):
            continue
        name = (item.get("lVal18Afc") or "").strip()
        if name == symbol:
            return item

    # در غیر این صورت اولین نتیجه
    return results[0] if isinstance(results[0], dict) else None


def fetch_instrument_detail(ins_code: str, debug: bool = False) -> dict | None:
    """
    دریافت اطلاعات تکمیلی نماد از endpoint‌های احتمالی تی‌اس‌ای.
    اگر هیچ endpoint جواب ندهد، None بازگردانده می‌شود
    (در این صورت فقط فیلدهای search_symbol استفاده می‌شوند).
    """
    endpoints = [
        f"Instrument/GetInstrumentInfo/{ins_code}",
        f"Instrument/GetInstrumentShareChange/{ins_code}",
    ]
    for ep in endpoints:
        data = api_get(ep, debug=debug)
        if not data or not isinstance(data, dict):
            continue
        info = (
            data.get("instrumentInfo")
            or data.get("InstrumentInfo")
            or data.get("instrumentShareChange")
            or data
        )
        if isinstance(info, dict) and len(info) > 1:
            return info
    return None


def fetch_yesterday_price(ins_code: str, debug: bool = False) -> tuple[float, dict]:
    """
    دریافت قیمت دیروز از ClosingPrice API.
    بازگرداندن: (yesterday_price, full_price_info_dict)
    """
    data = api_get(f"ClosingPrice/GetClosingPriceInfo/{ins_code}", debug=debug)
    if not data or not isinstance(data, dict):
        return 0.0, {}

    info = data.get("closingPriceInfo") or data.get("ClosingPriceInfo") or data
    if not isinstance(info, dict):
        return 0.0, {}

    yesterday = info.get("priceYesterday") or info.get("pPriceYesterday") or 0
    try:
        yesterday = float(yesterday)
    except (TypeError, ValueError):
        yesterday = 0.0
    return yesterday, info


# ─────────────────────────────────────────────────────────────────────
#  تشخیص دسته نماد از فیلدهای تی‌اس‌ای
# ─────────────────────────────────────────────────────────────────────
def _norm(text) -> str:
    """نرمال‌سازی متن فارسی برای جستج کلیدواژه (حذف نیم‌فاصله و فاصله اضافه)."""
    if not text:
        return ""
    s = str(text)
    s = s.replace("\u200c", " ")      # نیم‌فاصله → فاصله
    s = s.replace("ي", "ی").replace("ك", "ک")  # ی/ک عربی → فارسی
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip().lower()


def identify_category(fields: dict) -> tuple[str | None, dict]:
    """
    تشخیص دسته نماد از فیلدهای خام تی‌اس‌ای.

    فیلدهای استفاده‌شده (به ترتیب اولویت):
      - yVal / yValTitle  : نوع نماد (سهام، حق تقدم، اوراق، صندوق)
      - flow / flowTitle  : بورس/فرابورس/بورس کالا
      - lVal30File        : نام کامل نماد (برای تشخیص زیردسته صندوق‌ها)
      - lMarket / marketTitle / cSocCSAC : بازار فرعی (اصلی/فرعی/پایه/حرفه‌ای)

    بازگرداندن: (کلید دسته در RANGE_RULES, دیکشنری دیباگ)
    """
    y_val = str(fields.get("yVal", "")).strip()
    y_val_title = _norm(fields.get("yValTitle", ""))
    flow = str(fields.get("flow", "")).strip()
    flow_title = _norm(fields.get("flowTitle", ""))
    l_val30 = _norm(fields.get("lVal30File", ""))
    l_market = str(fields.get("lMarket", "")).strip()
    market_title = _norm(fields.get("marketTitle", ""))
    instrument_id = str(fields.get("instrumentID", "")).strip()  # ISIN
    c_soc = _norm(fields.get("cSocCSAC", ""))
    cgr_val = _norm(fields.get("cgrValCot", ""))

    debug_fields = {
        "yVal": y_val, "yValTitle": y_val_title,
        "flow": flow, "flowTitle": flow_title,
        "lVal30File": l_val30, "lMarket": l_market,
        "marketTitle": market_title, "instrumentID": instrument_id,
        "cSocCSAC": c_soc, "cgrValCot": cgr_val,
    }

    # ── تشخیص نوع کلی از ISIN (پیشوند) و yValTitle ──
    is_stock = "سهام" in y_val_title or instrument_id.startswith("IRO1")
    is_rights = "حق تقدم" in y_val_title or instrument_id.startswith("IRO3")
    is_bond = (
        "اوراق" in y_val_title or "اختیار معامله" in y_val_title
        or "اختیار فروش" in y_val_title or instrument_id.startswith("IRO5")
    )
    is_fund = "صندوق" in y_val_title or "صندوق" in l_val30 or instrument_id.startswith("IRO7")

    # ── تشخیص بورس کالا ──
    is_commodity = "بورس کالا" in flow_title or flow == "4"

    # بازار فرعی برای سهام و حق تقدم
    is_professional = "حرفه" in market_title or "حرفه" in cgr_val
    is_base_market = "پایه" in market_title or "پایه" in cgr_val
    base_table = None
    if is_base_market:
        if "زرد" in market_title or "الف" in cgr_val or "a" in cgr_val:
            base_table = "زرد"
        elif "نارنجی" in market_title or "ب" in cgr_val or "b" in cgr_val:
            base_table = "نارنجی"
        elif "قرمز" in market_title or "ج" in cgr_val or "c" in cgr_val:
            base_table = "قرمز"

    # ═══ ۱. بورس کالا ═══
    if is_commodity:
        if "گواهی سپرده" in l_val30 or ("سکه" in l_val30 and "سپرده" in l_val30):
            return "گواهی سپرده کالایی (شمش و سکه)", debug_fields
        if "آتی" in l_val30 or "futures" in l_val30:
            if any(k in l_val30 for k in ("طلا", "نقره", "مس", "شمش")):
                return "قرارداد آتی (شمش طلا، نقره، مس)", debug_fields
            return "قرارداد آتی (سایر کالاها)", debug_fields
        if "گواهی" in l_val30:
            return "گواهی سپرده کالایی (شمش و سکه)", debug_fields
        return "قرارداد آتی (سایر کالاها)", debug_fields

    # ═══ ۲. صندوق‌های قابل معامله ═══
    if is_fund:
        if "اهرمی" in l_val30 or "اهرم" in l_val30:
            return "صندوق اهرمی", debug_fields
        if "طلا" in l_val30 or "نقره" in l_val30:
            return "صندوق طلا (و نقره)", debug_fields
        if "درآمد ثابت" in l_val30:
            return "صندوق درآمد ثابت", debug_fields
        if "کالایی" in l_val30 or "کالا" in l_val30:
            return "صندوق کالایی (سایر)", debug_fields
        return "صندوق سهامی و مختلط", debug_fields

    # ═══ ۳. اوراق ═══
    if is_bond:
        if "تسهیلات مسکن" in l_val30 or "مسکن" in l_val30:
            return "اوراق تسهیلات مسکن", debug_fields
        return "اوراق بدهی (اختیار معامله، اختیار فروش تبعی و ...)", debug_fields

    # ═══ ۴. حق تقدم ═══
    if is_rights:
        if is_professional:
            return "حق تقدم بازار سرمایه‌گذاری حرفه‌ای", debug_fields
        if is_base_market:
            return "بازار پایه - تابلوی زرد (الف)", debug_fields
        return "حق تقدم بازار اصلی (تابلوی اصلی و فرعی)", debug_fields

    # ═══ ۵. سهام ═══
    if is_stock:
        if is_professional:
            return "سهام بازار سرمایه‌گذاری حرفه‌ای", debug_fields
        if is_base_market:
            if base_table == "زرد":
                return "بازار پایه - تابلوی زرد (الف)", debug_fields
            if base_table == "نارنجی":
                return "بازار پایه - تابلوی نارنجی (ب)", debug_fields
            if base_table == "قرمز":
                return "بازار پایه - تابلوی قرمز (ج)", debug_fields
            return "بازار پایه - تابلوی زرد (الف)", debug_fields
        return "سهام بازار اصلی (تابلوی اصلی و فرعی)", debug_fields

    return None, debug_fields


# ─────────────────────────────────────────────────────────────────────
#  ذخیره و خواندن در بانک اطلاعاتی
# ─────────────────────────────────────────────────────────────────────
PRICE_RANGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_range (
    range_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at        TEXT NOT NULL,
    date_jalali        TEXT,
    symbol             TEXT NOT NULL,
    ins_code           TEXT,
    isin               TEXT,
    category           TEXT,
    range_percent      REAL NOT NULL,
    yesterday_price    REAL NOT NULL,
    min_allowed_price  REAL NOT NULL,
    max_allowed_price  REAL NOT NULL,
    raw_yval           TEXT,
    raw_flow           TEXT,
    raw_yval_title     TEXT,
    raw_flow_title     TEXT,
    raw_lval30         TEXT,
    raw_lmarket        TEXT,
    raw_market_title   TEXT,
    notes              TEXT
);
"""

PRICE_RANGE_COLUMNS = [
    "computed_at", "date_jalali", "symbol", "ins_code", "isin",
    "category", "range_percent", "yesterday_price",
    "min_allowed_price", "max_allowed_price",
    "raw_yval", "raw_flow", "raw_yval_title", "raw_flow_title",
    "raw_lval30", "raw_lmarket", "raw_market_title", "notes",
]


def save_price_range(db_path: Path, record: dict) -> int:
    """ذخیره (یا به‌روزرسانی) رکورد price_range برای یک نماد در یک روز."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(PRICE_RANGE_SCHEMA)
    cur = conn.cursor()

    today = record.get("date_jalali", "")
    symbol = record.get("symbol", "")

    cur.execute(
        "SELECT range_id FROM price_range WHERE symbol=? AND date_jalali=? "
        "ORDER BY range_id DESC LIMIT 1",
        (symbol, today),
    )
    existing = cur.fetchone()

    if existing:
        range_id = existing[0]
        set_clause = ", ".join(f"{c}=?" for c in PRICE_RANGE_COLUMNS)
        values = [record.get(c) for c in PRICE_RANGE_COLUMNS]
        cur.execute(
            f"UPDATE price_range SET {set_clause} WHERE range_id=?",
            (*values, range_id),
        )
    else:
        placeholders = ", ".join("?" for _ in PRICE_RANGE_COLUMNS)
        col_names = ", ".join(PRICE_RANGE_COLUMNS)
        values = [record.get(c) for c in PRICE_RANGE_COLUMNS]
        cur.execute(
            f"INSERT INTO price_range ({col_names}) VALUES ({placeholders})",
            values,
        )
        range_id = cur.lastrowid

    conn.commit()
    conn.close()
    return range_id


def get_price_range(db_path: Path, symbol: str) -> dict | None:
    """
    خواندن آخرین رکورد price_range برای یک نماد از بانک.
    این تابع توسط run_live.py در ابتدای اجرا یک بار فراخوانی می‌شود.
    """
    if not db_path.exists():
        return None
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT * FROM price_range WHERE symbol=? ORDER BY range_id DESC LIMIT 1",
            (symbol,),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return None


# ─────────────────────────────────────────────────────────────────────
#  تابع اصلی محاسبه
# ─────────────────────────────────────────────────────────────────────
def compute_price_range(symbol: str, debug: bool = False) -> dict | None:
    """محاسبه کامل درصد نوسان مجاز و کف/سقف برای یک نماد."""
    print(f"  [۱] جستجوی نماد «{symbol}» در تی‌اس‌ای ...")
    search_item = search_symbol(symbol, debug=debug)
    if not search_item:
        print(f"  [!] نماد «{symbol}» در تی‌اس‌ای یافت نشد.")
        return None

    ins_code = str(search_item.get("insCode") or "").strip()
    name_fa = (search_item.get("lVal18Afc") or "").strip()
    l_val30 = (search_item.get("lVal30File") or "").strip()
    instrument_id = str(search_item.get("instrumentID") or "").strip()

    print(f"      نماد: {name_fa}")
    print(f"      کد تی‌اس‌ای: {ins_code}")
    print(f"      نام کامل: {l_val30}")
    if instrument_id:
        print(f"      ISIN: {instrument_id}")

    if debug:
        print(f"\n  [DEBUG] همه فیلدهای خام از InstrumentSearch:")
        for k, v in sorted(search_item.items()):
            print(f"    {k} = {v}")

    print(f"\n  [۲] دریافت اطلاعات تکمیلی نماد ...")
    detail = fetch_instrument_detail(ins_code, debug=debug)
    all_fields = dict(search_item)
    if detail:
        all_fields.update(detail)
        if debug:
            print(f"\n  [DEBUG] فیلدهای اضافی از InstrumentInfo:")
            for k, v in sorted(detail.items()):
                if k not in search_item:
                    print(f"    {k} = {v}")

    print(f"\n  [۳] تشخیص دسته نماد ...")
    category, cat_debug = identify_category(all_fields)
    if category:
        range_percent = RANGE_RULES[category]
        print(f"      دسته: {category}")
        print(f"      درصد نوسان مجاز: {range_percent}%")
    else:
        range_percent = DEFAULT_RANGE_PERCENT
        print(f"  [!] دسته تشخیص داده نشد — درصد پیش‌فرض: {range_percent}%")
        for k, v in cat_debug.items():
            if v:
                print(f"        {k} = {v}")

    print(f"\n  [۴] دریافت قیمت دیروز از تی‌اس‌ای ...")
    yesterday_price, price_info = fetch_yesterday_price(ins_code, debug=debug)
    if yesterday_price > 0:
        print(f"      قیمت دیروز: {yesterday_price:,.0f}")
    else:
        print(f"  [!] قیمت دیروز دریافت نشد.")
        return None

    print(f"\n  [۵] محاسبه کف و سقف مجاز:")
    low_factor = 1 - range_percent / 100.0
    high_factor = 1 + range_percent / 100.0
    min_allowed = round(yesterday_price * low_factor, 0)
    max_allowed = round(yesterday_price * high_factor, 0)
    print(f"      کف مجاز  (min_allowed): {min_allowed:,.0f}")
    print(f"      سقف مجاز (max_allowed): {max_allowed:,.0f}")

    # تبدیل تاریخ میلادی به شمسی (تقریب بدون کتابخانه خارجی)
    try:
        from datetime import date
        today = date.today()
        gy, gm, gd = today.year, today.month, today.day
        gy_d = gy - 1600
        gm_d = gm - 1
        gd_d = gd - 1
        g_day_no = 365 * gy_d + (gy_d + 3) // 4 - (gy_d + 99) // 100 + (gy_d + 399) // 400
        g_day_no += [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334][gm_d]
        if gm > 2 and ((gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)):
            g_day_no += 1
        g_day_no += gd_d
        j_day_no = g_day_no - 79
        j_np = j_day_no // 12053
        j_day_no %= 12053
        jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
        j_day_no %= 1461
        if j_day_no >= 366:
            jy += (j_day_no - 1) // 365
            j_day_no = (j_day_no - 1) % 365
        j_months = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]
        jm = 0
        while j_day_no >= j_months[jm]:
            j_day_no -= j_months[jm]
            jm += 1
        jm += 1
        jd = j_day_no + 1
        date_jalali = f"{jy:04d}/{jm:02d}/{jd:02d}"
    except Exception:
        date_jalali = datetime.now().strftime("%Y-%m-%d")

    return {
        "computed_at": datetime.now().isoformat(),
        "date_jalali": date_jalali,
        "symbol": name_fa or symbol,
        "ins_code": ins_code,
        "isin": instrument_id,
        "category": category or "(نامشخص — پیش‌فرض)",
        "range_percent": range_percent,
        "yesterday_price": yesterday_price,
        "min_allowed_price": min_allowed,
        "max_allowed_price": max_allowed,
        "raw_yval": cat_debug.get("yVal", ""),
        "raw_flow": cat_debug.get("flow", ""),
        "raw_yval_title": cat_debug.get("yValTitle", ""),
        "raw_flow_title": cat_debug.get("flowTitle", ""),
        "raw_lval30": l_val30,
        "raw_lmarket": cat_debug.get("lMarket", ""),
        "raw_market_title": cat_debug.get("marketTitle", ""),
        "notes": "",
    }


# ─────────────────────────────────────────────────────────────────────
#  خط فرمان
# ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="محاسبه درصد نوسان مجاز و کف/سقف قیمت روز برای یک نماد تی‌اس‌ای.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "مثال‌ها:\n"
            "  python calc_price_range.py اهرم\n"
            "  python calc_price_range.py --symbol ریتون\n"
            "  python calc_price_range.py --symbol اهرم --debug\n"
            "  python calc_price_range.py --symbol اهرم --show\n"
        ),
    )
    parser.add_argument("symbol", nargs="?", default=None, help="نام نماد (مثلا اهرم)")
    parser.add_argument("--symbol", dest="symbol_opt", default=None, help="نام نماد (جایگزین آرگومان 위치ی)")
    parser.add_argument("--db", default="data/early_warning_live.sqlite",
                        help="مسیر فایل SQLite (پیش‌فرض: data/early_warning_live.sqlite)")
    parser.add_argument("--debug", action="store_true", help="نمایش همه فیلدهای خام API")
    parser.add_argument("--show", action="store_true", help="فقط نمایش رکورد ذخیره‌شده در بانک")
    args = parser.parse_args()

    symbol = args.symbol or args.symbol_opt
    if not symbol and not args.show:
        parser.error("نام نماد الزامی است (مگر در حالت --show)")

    root = Path(__file__).parent
    db_path = (root / args.db).resolve()

    if args.show:
        sym = symbol or ""
        print("=" * 60)
        print("  رکورد price_range ذخیره‌شده در بانک")
        print("=" * 60)
        print(f"  بانک: {db_path}")
        if not db_path.exists():
            print("  [!] فایل بانک وجود ندارد.")
            return
        if sym:
            row = get_price_range(db_path, sym)
            if not row:
                print(f"  [!] رکوردی برای نماد «{sym}» یافت نشد.")
                return
            rows = [row]
        else:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            try:
                cur.execute("SELECT * FROM price_range ORDER BY computed_at DESC LIMIT 10")
                rows = [dict(r) for r in cur.fetchall()]
            except sqlite3.OperationalError:
                print("  [!] جدول price_range هنوز ایجاد نشده است.")
                return
            finally:
                conn.close()
            if not rows:
                print("  [!] هیچ رکوردی در جدول price_range نیست.")
                return
        for r in rows:
            print(f"\n  نماد: {r.get('symbol', '?')}")
            print(f"  کد تی‌اس‌ای: {r.get('ins_code', '?')}")
            print(f"  ISIN: {r.get('isin', '-')}")
            print(f"  دسته: {r.get('category', '?')}")
            print(f"  درصد نوسان مجاز: {r.get('range_percent', '?')}%")
            print(f"  قیمت دیروز: {r.get('yesterday_price', 0):,.0f}")
            print(f"  کف مجاز: {r.get('min_allowed_price', 0):,.0f}")
            print(f"  سقف مجاز: {r.get('max_allowed_price', 0):,.0f}")
            print(f"  محاسبه در: {r.get('computed_at', '?')}")
        return

    print("=" * 60)
    print(f"  محاسبه درصد نوسان مجاز — نماد «{symbol}»")
    print("=" * 60)
    print(f"  بانک: {db_path}")
    print()

    record = compute_price_range(symbol, debug=args.debug)
    if not record:
        print("\n[!] محاسبه انجام نشد.")
        sys.exit(1)

    print(f"\n  [۶] ذخیره در بانک اطلاعاتی ...")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    range_id = save_price_range(db_path, record)
    print(f"      رکورد با شناسه {range_id} ذخیره شد (جدول price_range).")

    print("\n" + "=" * 60)
    print("  خلاصه نتیجه")
    print("=" * 60)
    print(f"  نماد             : {record['symbol']}")
    print(f"  کد تی‌اس‌ای       : {record['ins_code']}")
    print(f"  دسته             : {record['category']}")
    print(f"  درصد نوسان مجاز  : {record['range_percent']}%")
    print(f"  قیمت دیروز       : {record['yesterday_price']:,.0f}")
    print(f"  کف مجاز          : {record['min_allowed_price']:,.0f}")
    print(f"  سقف مجاز         : {record['max_allowed_price']:,.0f}")
    print("=" * 60)
    print("\n  run_live.py در ابتدای اجرا یک بار این مقادیر را از جدول")
    print("  price_range می‌خواند و در تمام نمونه‌های روز از آن‌ها استفاده می‌کند.")


if __name__ == "__main__":
    main()
