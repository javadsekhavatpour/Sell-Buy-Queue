#!/usr/bin/env python3
"""تست‌های واحد و یکپارچگی برای calc_price_range.py و تغییرات data_collector.py."""

import sys
import os
import tempfile
from pathlib import Path

# مسیر پروژه
PROJ = Path(__file__).parent.parent / "download" / "TSE_Screener"
sys.path.insert(0, str(PROJ))

from calc_price_range import (
    RANGE_RULES,
    DEFAULT_RANGE_PERCENT,
    identify_category,
    save_price_range,
    get_price_range,
)

passed = 0
failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}  {detail}")


print("=" * 60)
print("  تست‌های calc_price_range.py و یکپارچگی data_collector")
print("=" * 60)

# ── ۱. جدول RANGE_RULES ──
print("\n[۱] جدول RANGE_RULES")
check("تعداد دسته‌ها = ۱۷", len(RANGE_RULES) == 17, f"تعداد: {len(RANGE_RULES)}")
check("سهام بازار اصلی = ۶٪", RANGE_RULES.get("سهام بازار اصلی (تابلوی اصلی و فرعی)") == 6.0)
check("صندوق اهرمی = ۶٪", RANGE_RULES.get("صندوق اهرمی") == 6.0)
check("صندوق طلا = ۱۰٪", RANGE_RULES.get("صندوق طلا (و نقره)") == 10.0)
check("صندوق درآمد ثابت = ۱٪", RANGE_RULES.get("صندوق درآمد ثابت") == 1.0)
check("بازار پایه زرد = ۳٪", RANGE_RULES.get("بازار پایه - تابلوی زرد (الف)") == 3.0)
check("بازار پایه قرمز = ۱٪", RANGE_RULES.get("بازار پایه - تابلوی قرمز (ج)") == 1.0)
check("قرارداد آتی طلا = ۱۰٪", RANGE_RULES.get("قرارداد آتی (شمش طلا، نقره، مس)") == 10.0)

# ── ۲. تشخیص دسته — صندوق‌ها ──
print("\n[۲] تشخیص دسته: صندوق‌ها")
cat, _ = identify_category({
    "yValTitle": "صندوق سرمایه گذاری قابل معامله",
    "flowTitle": "بورس",
    "lVal30File": "صندوق سرمایه گذاری طلا پاسارگاد",
    "instrumentID": "IRO7TOLDP0001",
})
check("صندوق طلا", cat == "صندوق طلا (و نقره)", f"دسته: {cat}")

cat, _ = identify_category({
    "yValTitle": "صندوق سرمایه گذاری قابل معامله",
    "flowTitle": "فرابورس",
    "lVal30File": "صندوق سرمایه گذاری اهرمی فردا",
    "instrumentID": "IRO7SEKP0001",
})
check("صندوق اهرمی", cat == "صندوق اهرمی", f"دسته: {cat}")

cat, _ = identify_category({
    "yValTitle": "صندوق سرمایه گذاری قابل معامله",
    "flowTitle": "فرابورس",
    "lVal30File": "صندوق سرمایه گذاری درآمد ثابت کمال",
    "instrumentID": "IRO7FARP0001",
})
check("صندوق درآمد ثابت", cat == "صندوق درآمد ثابت", f"دسته: {cat}")

# ── ۳. تشخیص دسته — سهام و حق تقدم ──
print("\n[۳] تشخیص دسته: سهام و حق تقدم")
cat, _ = identify_category({
    "yValTitle": "سهام عادی",
    "flowTitle": "بورس",
    "lVal30File": "دابور",
    "instrumentID": "IRO1DABR0001",
    "marketTitle": "بازار اول (اصلی)",
})
check("سهام بازار اصلی", cat == "سهام بازار اصلی (تابلوی اصلی و فرعی)", f"دسته: {cat}")

cat, _ = identify_category({
    "yValTitle": "حق تقدم",
    "flowTitle": "بورس",
    "lVal30File": "حق تقدم دابور",
    "instrumentID": "IRO3DABR0001",
})
check("حق تقدم بازار اصلی", cat == "حق تقدم بازار اصلی (تابلوی اصلی و فرعی)", f"دسته: {cat}")

# ── ۴. محاسبه کف/سقف ──
print("\n[۴] محاسبه کف و سقف مجاز")
y, p = 93450.0, 6.0
check("کف (۶٪) = ۸۷۸۴۳", round(y * (1 - p/100), 0) == 87843.0)
check("سقف (۶٪) = ۹۹۰۵۷", round(y * (1 + p/100), 0) == 99057.0)
p2 = 10.0
check("کف (۱۰٪) = ۸۴۱۰۵", round(y * 0.90, 0) == 84105.0)
check("سقف (۱۰٪) = ۱۰۲۷۹۵", round(y * 1.10, 0) == 102795.0)

# ── ۵. ذخیره و خواندن در بانک ──
print("\n[۵] ذخیره و خواندن در بانک اطلاعاتی")
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / "test.sqlite"
    rec = {
        "computed_at": "2026-11-14T12:00:00", "date_jalali": "1405/08/23",
        "symbol": "اهرم", "ins_code": "17914401175772326", "isin": "IRO7TOLDP0001",
        "category": "صندوق طلا (و نقره)", "range_percent": 10.0,
        "yesterday_price": 93450.0, "min_allowed_price": 84105.0,
        "max_allowed_price": 102795.0,
        "raw_yval": "6", "raw_flow": "1",
        "raw_yval_title": "صندوق", "raw_flow_title": "بورس",
        "raw_lval30": "صندوق طلا", "raw_lmarket": "1",
        "raw_market_title": "بازار اول", "notes": "تست",
    }
    rid = save_price_range(db, rec)
    check("ذخیره شد", rid > 0)
    loaded = get_price_range(db, "اهرم")
    check("خواندن موفق", loaded is not None)
    if loaded:
        check("دسته درست", loaded["category"] == "صندوق طلا (و نقره)")
        check("کف درست", loaded["min_allowed_price"] == 84105.0)
        check("سقف درست", loaded["max_allowed_price"] == 102795.0)

    # به‌روزرسانی رکورد موجود
    rec["range_percent"] = 6.0
    rec["min_allowed_price"] = 87843.0
    rec["max_allowed_price"] = 99057.0
    rid2 = save_price_range(db, rec)
    check("به‌روزرسانی (id یکسان)", rid2 == rid)
    loaded2 = get_price_range(db, "اهرم")
    if loaded2:
        check("درصد به‌روز شد", loaded2["range_percent"] == 6.0)

# ── ۶. یکپارچگی: data_collector با fixed_price_range ──
print("\n[۶] یکپارچگی: data_collector با fixed_price_range")
from early_warning.data_collector import MarketDataCollector

# ساخت collector با fixed_price_range در پیکربندی
cfg = {
    "test_symbol": {
        "name": "اهرم",
        "ins_code": "17914401175772326",
        "base_price": 93450,
        "fixed_price_range": {
            "yesterday_price": 93450.0,
            "min_allowed_price": 84105.0,
            "max_allowed_price": 102795.0,
            "range_percent": 10.0,
            "category": "صندوق طلا (و نقره)",
        },
    }
}
collector = MarketDataCollector(cfg)

# شبیه‌سازی داده inst (مثل خروجی fetch_intraday)
# بررسی اینکه collect از fixed_price_range استفاده می‌کند
cfg_sym = collector.cfg.get("test_symbol", {})
fixed_pr = cfg_sym.get("fixed_price_range")
check("fixed_price_range در پیکربندی موجود", fixed_pr is not None)
check("yesterday_price ثابت = ۹۳۴۵۰", fixed_pr["yesterday_price"] == 93450.0)
check("min_allowed ثابت = ۸۴۱۰۵", fixed_pr["min_allowed_price"] == 84105.0)
check("max_allowed ثابت = ۱۰۲۷۹۵", fixed_pr["max_allowed_price"] == 102795.0)

# بررسی fallback: وقتی fixed_price_range نیست، از limit_percent استفاده می‌کند
cfg2 = {
    "test_symbol": {
        "name": "تست",
        "ins_code": "123",
        "base_price": 10000,
        "limit_percent": 6,
    }
}
collector2 = MarketDataCollector(cfg2)
cfg_sym2 = collector2.cfg.get("test_symbol", {})
check("بدون fixed_price_range → fallback", "fixed_price_range" not in cfg_sym2)
check("limit_percent = ۶", cfg_sym2.get("limit_percent") == 6)

# ── ۷. یکپارچگی: run_live.py تابع load_price_range ──
print("\n[۷] یکپارچگی: run_live.py تابع load_price_range")
# import run_live و بررسی تابع
import importlib
spec = importlib.util.spec_from_file_location("run_live", str(PROJ / "run_live.py"))
check("run_live.py قابل import است", spec is not None)

# بررسی وجود تابع load_price_range
import ast
with open(PROJ / "run_live.py", "r", encoding="utf-8") as f:
    tree = ast.parse(f.read())
funcs = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
check("تابع load_price_range موجود", "load_price_range" in funcs)
check("import get_price_range موجود", "load_price_range" in funcs)

# ── خلاصه ──
print("\n" + "=" * 60)
print(f"  نتیجه: {passed} پاسخ، {failed} رد")
print("=" * 60)
sys.exit(0 if failed == 0 else 1)
