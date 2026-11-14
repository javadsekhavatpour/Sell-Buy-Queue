"""
early_warning/price_range.py
محاسبه درصد نوسان مجاز و کف/سقف قیمت روز برای یک نماد — روش دستی.

این ماژول از دو فایل در پوشه config استفاده می‌کند:

  ۱. config/tse_range_rules.json
     جدول ۱۷ دسته با درصد مجاز (قابل ویرایش با فایل HTML).
     ساختار: [{cat, pct, desc}, ...]

  ۲. config/symbol_categories.json
     نگاشت دستی نماد → دسته.
     ساختار: {"اهرم": "صندوق اهرمی", "ریتون": "صندوق کالایی (سایر)", ...}

روند محاسبه (یک بار در ابتدای اجرای run_live.py):
  ۱. دسته نماد از config/symbol_categories.json خوانده می‌شود (دستی)
  ۲. درصد مجاز از config/tse_range_rules.json خوانده می‌شود
  ۳. yesterday_price از اولین فراخوانی API دریافت می‌شود
  ۴. min/max_allowed_price = yesterday_price × (1 ± pct/100) محاسبه می‌شود
  ۵. مقادیر در جدول daily_params بانک ذخیره می‌شوند (یک ردیف در روز)

اصل مهم: این مقادیر در طول روز ثابت می‌مانند و در هر رکورد snapshot
تکرار نمی‌شوند. جدول daily_params منبع مرجع است.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ─────────────────────────────────────────────────────────────────────
#  بارگذاری فایل‌های کانفیگ
# ─────────────────────────────────────────────────────────────────────
def load_range_rules(config_dir: Path) -> List[dict]:
    """
    بارگذاری config/tse_range_rules.json.

    بازگرداندن: لیست [{cat, pct, desc}, ...]
    """
    path = Path(config_dir) / "tse_range_rules.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_symbol_categories(config_dir: Path) -> Dict[str, str]:
    """
    بارگذاری config/symbol_categories.json.

    بازگرداندن: دیکشنری {نماد: دسته}
    """
    path = Path(config_dir) / "symbol_categories.json"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def rules_as_dict(rules: List[dict]) -> Dict[str, float]:
    """تبدیل لیست قوانین به دیکشنری {دسته: درصد}."""
    return {r["cat"]: float(r["pct"]) for r in rules}


# ─────────────────────────────────────────────────────────────────────
#  جستجوی دسته و درصد برای یک نماد
# ─────────────────────────────────────────────────────────────────────
def get_symbol_category(symbol: str, config_dir: Path) -> Optional[str]:
    """
    دسته نماد را از config/symbol_categories.json می‌خواند (نگاشت دستی).

    اگر نماد در فایل نبود، None برمی‌گرداند.
    """
    cats = load_symbol_categories(config_dir)
    # تطبیق دقیق، سپس تطبیق با حذف فاصله‌ها
    if symbol in cats:
        return cats[symbol]
    norm = symbol.replace(" ", "").replace("\u200c", "")
    for k, v in cats.items():
        if k.replace(" ", "").replace("\u200c", "") == norm:
            return v
    return None


def get_category_percent(category: str, config_dir: Path) -> Optional[float]:
    """
    درصد مجاز برای یک دسته را از config/tse_range_rules.json می‌خواند.
    """
    rules = load_range_rules(config_dir)
    for r in rules:
        if r["cat"] == category:
            return float(r["pct"])
    return None


def list_all_categories(config_dir: Path) -> List[str]:
    """فهرست همه دسته‌های موجود در tse_range_rules.json."""
    return [r["cat"] for r in load_range_rules(config_dir)]


# ─────────────────────────────────────────────────────────────────────
#  محاسبه پارامترهای ثابت روز
# ─────────────────────────────────────────────────────────────────────
def compute_daily_params(symbol: str, yesterday_price: float,
                         config_dir: Path) -> Optional[dict]:
    """
    محاسبه کامل پارامترهای ثابت روز برای یک نماد.

    مراحل:
      ۱. دسته نماد از symbol_categories.json (دستی)
      ۲. درصد مجاز از tse_range_rules.json
      ۳. min/max = yesterday_price × (1 ± pct/100)

    بازگرداندن: دیکشنری با کلیدهای symbol, category, range_percent,
    yesterday_price, min_allowed_price, max_allowed_price
    یا None اگر دسته یا درصد پیدا نشد.
    """
    category = get_symbol_category(symbol, config_dir)
    if not category:
        return None

    pct = get_category_percent(category, config_dir)
    if pct is None:
        return None

    yp = float(yesterday_price)
    min_allowed = round(yp * (1 - pct / 100.0), 0)
    max_allowed = round(yp * (1 + pct / 100.0), 0)

    return {
        "symbol": symbol,
        "category": category,
        "range_percent": pct,
        "yesterday_price": yp,
        "min_allowed_price": min_allowed,
        "max_allowed_price": max_allowed,
    }


# ─────────────────────────────────────────────────────────────────────
#  تاریخ شمسی (تقریب بدون کتابخانه خارجی)
# ─────────────────────────────────────────────────────────────────────
def to_jalali(d: date) -> str:
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
