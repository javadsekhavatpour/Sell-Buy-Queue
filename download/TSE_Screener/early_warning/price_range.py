"""
early_warning/price_range.py
محاسبه درصد نوسان مجاز و کف/سقف قیمت روز برای یک نماد.

این ماژول توسط run_live.py در ابتدای اجرا به‌صورت خودکار فراخوانی می‌شود:
  ۱. اطلاعات پایه نماد از TSETMC دریافت می‌شود (نوع، بازار، نام کامل، قیمت دیروز)
  ۲. دسته نماد با تحلیل فیلدها تشخیص داده می‌شود
  ۳. درصد نوسان مجاز از RANGE_RULES خوانده می‌شود
  ۴. min_allowed_price و max_allowed_price نسبت به yesterday_price محاسبه می‌شود
  ۵. مقادیر در جدول price_range بانک ذخیره می‌شوند

اصل مهم: این محاسبات یک بار انجام می‌شوند و در طول روز ثابت می‌مانند.
data_collector در هر نمونه فقط مقادیر ثابت را از پیکربندی می‌خواند.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, date
from pathlib import Path
from typing import Dict, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────
#  جدول درصد نوسان مجاز بر اساس دسته نماد
#  (منبع: قواعد بورس و فرابورس ایران)
# ─────────────────────────────────────────────────────────────────────
RANGE_RULES: Dict[str, float] = {
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
#  تشخیص دسته نماد از فیلدهای خام تی‌اس‌ای
# ─────────────────────────────────────────────────────────────────────
def _norm(text) -> str:
    """نرمال‌سازی متن فارسی برای جستجوی کلیدواژه."""
    if not text:
        return ""
    s = str(text)
    s = s.replace("\u200c", " ")                    # نیم‌فاصله → فاصله
    s = s.replace("ي", "ی").replace("ك", "ک")      # ی/ک عربی → فارسی
    while "  " in s:
        s = s.replace("  ", " ")
    return s.strip().lower()


def identify_category(fields: dict) -> Tuple[Optional[str], dict]:
    """
    تشخیص دسته نماد از فیلدهای خام تی‌اس‌ای.

    فیلدهای استفاده‌شده:
      - yVal / yValTitle  : نوع نماد (سهام، حق تقدم، اوراق، صندوق)
      - flow / flowTitle  : بورس/فرابورس/بورس کالا
      - lVal30File        : نام کامل نماد (برای زیردسته صندوق‌ها)
      - lMarket / marketTitle : بازار فرعی (اصلی/فرعی/پایه/حرفه‌ای)

    بازگرداندن: (کلید دسته در RANGE_RULES, دیکشنری دیباگ)
    """
    y_val = str(fields.get("yVal", "")).strip()
    y_val_title = _norm(fields.get("yValTitle", ""))
    flow = str(fields.get("flow", "")).strip()
    flow_title = _norm(fields.get("flowTitle", ""))
    l_val30 = _norm(fields.get("lVal30File", ""))
    l_market = str(fields.get("lMarket", "")).strip()
    market_title = _norm(fields.get("marketTitle", ""))
    instrument_id = str(fields.get("instrumentID", "")).strip()
    cgr_val = _norm(fields.get("cgrValCot", ""))

    debug_fields = {
        "yVal": y_val, "yValTitle": y_val_title,
        "flow": flow, "flowTitle": flow_title,
        "lVal30File": l_val30, "lMarket": l_market,
        "marketTitle": market_title, "instrumentID": instrument_id,
        "cgrValCot": cgr_val,
    }

    # تشخیص نوع کلی از ISIN (پیشوند) و yValTitle
    is_stock = "سهام" in y_val_title or instrument_id.startswith("IRO1")
    is_rights = "حق تقدم" in y_val_title or instrument_id.startswith("IRO3")
    is_bond = (
        "اوراق" in y_val_title or "اختیار معامله" in y_val_title
        or "اختیار فروش" in y_val_title or instrument_id.startswith("IRO5")
    )
    is_fund = "صندوق" in y_val_title or "صندوق" in l_val30 or instrument_id.startswith("IRO7")

    is_commodity = "بورس کالا" in flow_title or flow == "4"

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

    # ۱. بورس کالا
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

    # ۲. صندوق‌های قابل معامله
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

    # ۳. اوراق
    if is_bond:
        if "تسهیلات مسکن" in l_val30 or "مسکن" in l_val30:
            return "اوراق تسهیلات مسکن", debug_fields
        return "اوراق بدهی (اختیار معامله، اختیار فروش تبعی و ...)", debug_fields

    # ۴. حق تقدم
    if is_rights:
        if is_professional:
            return "حق تقدم بازار سرمایه‌گذاری حرفه‌ای", debug_fields
        if is_base_market:
            return "بازار پایه - تابلوی زرد (الف)", debug_fields
        return "حق تقدم بازار اصلی (تابلوی اصلی و فرعی)", debug_fields

    # ۵. سهام
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
#  تاریخ شمسی (تقریب بدون کتابخانه خارجی)
# ─────────────────────────────────────────────────────────────────────
def _to_jalali(d: date) -> str:
    """تبدیل تاریخ میلادی به شمسی (تقریب)."""
    gy, gm, gd = d.year, d.month, d.day
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
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


# ─────────────────────────────────────────────────────────────────────
#  دریافت اطلاعات از TSETMC (با استفاده از collector)
# ─────────────────────────────────────────────────────────────────────
def _fetch_raw_search(collector, symbol: str) -> Optional[dict]:
    """دریافت آیتم کامل از InstrumentSearch (تمام فیلدهای خام)."""
    data = collector._api_get(f"Instrument/GetInstrumentSearch/{symbol}")
    if not data or not isinstance(data, dict):
        return None
    results = data.get("instrumentSearch") or data.get("InstrumentSearch") or []
    if not isinstance(results, list) or not results:
        return None
    # اولویت: مطابقت دقیق نام نماد
    for item in results:
        if not isinstance(item, dict):
            continue
        if (item.get("lVal18Afc") or "").strip() == symbol:
            return item
    return results[0] if isinstance(results[0], dict) else None


def _fetch_instrument_detail(collector, ins_code: str) -> Optional[dict]:
    """دریافت اطلاعات تکمیلی نماد (yValTitle/flowTitle/lMarket)."""
    for ep in (f"Instrument/GetInstrumentInfo/{ins_code}",
               f"Instrument/GetInstrumentShareChange/{ins_code}"):
        data = collector._api_get(ep)
        if not data or not isinstance(data, dict):
            continue
        info = (data.get("instrumentInfo") or data.get("InstrumentInfo")
                or data.get("instrumentShareChange") or data)
        if isinstance(info, dict) and len(info) > 1:
            return info
    return None


def _fetch_yesterday_price(collector, ins_code: str) -> Tuple[float, dict]:
    """دریافت قیمت دیروز از ClosingPrice API."""
    data = collector._api_get(f"ClosingPrice/GetClosingPriceInfo/{ins_code}")
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
#  تابع اصلی محاسبه
# ─────────────────────────────────────────────────────────────────────
def compute_price_range(collector, symbol: str, ins_code: str,
                        debug: bool = False) -> Optional[dict]:
    """
    محاسبه کامل درصد نوسان مجاز و کف/سقف برای یک نماد.

    از collector (MarketDataCollector) برای ارتباط با TSETMC استفاده می‌کند.

    بازگرداندن: دیکشنری با کلیدهای symbol, ins_code, category,
    range_percent, yesterday_price, min_allowed_price, max_allowed_price
    یا None در صورت خطا.
    """
    # ── ۱. جستجوی نماد (اگر ins_code موجود است، فقط نام کامل می‌گیریم) ──
    search_item = None
    if ins_code:
        # اگر ins_code داریم، جستجو برای گرفتن نام کامل و ISIN
        search_item = _fetch_raw_search(collector, symbol)
    else:
        search_item = _fetch_raw_search(collector, symbol)
        if search_item:
            ins_code = str(search_item.get("insCode") or "").strip()

    if not search_item and not ins_code:
        print("  [!] نماد در تی‌اس‌ای یافت نشد.")
        return None

    # استخراج فیلدهای پایه
    name_fa = ""
    l_val30 = ""
    instrument_id = ""
    if search_item:
        name_fa = (search_item.get("lVal18Afc") or "").strip()
        l_val30 = (search_item.get("lVal30File") or "").strip()
        instrument_id = str(search_item.get("instrumentID") or "").strip()

    if debug:
        print(f"  [DEBUG] نماد: {name_fa or symbol} | کد: {ins_code}")
        if search_item:
            print(f"  [DEBUG] فیلدهای خام InstrumentSearch:")
            for k, v in sorted(search_item.items()):
                print(f"    {k} = {v}")

    # ── ۲. دریافت اطلاعات تکمیلی ──
    detail = _fetch_instrument_detail(collector, ins_code) if ins_code else None
    all_fields = dict(search_item) if search_item else {}
    if detail:
        all_fields.update(detail)
        if debug:
            print(f"  [DEBUG] فیلدهای اضافی InstrumentInfo:")
            for k, v in sorted(detail.items()):
                if not search_item or k not in search_item:
                    print(f"    {k} = {v}")

    # ── ۳. تشخیص دسته ──
    category, cat_debug = identify_category(all_fields)
    if category:
        range_percent = RANGE_RULES[category]
        print(f"  ✓ دسته نماد: {category}")
        print(f"  ✓ درصد نوسان مجاز: {range_percent}%")
    else:
        range_percent = DEFAULT_RANGE_PERCENT
        print(f"  ⚠ دسته تشخیص داده نشد — درصد پیش‌فرض: {range_percent}%")
        if debug:
            for k, v in cat_debug.items():
                if v:
                    print(f"    {k} = {v}")

    # ── ۴. دریافت قیمت دیروز ──
    yesterday_price = 0.0
    if ins_code:
        yesterday_price, _ = _fetch_yesterday_price(collector, ins_code)
    if yesterday_price > 0:
        print(f"  ✓ قیمت دیروز: {yesterday_price:,.0f}")
    else:
        # fallback: از base_price پیکربندی
        base = collector.cfg.get("test_symbol", {}).get("base_price", 0) if hasattr(collector, "cfg") else 0
        if base and float(base) > 0:
            yesterday_price = float(base)
            print(f"  ⚠ قیمت دیروز از TSETMC دریافت نشد — استفاده از base_price: {yesterday_price:,.0f}")
        else:
            print("  [!] قیمت دیروز دریافت نشد — محاسبه کف/سقف ممکن نیست.")
            return None

    # ── ۵. محاسبه کف و سقف ──
    low_factor = 1 - range_percent / 100.0
    high_factor = 1 + range_percent / 100.0
    min_allowed = round(yesterday_price * low_factor, 0)
    max_allowed = round(yesterday_price * high_factor, 0)
    print(f"  ✓ کف مجاز: {min_allowed:,.0f}  |  سقف مجاز: {max_allowed:,.0f}")

    date_jalali = _to_jalali(date.today())
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

_PRICE_RANGE_COLS = [
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
        set_clause = ", ".join(f"{c}=?" for c in _PRICE_RANGE_COLS)
        values = [record.get(c) for c in _PRICE_RANGE_COLS]
        cur.execute(f"UPDATE price_range SET {set_clause} WHERE range_id=?",
                    (*values, range_id))
    else:
        placeholders = ", ".join("?" for _ in _PRICE_RANGE_COLS)
        col_names = ", ".join(_PRICE_RANGE_COLS)
        values = [record.get(c) for c in _PRICE_RANGE_COLS]
        cur.execute(f"INSERT INTO price_range ({col_names}) VALUES ({placeholders})",
                    values)
        range_id = cur.lastrowid
    conn.commit()
    conn.close()
    return range_id


def get_price_range(db_path: Path, symbol: str) -> Optional[dict]:
    """خواندن آخرین رکورد price_range برای یک نماد از بانک."""
    if not Path(db_path).exists():
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
        return dict(row) if row else None
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
