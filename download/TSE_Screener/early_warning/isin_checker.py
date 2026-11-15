"""
isin_checker.py
ماژول استخراج ISIN از TSE و محاسبه درصد نوسان مجاز بر اساس پیشوند ISIN.

روند کار:
  ۱. fetch_isin(collector, ins_code) → کد ISIN نماد از API TSETMC
  ۲. parse_range_rules_html(html_path) → خواندن جدول درصد از فایل HTML کانفیگ
  ۳. get_range_percent_by_isin(isin, rules) → درصد متناظر با پیشوند ISIN

منبع درصدها: config/tse_range_rules.html (قابل ویرایش دستی)
اگر قوانین بورس تغییر کند، فقط آن فایل HTML ویرایش می‌شود.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# پارس کردن فایل HTML کانفیگ
# ---------------------------------------------------------------------------

def parse_range_rules_html(html_path: Path | str) -> Dict[str, Tuple[str, float]]:
    """
    خواندن جدول درصد نوسان مجاز از فایل HTML.

    فایل HTML باید یک جدول با data-attributeهای زیر داشته باشد:
      <td data-prefix="IRO7" ...>IRO7</td>
      <td ...>صندوق‌های سرمایه‌گذاری (ETF)</td>
      <td data-pct="10" ...>± 10 ٪</td>

    خروجی: { "IRO7": ("صندوق‌های سرمایه‌گذاری (ETF)", 10.0), ... }
    """
    html_path = Path(html_path)
    if not html_path.exists():
        return {}

    html = html_path.read_text(encoding="utf-8")

    # استخراج ردیف‌های <tr> داخل <tbody>
    # هر ردیف باید شامل data-prefix و data-pct باشد
    rules: Dict[str, Tuple[str, float]] = {}

    # الگو: یک ردیف کامل <tr>...</tr> که data-prefix و data-pct دارد
    # Group 1: prefix (از data-prefix)
    # Group 2: محتوای td دوم (دسته) — می‌تواند شامل data-attribute هم باشد
    # Group 3: pct (از data-pct)
    row_pattern = re.compile(
        r"<tr[^>]*>"                        # شروع ردیف
        r".*?data-prefix\s*=\s*\"([^\"]+)\""  # پیشوند ISIN
        r".*?<td[^>]*class=\"cat\"[^>]*>(.*?)</td>"  # دسته نماد
        r".*?data-pct\s*=\s*\"([^\"]+)\""   # درصد
        r".*?</tr>",
        re.DOTALL | re.IGNORECASE,
    )

    for m in row_pattern.finditer(html):
        prefix = m.group(1).strip().upper()
        category_raw = m.group(2).strip()
        # حذف تگ‌های HTML از نام دسته
        category = re.sub(r"<[^>]+>", "", category_raw).strip()
        try:
            pct = float(m.group(3).strip())
        except ValueError:
            continue
        if prefix and pct > 0:
            rules[prefix] = (category, pct)

    return rules


# ---------------------------------------------------------------------------
# استخراج پیشوند ISIN
# ---------------------------------------------------------------------------

def get_isin_prefix(isin: str) -> str:
    """
    استخراج پیشوند ISIN (۴ کاراکتر اول).

    مثال: "IRO7TSEF0121" → "IRO7"
    پیشوندهای استاندارد بورس تهران:
      IRO1 = سهام بازار اصلی
      IRO3 = حق تقدم
      IRO4 = بازار پایه
      IRO5 = اوراق بدهی
      IRO6 = گواهی سپرده
      IRO7 = صندوق (ETF)
      IRO8 = قرارداد آتی
    """
    if not isin:
        return ""
    isin = isin.strip().upper()
    # پیشوند همیشه ۴ کاراکتر است (IRO + یک رقم)
    return isin[:4]


# ---------------------------------------------------------------------------
# جستجوی درصد بر اساس ISIN
# ---------------------------------------------------------------------------

def get_range_percent_by_isin(
    isin: str,
    rules: Dict[str, Tuple[str, float]] | None = None,
    html_path: Path | str | None = None,
) -> Optional[Tuple[str, float]]:
    """
    جستجوی دسته و درصد متناظر با ISIN.

    ورودی:
      isin: کد ISIN کامل (مثل "IRO7TSEF0121")
      rules: دیکشنری از parse_range_rules_html (اختیاری)
      html_path: مسیر فایل HTML (اگر rules داده نشد)

    خروجی: (category, pct) یا None اگر پیشوند پیدا نشد
    """
    if rules is None:
        if html_path is None:
            return None
        rules = parse_range_rules_html(html_path)

    prefix = get_isin_prefix(isin)
    if not prefix:
        return None

    return rules.get(prefix)


# ---------------------------------------------------------------------------
# تابع اصلی: دریافت ISIN از TSE و محاسبه درصد
# ---------------------------------------------------------------------------

def get_symbol_range_from_isin(
    collector,
    ins_code: str,
    html_path: Path | str,
) -> Optional[Dict]:
    """
    دریافت ISIN نماد از TSE و محاسبه درصد نوسان مجاز.

    مراحل:
      ۱. fetch_isin(collector, ins_code) → ISIN از API
      ۲. get_range_percent_by_isin(isin, html_path) → (category, pct)
      ۳. خروجی: { isin, prefix, category, range_percent }

    اگر ISIN دریافت نشد یا پیشوند در جدول نبود، None برمی‌گرداند.
    """
    rules = parse_range_rules_html(html_path)
    if not rules:
        return None

    isin = collector.fetch_isin(str(ins_code))
    if not isin:
        return None

    prefix = get_isin_prefix(isin)
    result = get_range_percent_by_isin(isin, rules=rules)
    if result is None:
        return {
            "isin": isin,
            "prefix": prefix,
            "category": None,
            "range_percent": None,
            "found": False,
        }

    category, pct = result
    return {
        "isin": isin,
        "prefix": prefix,
        "category": category,
        "range_percent": pct,
        "found": True,
    }


# ---------------------------------------------------------------------------
# محاسبه کف/سقف مجاز بر اساس ISIN
# ---------------------------------------------------------------------------

def compute_range_from_isin(
    collector,
    ins_code: str,
    yesterday_price: float,
    html_path: Path | str,
) -> Optional[Dict]:
    """
    محاسبه کامل کف/سقف مجاز بر اساس ISIN و قیمت دیروز.

    خروجی:
      {
        isin, prefix, category, range_percent,
        yesterday_price, min_allowed_price, max_allowed_price,
      }
    یا None اگر ISIN دریافت نشد یا پیشوند پیدا نشد.
    """
    info = get_symbol_range_from_isin(collector, ins_code, html_path)
    if not info or not info.get("found"):
        return info  # برگرداندن info با found=False برای پیام خطا

    pct = info["range_percent"]
    if yesterday_price <= 0 or pct is None:
        return None

    min_allowed = round(yesterday_price * (1 - pct / 100.0), 0)
    max_allowed = round(yesterday_price * (1 + pct / 100.0), 0)

    return {
        "isin": info["isin"],
        "prefix": info["prefix"],
        "category": info["category"],
        "range_percent": pct,
        "yesterday_price": yesterday_price,
        "min_allowed_price": min_allowed,
        "max_allowed_price": max_allowed,
    }
