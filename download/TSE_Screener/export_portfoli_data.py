#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
export_portfoli_data.py — تولید دادهٔ داشبورد «portfoli» از بانک خام

این فایل را داخل ریشهٔ پروژهٔ TSE_Screener کپی کنید و اجرا کنید:
    python export_portfoli_data.py                ← خروجی: portfoli_data.json در همین پوشه
    python export_portfoli_data.py -o C:/tmp/d.json

منبع سطرها: config/symbols.json (همان نمادهایی که raw_collector جمع‌آوری می‌کند).
منبع مقادیر: آخرین ردیفِ امروزِ هر نماد از data/raw/raw_{نماد}.sqlite
ستون‌ها دقیقاً همان هدرهای شیت اصلی گزارش داشبورد (excel_report.py) است؛
شاخص‌های مشتق با همان فرمول‌های پایپ‌لاین (data_collector.py) محاسبه می‌شوند.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# ── فیلدها و هدرها — مطابق شیت اصلی گزارش داشبورد (excel_report.py) ──
GROUPS = [
    ("وضعیت بازار", [
        ("تاریخ شمسی", "date_jalali"),
        ("زمان دقیق", "fetch_hms"),
        ("نماد", "symbol"),
        ("فاز بازار", "market_phase"),
        ("وضعیت نماد", "symbol_status"),
        ("وضعیت داده", "data_status"),
        ("خطای دریافت", "fetch_error"),
    ]),
    ("قیمت‌ها", [
        ("آخرین قیمت", "last_price"),
        ("قیمت پایانی", "close_price"),
        ("اولین قیمت", "open_price"),
        ("قیمت دیروز", "yesterday_price"),
        ("بالاترین روز", "daily_high"),
        ("پایین‌ترین روز", "daily_low"),
        ("کف مجاز", "min_allowed_price"),
        ("سقف مجاز", "max_allowed_price"),
    ]),
    ("بهترین قیمت و مجموع", [
        ("بهترین خرید", "best_bid"),
        ("حجم خرید", "bid_volume"),
        ("بهترین فروش", "best_ask"),
        ("حجم فروش", "ask_volume"),
        ("تعداد سفارش خرید", "buy_order_count"),
        ("تعداد سفارش فروش", "sell_order_count"),
    ]),
    ("پنج ردیف خرید", [
        ("bid_price_1", "bid_price_1"), ("bid_vol_1", "bid_vol_1"), ("bid_count_1", "bid_count_1"),
        ("bid_price_2", "bid_price_2"), ("bid_vol_2", "bid_vol_2"), ("bid_count_2", "bid_count_2"),
        ("bid_price_3", "bid_price_3"), ("bid_vol_3", "bid_vol_3"), ("bid_count_3", "bid_count_3"),
        ("bid_price_4", "bid_price_4"), ("bid_vol_4", "bid_vol_4"), ("bid_count_4", "bid_count_4"),
        ("bid_price_5", "bid_price_5"), ("bid_vol_5", "bid_vol_5"), ("bid_count_5", "bid_count_5"),
    ]),
    ("پنج ردیف فروش", [
        ("ask_price_1", "ask_price_1"), ("ask_vol_1", "ask_vol_1"), ("ask_count_1", "ask_count_1"),
        ("ask_price_2", "ask_price_2"), ("ask_vol_2", "ask_vol_2"), ("ask_count_2", "ask_count_2"),
        ("ask_price_3", "ask_price_3"), ("ask_vol_3", "ask_vol_3"), ("ask_count_3", "ask_count_3"),
        ("ask_price_4", "ask_price_4"), ("ask_vol_4", "ask_vol_4"), ("ask_count_4", "ask_count_4"),
        ("ask_price_5", "ask_price_5"), ("ask_vol_5", "ask_vol_5"), ("ask_count_5", "ask_count_5"),
    ]),
    ("تجمعی", [
        ("حجم کل", "total_volume"),
        ("ارزش کل", "total_value"),
        ("تعداد معامله کل", "total_count"),
        ("حجم مبنا", "volume_basis"),
        ("حجم بازه", "interval_volume"),
        ("ارزش بازه", "interval_value"),
        ("تعداد بازه", "interval_count"),
    ]),
    ("حقیقی/حقوقی", [
        ("خریداران حقیقی", "real_buy_count"),
        ("حجم خرید حقیقی", "real_buy_volume"),
        ("ارزش خرید حقیقی", "real_buy_value"),
        ("فروشندگان حقیقی", "real_sell_count"),
        ("حجم فروش حقیقی", "real_sell_volume"),
        ("ارزش فروش حقیقی", "real_sell_value"),
        ("خریداران حقوقی", "legal_buy_count"),
        ("حجم خرید حقوقی", "legal_buy_volume"),
        ("ارزش خرید حقوقی", "legal_buy_value"),
        ("فروشندگان حقوقی", "legal_sell_count"),
        ("حجم فروش حقوقی", "legal_sell_volume"),
        ("ارزش فروش حقوقی", "legal_sell_value"),
        ("حجم خرید حقیقی بازه", "interval_real_buy_volume"),
        ("حجم فروش حقیقی بازه", "interval_real_sell_volume"),
    ]),
    ("شاخص‌های مشتق", [
        ("قدرت خریدار", "buyer_power"),
        ("سرانه خرید", "per_capita_buy_real"),
        ("سرانه فروش", "per_capita_sell_real"),
        ("ورود/خروج پول حقیقی", "real_money_flow"),
        ("نسبت پول حقیقی", "real_money_flow_ratio"),
        # فرمول‌ها مطابق فایل dashboard.xlsx — شیت dashboard
        # (ورود/خروج پول حقیقی و ارزش خرید/فروش حقیقی همین‌جا تعریف شده‌اند؛
        #  ستون تکراری برای همان فیلد ممنوع — انتخابگر دوباره نشانشان می‌داد)
        ("نسبت ورود پول ٪", "money_flow_ratio_pct"),
        ("نسبت ۵ روزه ورود پول ٪", "mf_ratio_5d_pct"),
        ("نسبت ۳۰ روزه ورود پول ٪", "mf_ratio_30d_pct"),
        ("میانگین قدرت مطلق ورود پول ۵ روز اخیر (ریال)", "flow5_avg_abs"),
        ("میانگین قدرت مطلق ورود پول ۳۰ روز اخیر (ریال)", "flow30_avg_abs"),
        ("نسبت ۵ روزه حجم ٪", "volume_ratio_5d_pct"),
        ("نسبت ۳۰ روزه حجم ٪", "volume_ratio_30d_pct"),
        ("از نظر مبلغ خرید یا فروش", "buy_sell_amount_side"),
        ("نسبت تعداد خریدار به فروشنده", "buyer_seller_count_ratio"),
        ("امتیاز واکنش قیمت", "price_reaction_score"),
    ]),
    # گروه «تاریخچه» — همان ستون‌های داشبورد سابقهٔ نمادها؛ حجم روز (حجم کل) و
    # قدرت خرید روز (قدرت خریدار) از قبل در گروه‌های دیگر هستند و تکرار نمی‌شوند
    ("تاریخچه", [
        ("میانگین ۵ روزه ورود پول (ریال)", "flow_avg5_rial"),
        ("میانگین ۱۰ روزه ورود پول (ریال)", "flow_avg10_rial"),
        ("میانگین ۲۰ روزه ورود پول (ریال)", "flow_avg20_rial"),
        ("میانگین ۳۰ روزه ورود پول (ریال)", "flow_avg30_rial"),
        ("میانگین ۵ روزه حجم (سهم)", "vol_avg5"),
        ("میانگین ۱۰ روزه حجم (سهم)", "vol_avg10"),
        ("میانگین ۲۰ روزه حجم (سهم)", "vol_avg20"),
        ("میانگین ۳۰ روزه حجم (سهم)", "vol_avg30"),
        ("میانگین ۵ روزه ارزش معاملات", "val_avg5"),
        ("میانگین ۱۰ روزه ارزش معاملات", "val_avg10"),
        ("میانگین ۲۰ روزه ارزش معاملات", "val_avg20"),
        ("میانگین ۳۰ روزه ارزش معاملات", "val_avg30"),
        ("میانگین قدرت خرید ۵ روز", "buy_power_avg5"),
        ("میانگین قدرت خرید ۱۰ روز", "buy_power_avg10"),
        ("میانگین قدرت خرید ۲۰ روز", "buy_power_avg20"),
        ("میانگین قدرت خرید ۳۰ روز", "buy_power_avg30"),
    ]),
    ("تغییرات", [
        ("اختلاف کدهای خرید و فروش حقیقی", "code_diff"),
        ("اختلاف سرانه خرید و فروش حقیقی", "per_capita_diff"),
        ("تفاوت ارزش خرید و فروش حقیقی", "real_value_diff"),
        ("تفاوت ارزش خرید و فروش حقوقی", "legal_value_diff"),
    ]),
    ("روند جلسه", [
        ("میانگین نسبت ورود پول (N نمادهٔ اخیر)", "flow_ratio_recent_avg"),
        ("میانگین وزنی ارزش معاملات از ابتدای جلسه", "avg_session_total_value"),
        ("میانگین وزنی سرانه خرید از ابتدای جلسه", "avg_session_per_capita_buy"),
        ("میانگین وزنی سرانه فروش از ابتدای جلسه", "avg_session_per_capita_sell"),
        ("میانگین وزنی قدرت خرید از ابتدای جلسه", "avg_session_buyer_power"),
        ("میانگین وزنی تعداد خریدار حقیقی از ابتدای جلسه", "avg_session_real_buy_count"),
        ("میانگین وزنی تعداد فروشنده حقیقی از ابتدای جلسه", "avg_session_real_sell_count"),
        ("میانگین وزنی تعداد خریدار حقوقی از ابتدای جلسه", "avg_session_legal_buy_count"),
        ("میانگین وزنی تعداد فروشنده حقوقی از ابتدای جلسه", "avg_session_legal_sell_count"),
        ("میانگین وزنی ارزش خرید حقیقی از ابتدای جلسه", "avg_session_real_buy_value"),
        ("میانگین وزنی ارزش فروش حقیقی از ابتدای جلسه", "avg_session_real_sell_value"),
        ("روند ورود پول از ابتدای جلسه", "trend_flow_session"),
        ("روند ورود پول (N نمادهٔ اخیر)", "trend_flow_recent"),
        ("روند قدرت خریدار از ابتدای جلسه", "trend_power_session"),
        ("روند قدرت خریدار (N نمادهٔ اخیر)", "trend_power_recent"),
        ("واژگونی روند", "trend_divergence"),
    ]),
    ("کیفیت داده", [
        ("داده کامل", "completeness"),
        ("فیلدهای مفقود", "missing_count"),
    ]),
    ("نوسان", [
        ("٪ نوسان لحظه‌ای", "pct_last"),
        ("٪ نوسان پایانی", "pct_close"),
    ]),
]

ALL_FIELDS = [en for _, cols in GROUPS for _, en in cols]

# ── منبع هر ستون — برای سطر «نام فیلد بانک» در هدر اکسل و شیت راهنما ──
# مقدار = (نام فیلد بانک خام raw_snapshots یا API، توضیح/فرمول یک‌خطی)
# ستون‌های محاسبه‌ای به‌جای نام فیلد، فرمول مختصر دارند؛ ستون‌های مستقیم
# نام ستون بانک (= همان نام کلید API بعد از مپ raw_collector) را نشان می‌دهند.
FIELD_SOURCES = {
    "date_jalali": ("date_jalali", "شناسهٔ ثبت collector — تاریخ شمسی روز دریافت"),
    "fetch_hms": ("fetch_hms", "شناسهٔ ثبت collector — ساعت دریافت"),
    "symbol": ("symbol", "شناسهٔ ثبت collector — نماد از config/symbols.json"),
    "market_phase": ("—", "محاسبه: بازهٔ ساعت تهران در pre_open/continuous از symbols.json"),
    "symbol_status": ("api_symbol_status", "مستقیم از API — instrumentState.cEtavalTitle"),
    "data_status": ("—", "محاسبه: کامل/ناقص از شمار فیلدهای مفقود کلیدی"),
    "fetch_error": ("—", "محاسبه: خطای endpoint در همان نمونه"),
    "last_price": ("pl", "مستقیم — pDrCotVal"),
    "close_price": ("pc", "مستقیم — pClosing"),
    "open_price": ("pf", "مستقیم — priceFirst"),
    "yesterday_price": ("py", "مستقیم — priceYesterday"),
    "daily_high": ("pmax", "مستقیم — priceMax"),
    "daily_low": ("pmin", "مستقیم — priceMin"),
    "min_allowed_price": ("—", "محاسبه: کف/سقف مجاز از early_warning/price_range.py"),
    "max_allowed_price": ("—", "محاسبه: کف/سقف مجاز از early_warning/price_range.py"),
    "best_bid": ("pd1", "مستقیم — pMeDem ردیف ۱"),
    "bid_volume": ("qd1", "مستقیم — qTitMeDem ردیف ۱"),
    "best_ask": ("po1", "مستقیم — pMeOf ردیف ۱"),
    "ask_volume": ("qo1", "مستقیم — qTitMeOf ردیف ۱"),
    "buy_order_count": ("zd1", "مستقیم — zOrdMeDem ردیف ۱"),
    "sell_order_count": ("zo1", "مستقیم — zOrdMeOf ردیف ۱"),
    "total_volume": ("tvol", "مستقیم — qTotTran5J"),
    "total_value": ("tval", "مستقیم — qTotCap (ریال)"),
    "total_count": ("tno", "مستقیم — zTotTran"),
    "real_buy_count": ("buy_counti", "مستقیم — (ct).Buy_CountI"),
    "real_buy_volume": ("buy_i_volume", "مستقیم — (ct).Buy_I_Volume"),
    "real_sell_count": ("sell_counti", "مستقیم — (ct).Sell_CountI"),
    "real_sell_volume": ("sell_i_volume", "مستقیم — (ct).Sell_I_Volume"),
    "legal_buy_count": ("buy_countn", "مستقیم — (ct).Buy_CountN"),
    "legal_buy_volume": ("buy_n_volume", "مستقیم — (ct).Buy_N_Volume"),
    "legal_sell_count": ("sell_countn", "مستقیم — (ct).Sell_CountN"),
    "legal_sell_volume": ("sell_n_volume", "مستقیم — (ct).Sell_N_Volume"),
    "real_buy_value": ("—", "محاسبه: buy_i_volume × قیمت (pc یا pl)"),
    "real_sell_value": ("—", "محاسبه: sell_i_volume × قیمت (pc یا pl)"),
    "code_diff": ("—", "محاسبه: تعداد خریدار حقیقی − تعداد فروشنده حقیقی (کدهای خرید−فروش)"),
    "per_capita_diff": ("—", "محاسبه: سرانه خرید حقیقی − سرانه فروش حقیقی (ریال)"),
    "real_value_diff": ("—", "محاسبه: ارزش خرید حقیقی − ارزش فروش حقیقی (هم‌مقدار ورود پول ریالی)"),
    "legal_value_diff": ("—", "محاسبه: ارزش خرید حقوقی − ارزش فروش حقوقی (ریال)"),
    "buyer_power": ("—", "محاسبه: (خرید حقیقی÷تعداد خریدار حقیقی) ÷ (فروش حقیقی÷تعداد فروشنده حقیقی)"),
    "per_capita_buy_real": ("—", "محاسبه: buy_i_volume ÷ buy_counti (سرانه خرید)"),
    "per_capita_sell_real": ("—", "محاسبه: sell_i_volume ÷ sell_counti (سرانه فروش)"),
    "real_money_flow": ("—", "محاسبه: (buy_i_volume − sell_i_volume) × قیمت"),
    "real_money_flow_ratio": ("—", "محاسبه: (خرید حقیقی − فروش حقیقی) ÷ (خرید حقیقی + فروش حقیقی) — سهم خالص حقیقی از گردش خودش، بین −۱ تا +۱"),
    "money_flow_ratio_pct": ("—", "محاسبه: ورود پول ÷ trade_value × ۱۰۰ (درصد)"),
    "mf_ratio_5d_pct": ("—", "محاسبه: ورود پول امروز ÷ میانگین |ورود پول| ۵ روز قبل × ۱۰۰"),
    "mf_ratio_30d_pct": ("—", "محاسبه: ورود پول امروز ÷ میانگین |ورود پول| ۳۰ روز قبل × ۱۰۰"),
    "flow5_avg_abs": ("—", "محاسبه: میانگین |(خرید−فروش حقیقی) × قیمت پایانی| در ۵ روز قبل"),
    "flow30_avg_abs": ("—", "محاسبه: میانگین |(خرید−فروش حقیقی) × قیمت پایانی| در ۳۰ روز قبل"),
    "flow_avg5_rial": ("—", "محاسبهٔ وزنی: (Σ ارزش خرید − Σ ارزش فروش حقیقی سایت) ÷ تعداد روز، در ۵ روز قبل (پنجرهٔ کامل)"),
    "flow_avg10_rial": ("—", "محاسبه: همان با ۱۰ روز قبل"),
    "flow_avg20_rial": ("—", "محاسبه: همان با ۲۰ روز قبل"),
    "flow_avg30_rial": ("—", "محاسبه: همان با ۳۰ روز قبل"),
    "vol_avg5": ("—", "محاسبهٔ وزنی: Σ حجم معاملات ÷ تعداد روز، در ۵ روز قبل (پنجرهٔ کامل)"),
    "vol_avg10": ("—", "محاسبه: همان با ۱۰ روز قبل"),
    "vol_avg20": ("—", "محاسبه: همان با ۲۰ روز قبل"),
    "vol_avg30": ("—", "محاسبه: همان با ۳۰ روز قبل"),
    "val_avg5": ("—", "محاسبهٔ وزنی: Σ ارزش معاملات روزانه (tval) ÷ تعداد روز، در ۵ روز قبل (پنجرهٔ کامل)"),
    "val_avg10": ("—", "محاسبه: همان با ۱۰ روز قبل"),
    "val_avg20": ("—", "محاسبه: همان با ۲۰ روز قبل"),
    "val_avg30": ("—", "محاسبه: همان با ۳۰ روز قبل"),
    "buy_power_avg5": ("—", "محاسبهٔ وزنی: (Σ ارزش خرید ÷ Σ خریداران) ÷ (Σ ارزش فروش ÷ Σ فروشندگان) در ۵ روز قبل (پنجرهٔ کامل)"),
    "buy_power_avg10": ("—", "محاسبه: همان با ۱۰ روز قبل"),
    "buy_power_avg20": ("—", "محاسبه: همان با ۲۰ روز قبل"),
    "buy_power_avg30": ("—", "محاسبه: همان با ۳۰ روز قبل"),
    "volume_ratio_5d_pct": ("—", "محاسبه: حجم امروز ÷ میانگین حجم ۵ روز قبل × ۱۰۰"),
    "volume_ratio_30d_pct": ("—", "محاسبه: حجم امروز ÷ میانگین حجم ۳۰ روز قبل × ۱۰۰"),
    "buy_sell_amount_side": ("—", "محاسبه: خرید/فروش/تعادل از مقایسهٔ ارزش خرید و فروش حقیقی"),
    "buyer_seller_count_ratio": ("—", "محاسبه: buy_counti ÷ sell_counti"),
    "price_reaction_score": ("—", "محاسبه: جای آخرین قیمت در بازهٔ کف تا سقف مجاز (۰ تا ۱۰۰)"),
    "pct_last": ("plp", "مستقیم — plp (بانک)؛ نبود → محاسبه از pl/py"),
    "pct_close": ("pcp", "مستقیم — pcp (بانک)؛ نبود → محاسبه از pc/py"),
    "flow_ratio_recent_avg": ("—", "محاسبه: میانگین نسبت ورود پول ٪ در N نمونهٔ اخیر"),
    "avg_session_total_value": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی ارزش معاملات، وزن هر بازه = ارزش معاملات همان بازه"),
    "avg_session_per_capita_buy": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی سرانه خرید حقیقی با وزن ارزش معاملات بازه"),
    "avg_session_per_capita_sell": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی سرانه فروش حقیقی با وزن ارزش معاملات بازه"),
    "avg_session_buyer_power": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی نسبت قدرت (سپس علامت‌دار) با وزن ارزش معاملات بازه"),
    "avg_session_real_buy_count": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی تعداد خریدار حقیقی با وزن ارزش معاملات بازه"),
    "avg_session_real_sell_count": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی تعداد فروشنده حقیقی با وزن ارزش معاملات بازه"),
    "avg_session_legal_buy_count": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی تعداد خریدار حقوقی با وزن ارزش معاملات بازه"),
    "avg_session_legal_sell_count": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی تعداد فروشنده حقوقی با وزن ارزش معاملات بازه"),
    "avg_session_real_buy_value": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی ارزش خرید حقیقی (حجم×قیمت) با وزن ارزش معاملات بازه"),
    "avg_session_real_sell_value": ("—", "میانگین وزنی از ابتدای جلسه: منحنی تجمیعی ارزش فروش حقیقی (حجم×قیمت) با وزن ارزش معاملات بازه"),
    "trend_flow_session": ("—", "محاسبه: شیب رگرسیون سری ورود پول کل جلسه، نرمال به دامنه — آستانه ±۰٫۱۵/±۰٫۵"),
    "trend_flow_recent": ("—", "محاسبه: همان، فقط روی N نمونهٔ اخیر"),
    "trend_power_session": ("—", "محاسبه: همان، روی سری قدرت خریدار کل جلسه"),
    "trend_power_recent": ("—", "محاسبه: همان، روی سری قدرت خریدار N نمونهٔ اخیر"),
    "trend_divergence": ("—", "محاسبه: جهت روند اخیر مخالف جهت روند جلسه (مبنای هایلایت سطر)"),
}
for i in range(1, 6):
    FIELD_SOURCES[f"bid_price_{i}"] = (f"pd{i}", f"مستقیم — pMeDem ردیف {i}")
    FIELD_SOURCES[f"bid_vol_{i}"] = (f"qd{i}", f"مستقیم — qTitMeDem ردیف {i}")
    FIELD_SOURCES[f"bid_count_{i}"] = (f"zd{i}", f"مستقیم — zOrdMeDem ردیف {i}")
    FIELD_SOURCES[f"ask_price_{i}"] = (f"po{i}", f"مستقیم — pMeOf ردیف {i}")
    FIELD_SOURCES[f"ask_vol_{i}"] = (f"qo{i}", f"مستقیم — qTitMeOf ردیف {i}")
    FIELD_SOURCES[f"ask_count_{i}"] = (f"zo{i}", f"مستقیم — zOrdMeOf ردیف {i}")

# ستون‌های محاسبه‌ای «بی‌نام» نمی‌مانند — نام قراردادی calc_<فیلد> می‌گیرند
# تا در سطر دوم هدر اکسل و شیت راهنما قابل ارجاع باشند.
for _k, _v in FIELD_SOURCES.items():
    if _v[0] == "—":
        FIELD_SOURCES[_k] = (f"calc_{_k}", _v[1])

DEFAULT_VISIBLE = [
    "symbol", "date_jalali", "fetch_hms", "market_phase", "symbol_status",
    "last_price", "close_price", "pct_last", "pct_close",
    "best_bid", "bid_volume", "best_ask", "ask_volume",
    "total_volume", "total_value",
    "buyer_power", "per_capita_buy_real", "per_capita_sell_real",
    "real_money_flow", "real_money_flow_ratio",
    "money_flow_ratio_pct", "mf_ratio_5d_pct", "volume_ratio_5d_pct",
    "volume_ratio_30d_pct", "buy_sell_amount_side",
    "buyer_seller_count_ratio", "price_reaction_score", "data_status",
    "trend_flow_session", "trend_flow_recent", "trend_divergence",
    # گروه «تاریخچه» — پیش‌فرض روشن (درخواست کاربر؛ دکمهٔ گروه برای نمایش/حذف سریع)
    "flow_avg5_rial", "flow_avg10_rial", "flow_avg20_rial", "flow_avg30_rial",
    "vol_avg5", "vol_avg10", "vol_avg20", "vol_avg30",
    "buy_power_avg5", "buy_power_avg10", "buy_power_avg20", "buy_power_avg30",
]

TREND_WINDOW_DEFAULT = 20

TREND_SCORE = {"قوی صعودی": 2, "صعودی": 1, "خنثی": 0, "نزولی": -1, "قوی نزولی": -2}


def _raw_phase(trading_hours: dict, hm: str) -> str:
    """فاز بازار از ساعت معاملات symbols.json — همان منطق run_live."""
    for key, val in (("pre_open", "پیش‌گشایش"), ("continuous", "پیوسته")):
        w = (trading_hours or {}).get(key) or []
        if len(w) == 2 and w[0] <= hm <= w[1]:
            return val
    return "بسته"


_DAILY_COLS = ("date_jalali, buy_i_value, sell_i_value, "
               "buy_i_volume, sell_i_volume, "
               "buy_counti, sell_counti, pc, tvol, tval")


def _signed_power(ratio: float | None) -> float | None:
    """قدرت خرید علامت‌دار — قرارداد نمایش بازار:
    نسبت ≥ ۱ ← همان عدد مثبت (خریدار غالب)؛ نسبت < ۱ ← معکوس با علامت منفی
    (فروشنده غالب)، مثلاً نسبت ۰٫۸۴ ← ‎−۱٫۱۹. قدرت مطلق همیشه ≥ ۱ است و
    مقدارهای بین ‎−۱ و ‎+۱ هرگز ظاهر نمی‌شوند."""
    if ratio is None or ratio <= 0:
        return None
    return ratio if ratio >= 1 else -1.0 / ratio


def _daily_rows(db_path: Path, today: str | None, symbol: str | None = None,
                table: str = "raw_snapshots") -> list:
    """سری روزانهٔ ورود پول/حجم/تعدادها — نزولی، بدون امروز.

    raw_snapshots چند نمونه در روز دارد (گروه‌بندی بر id)؛ history_daily
    یک ردیف در روز برای همهٔ نمادها (بدون id — با فیلتر نماد).
    """
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        if table == "history_daily":
            q = f"SELECT {_DAILY_COLS} FROM history_daily"
            args: list = []
            if symbol:
                q += " WHERE symbol = ?"
                args.append(symbol)
            q += " ORDER BY date_jalali DESC"
        else:
            q = (f"SELECT {_DAILY_COLS} FROM {table} WHERE id IN "
                 f"(SELECT MAX(id) FROM {table} GROUP BY date_jalali) "
                 "ORDER BY date_jalali DESC")
            args = []
        rows = con.execute(q, args).fetchall()
    finally:
        con.close()
    if today:
        # فقط روزهای «قبل» از تاریخ مبنای payload — امروز و روزهای بعدتر حذف؛
        # بانک سابقه ممکن است روزهای جدیدتری از نمونهٔ لایو داشته باشد
        rows = [r for r in rows if r["date_jalali"] < today]
    return rows


def _basis_vals(b, raw_db: Path) -> dict:
    """مقادیر «جلسهٔ قبل» برای سطر دوم داشبورد لایو — از ردیف مبنای روزهای قبل (b).

    فرمول‌ها عیناً همان شاخص‌های لحظه‌ایِ _compute_row است (سرانه، قدرت
    علامت‌دار، ورود پول)؛ فقط ورود پولِ روز مبنا مستقیماً از ارزش‌های روزانهٔ
    بانک سابقه (buy_i_value/sell_i_value) می‌آید که دقیق‌تر از حجم×قیمت است.
    ارزش معاملات و حجم روز مبنا از ستون‌های روزانهٔ بانک سابقه (tval/tvol)
    می‌آیند؛ نبودِ tval → آخرین نمونهٔ خام همان روز از بانک لایو.
    کلیدهای بی‌مقدار در خروجی نمی‌آیند تا payload سبک بماند.
    """
    out: dict = {}
    get = lambda k: b[k] if k in b.keys() else None  # noqa: E731  (Row → مقدار امن)
    pc, biv, siv = get("pc"), get("buy_i_volume"), get("sell_i_volume")
    bic, bsc = get("buy_counti"), get("sell_counti")
    out["close_price"] = int(pc) if pc else None
    out["real_buy_count"] = int(bic) if bic else None
    out["real_sell_count"] = int(bsc) if bsc else None
    if biv is not None and bic is not None:
        out["per_capita_buy_real"] = round(biv / max(bic, 1), 0)
    if siv is not None and bsc is not None:
        out["per_capita_sell_real"] = round(siv / max(bsc, 1), 0)
    if biv is not None and siv is not None and bsc and siv / max(bsc, 1):
        bp = _signed_power((biv / max(bic or 0, 1)) / (siv / max(bsc, 1)))
        if bp is not None:
            out["buyer_power"] = round(bp, 2)
    if bic or bsc:  # ورود پول — ارزش روزانه دقیق‌تر؛ نبود → حجم×قیمتِ پایانی
        bivv, sivv = get("buy_i_value"), get("sell_i_value")
        if bivv is not None and sivv is not None:
            out["real_money_flow"] = int(bivv - sivv)
        elif biv is not None and siv is not None and pc:
            out["real_money_flow"] = int((biv - siv) * pc)
        # نسبت ورود پول حقیقی روز مبنا — سهم خالص حقیقی از گردش خودِ حقیقی‌ها
        if bivv is not None and sivv is not None and (bivv or sivv):
            out["real_money_flow_ratio"] = round((bivv - sivv) / (bivv + sivv), 4)
        elif biv is not None and siv is not None and (biv or siv):
            out["real_money_flow_ratio"] = round((biv - siv) / (biv + siv), 4)
    tv = get("tval")          # ارزش معاملات روزانهٔ بانک سابقه (tval)
    tvol_b = get("tvol")      # حجم روزانهٔ بانک سابقه — فیلد «حجم» جلسهٔ قبل
    out["total_volume"] = int(tvol_b) if tvol_b else None
    if tv:  # ارزش معاملات روز مبنا — tval روزانهٔ بانک سابقه (رسمی TSETMC)
        out["total_value"] = int(tv)
    else:
        d = get("date_jalali")
        if d:  # نبود در بانک سابقه → آخرین نمونهٔ خام همان روز از بانک لایو
            try:
                con = sqlite3.connect(str(raw_db))
                try:
                    r = con.execute("SELECT tval FROM raw_snapshots WHERE date_jalali = ? "
                                    "ORDER BY id DESC LIMIT 1", (d,)).fetchone()
                    out["total_value"] = int(r[0]) if r and r[0] else None
                finally:
                    con.close()
            except sqlite3.Error:
                out["total_value"] = None
    return {k: v for k, v in out.items() if v is not None}


def _daily_stats(db_path: Path, today: str | None, symbol: str | None = None) -> dict:
    """میانگین‌های وزنی ۵/۱۰/۲۰/۳۰ روزه — جمع تجمیعی اجزا روی پنجرهٔ روزهای قبل
    (نه میانگین سادهٔ مقادیر روزانه):

    ورود پول وزنی N روزه = (Σ ارزش خرید حقیقی − Σ ارزش فروش حقیقی) ÷ تعداد روز.
    حجم وزنی N روزه = Σ حجم ÷ تعداد روز.
    قدرت خرید وزنی N روزه = (Σ ارزش خرید ÷ Σ خریداران) ÷ (Σ ارزش فروش ÷ Σ فروشندگان).
    روزِ نامعتبر (اجزای ناقص) از پنجره رد می‌شود و نزدیک‌ترین روزِ معتبرِ قبل
    جایگزین می‌شود؛ پنجرهٔ ناقص = None تا ستون‌های ۵/۱۰/۲۰/۳۰ تکراری نشوند.
    پنجره فقط «روزهای قبل» است، امروز داخل میانگین نمی‌آید. میانگین‌های مطلق
    (مخرج نسبت‌های ٪) مثل قبل جزئی هم می‌پذیرند.
    مبنای داده بانک سابقهٔ ۴۰۰ روزهٔ history.sqlite است؛ نبود → بانک لایو همان نماد.
    """
    if symbol is None:
        symbol = db_path.stem.removeprefix("raw_")
    rows = None
    hdb = db_path.parent / "history.sqlite"
    if hdb != db_path and hdb.exists():
        rows = _daily_rows(hdb, today, symbol, table="history_daily") or None
    if rows is None:
        rows = _daily_rows(db_path, today)
    me, vols, fdays, vdays, pdays, aldays = [], [], [], [], [], []
    for r in rows[:60]:
        bv, sv = r["buy_i_value"], r["sell_i_value"]
        bc, sc = r["buy_counti"], r["sell_counti"]
        me.append((bv - sv) if (bv is not None and sv is not None) else None)
        vols.append(float(r["tvol"] or 0))
        # اجزای خام برای میانگین وزنی — روزِ معتبر هر متریک = روزی که همهٔ
        # اجزای فرمولش موجود باشد؛ سطرها تازه‌به‌قدیم‌اند (ابتدای لیست = اخیر)
        fdays.append({"bv": bv or 0, "sv": sv or 0}
                     if (bv is not None or sv is not None) else None)
        vdays.append({"t": float(r["tvol"])} if r["tvol"] is not None else None)
        aldays.append({"v": float(r["tval"])} if r["tval"] is not None else None)
        pdays.append({"bv": bv, "sv": sv, "bc": bc, "sc": sc}
                     if (bv and sv and bc and sc) else None)
    f_abs = [abs(x) for x in me if x is not None]

    def _agg(xs, n):
        # پنجرهٔ وزنی n روزه — جمع تجمیعی اجزا روی n روزِ معتبرِ قبل؛
        # پنجرهٔ ناقص = None. خروجی: (جمع اجزا، تعداد روز) یا None.
        xs = [x for x in xs[:n * 2] if x is not None][:n]
        if len(xs) < n:
            return None
        keys = xs[0].keys()
        return ({k: sum(x[k] or 0 for x in xs) for k in keys}, len(xs))

    aggf = {n: _agg(fdays, n) for n in (5, 10, 20, 30)}
    aggv = {n: _agg(vdays, n) for n in (5, 10, 20, 30)}
    agga = {n: _agg(aldays, n) for n in (5, 10, 20, 30)}
    aggp = {n: _agg(pdays, n) for n in (5, 10, 20, 30)}

    def _flow_w(n):
        # ورود پول وزنی = (Σ ارزش خرید − Σ ارزش فروش) ÷ تعداد روز
        a = aggf[n]
        return (a[0]["bv"] - a[0]["sv"]) / a[1] if a else None

    def _vol_w(n):
        a = aggv[n]
        return a[0]["t"] / a[1] if a else None

    def _val_w(n):
        # میانگین ارزش معاملات وزنی = Σ ارزش معاملات روزانه (tval) ÷ تعداد روز
        a = agga[n]
        return a[0]["v"] / a[1] if a else None

    def _pow_w(n):
        # قدرت خرید وزنی از جمع‌ها — بعد علامت‌دار؛ نتیجه همیشه خارج ‎(−۱، +۱)‎
        a = aggp[n]
        if not a:
            return None
        s = a[0]
        if not (s["bc"] and s["sc"] and s["sv"]):
            return None
        return _signed_power((s["bv"] / s["bc"]) / (s["sv"] / s["sc"]))

    f5, v5, v30 = f_abs[:5], vols[:5], vols[:30]
    return {
        "flow5_avg_abs": sum(f5) / len(f5) if f5 else 0.0,
        "flow30_avg_abs": sum(f_abs) / len(f_abs) if f_abs else 0.0,
        "vol5_avg": sum(v5) / len(v5) if v5 else 0.0,
        "vol30_avg": sum(v30) / len(v30) if v30 else 0.0,
        "flow_avg5_rial": _flow_w(5),
        "flow_avg10_rial": _flow_w(10),
        "flow_avg20_rial": _flow_w(20),
        "flow_avg30_rial": _flow_w(30),
        "vol_avg5": _vol_w(5),
        "vol_avg10": _vol_w(10),
        "vol_avg20": _vol_w(20),
        "vol_avg30": _vol_w(30),
        "val_avg5": _val_w(5),
        "val_avg10": _val_w(10),
        "val_avg20": _val_w(20),
        "val_avg30": _val_w(30),
        "buy_power_avg5": _pow_w(5),
        "buy_power_avg10": _pow_w(10),
        "buy_power_avg20": _pow_w(20),
        "buy_power_avg30": _pow_w(30),
        # جدیدترین جلسهٔ داخل میانگین‌ها = آخرین روزِ بانک قبل از سطر لایو —
        # برای برچسب سطر دوم داشبورد لایو («میانگین‌های جلسهٔ قبل — تا …»)
        "basis_date": rows[0]["date_jalali"] if rows else None,
        # مقادیر ۸ فیلدِ جلسهٔ قبل برای سطر دوم داشبورد لایو (گروه «جلسهٔ قبل»)
        "basis_vals": _basis_vals(rows[0], db_path) if rows else None,
        "days": len(rows),
    }


def _daily_params(symbol: str, yesterday_price: float, root: Path) -> dict | None:
    """کف/سقف مجاز از price_range.py پروژه (اگر در کنار همین اسکریپت باشد)."""
    try:
        sys.path.insert(0, str(root))
        from early_warning.price_range import compute_daily_params  # type: ignore
        return compute_daily_params(symbol, float(yesterday_price), root / "config")
    except Exception:
        return None


def _trend_label(values) -> tuple[str | None, float | None]:
    """برچسب روند یک سری زمانی — شیب رگرسیون خطی نرمال‌شده به دامنهٔ نوسان سری.

    خروجی: (برچسب، norm) — norm عدد خام همین برچسب است تا کنار توصیف نمایش داده شود.
    norm = کل تغییرِ پیش‌بینی‌شدهٔ روند در طول پنجره ÷ دامنهٔ نوسان؛
    خط صاف = ۱٫۰. آستانه‌ها: |norm|≥۰٫۵ قوی، ≥۰٫۱۵ ملایم، کمتر = خنثی.
    """
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < 4:
        return None, None
    mx = (n - 1) / 2
    my = sum(vals) / n
    sxx = sum((i - mx) ** 2 for i in range(n))
    sxy = sum((i - mx) * (v - my) for i, v in enumerate(vals))
    slope = sxy / sxx if sxx else 0.0
    span = max(vals) - min(vals)
    norm = slope * (n - 1) / span if span > 1e-12 else 0.0
    lab = ("قوی صعودی" if norm >= 0.5 else "صعودی" if norm >= 0.15
           else "قوی نزولی" if norm <= -0.5 else "نزولی" if norm <= -0.15 else "خنثی")
    return lab, round(norm, 2)


def _trends_from_series(flow, power, window: int = TREND_WINDOW_DEFAULT) -> dict:
    """روند ورود پول و قدرت خریدار از سری‌های نمونه‌ای — بین export و شبیه‌سازی مشترک.

    واژگونی = جهت روند پنجرهٔ اخیر معکوس جهت روند کل جلسه (مثلاً جلسه صعودی ولی
    N نمادهٔ اخیر نزولی) — مبنای هایلایت کل سطر در داشبورد.
    """
    w = max(3, int(window))
    fs, ps = list(flow)[-w:], list(power)[-w:]
    f_ses, f_ses_n = _trend_label(flow)
    f_rec, f_rec_n = _trend_label(fs)
    p_ses, p_ses_n = _trend_label(power)
    p_rec, p_rec_n = _trend_label(ps)
    out = {
        "trend_flow_session": f_ses,
        "trend_flow_session_val": f_ses_n,
        "trend_flow_recent": f_rec,
        "trend_flow_recent_val": f_rec_n,
        "trend_power_session": p_ses,
        "trend_power_session_val": p_ses_n,
        "trend_power_recent": p_rec,
        "trend_power_recent_val": p_rec_n,
        "flow_ratio_recent_avg": round(sum(fs) / len(fs), 2) if fs else None,
    }
    names, kind = [], None
    for name, ses, rec in (("ورود پول", out["trend_flow_session"], out["trend_flow_recent"]),
                           ("قدرت خریدار", out["trend_power_session"], out["trend_power_recent"])):
        s, r = TREND_SCORE.get(ses, 0), TREND_SCORE.get(rec, 0)
        if s and r and (s > 0) != (r > 0):
            names.append(name)
            if r < 0:
                kind = "down"   # تضعیف روند صعودی جلسه — هشدار نزولی
            elif kind is None:
                kind = "up"     # تقویت/برگشت صعودی از روند نزولی جلسه
    if names:
        out["trend_divergence"] = ("واژگون نزولی: " if kind == "down" else "واژگون صعودی: ") \
            + " + ".join(names)
        out["trend_divergence_kind"] = kind
    else:
        out["trend_divergence"] = None
        out["trend_divergence_kind"] = None
    return out


def _session_trends(raw_db: Path, window: int = TREND_WINDOW_DEFAULT) -> dict:
    """سری‌های نسبت ورود پول و قدرت خریدارِ جلسه از بانک خام، روند آن‌ها و
    میانگین‌های وزنیِ «از ابتدای جلسه» (گروه «روند جلسه»).

    میانگین وزنی هر متریک = میانگینِ منحنیِ تجمیعی آن در طول جلسه با وزنِ ارزش
    معاملاتِ همان بازه (اختلاف tval دو نمونهٔ پیوسته) — دقیقه‌های پرمعامله وزن
    بیشتری دارند؛ «مشابه گزارشات» یعنی وزنی، نه میانگین سادهٔ نمونه‌ها.
    قدرت خرید هم از میانگین وزنیِ نسبتِ خام ساخته و بعد علامت‌دار می‌شود —
    هم‌روش با میانگین‌های چندروزهٔ بانک سابقه.
    """
    con = sqlite3.connect(str(raw_db))
    try:
        rows = con.execute(
            "SELECT buy_i_volume, sell_i_volume, buy_counti, sell_counti, "
            "buy_countn, sell_countn, tval, pc, pl "
            "FROM raw_snapshots WHERE date_jalali = (SELECT MAX(date_jalali) "
            "FROM raw_snapshots) ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    flow, power = [], []
    curve: dict[str, list] = {}
    prev_tval = 0
    for rbv, rsv, rbc, rsc, lbc, lsc, tval, close_p, last_p in rows:
        rbv, rsv, tval = (x or 0 for x in (rbv, rsv, tval))
        rbc, rsc, lbc, lsc = (x or 0 for x in (rbc, rsc, lbc, lsc))
        px = float(close_p or 0) or float(last_p or 0)
        if tval and px:
            flow.append((rbv - rsv) * px / tval * 100)
        if rbc and rsc:
            power.append((rbv / rbc) / (rsv / rsc))
        w = max(tval - prev_tval, 0)   # وزن بازه = ارزش معاملات همان فاصله
        prev_tval = tval
        if not w:
            continue
        if tval and px:
            curve.setdefault("avg_session_total_value", []).append((tval, w))
            if rbc:
                curve.setdefault("avg_session_per_capita_buy", []).append(
                    (rbv / max(rbc, 1), w))
            if rsc:
                curve.setdefault("avg_session_per_capita_sell", []).append(
                    (rsv / max(rsc, 1), w))
            if rbc and rsc:
                curve.setdefault("avg_session_buyer_power", []).append(
                    ((rbv / rbc) / (rsv / rsc), w))
            curve.setdefault("avg_session_real_buy_value", []).append((rbv * px, w))
            curve.setdefault("avg_session_real_sell_value", []).append((rsv * px, w))
        if rbc:
            curve.setdefault("avg_session_real_buy_count", []).append((rbc, w))
        if rsc:
            curve.setdefault("avg_session_real_sell_count", []).append((rsc, w))
        if lbc:
            curve.setdefault("avg_session_legal_buy_count", []).append((lbc, w))
        if lsc:
            curve.setdefault("avg_session_legal_sell_count", []).append((lsc, w))

    def _wavg(key: str) -> float | None:
        pairs = curve.get(key) or []
        sw = sum(w for _, w in pairs)
        return sum(v * w for v, w in pairs) / sw if pairs and sw else None

    out = _trends_from_series(flow, power, window)
    for key in ("avg_session_total_value", "avg_session_real_buy_count",
                "avg_session_real_sell_count", "avg_session_legal_buy_count",
                "avg_session_legal_sell_count", "avg_session_real_buy_value",
                "avg_session_real_sell_value"):
        v = _wavg(key)
        out[key] = int(round(v)) if v is not None else None
    for key in ("avg_session_per_capita_buy", "avg_session_per_capita_sell"):
        v = _wavg(key)
        out[key] = round(v, 0) if v is not None else None
    bp = _wavg("avg_session_buyer_power")
    bp = _signed_power(bp) if bp is not None else None
    out["avg_session_buyer_power"] = round(bp, 2) if bp is not None else None
    return out


def _compute_row(row: dict, name: str, s: dict, root: Path, raw_db: Path, r) -> None:
    """محاسبهٔ یک سطر داشبورد از نمونهٔ خام r — بین export و شبیه‌سازی (portfoli_sim) مشترک.

    row باید از قبل کلیدهای ALL_FIELDS را داشته باشد؛ این تابع مقادیر را پر می‌کند.
    """
    if not isinstance(r, dict):
        r = dict(r)  # sqlite3.Row → dict — خوانش .get امن می‌شود

    def g(key, default=None):
        v = r[key]
        return default if v is None else v

    last_p = float(g("pl") or 0)
    close_p = float(g("pc") or 0)
    yest_p = float(g("py") or 0)
    px = close_p if close_p > 0 else last_p

    rbv = int(g("buy_i_volume") or 0)
    rsv = int(g("sell_i_volume") or 0)
    rbc = int(g("buy_counti") or 0)
    rsc = int(g("sell_counti") or 0)
    lbv = int(g("buy_n_volume") or 0)
    lsv = int(g("sell_n_volume") or 0)
    lbc = int(g("buy_countn") or 0)
    lsc = int(g("sell_countn") or 0)
    tval = float(g("tval") or 0)

    row.update({
        "date_jalali": g("date_jalali"),
        "fetch_hms": g("fetch_hms"),
        "symbol": name,
        "market_phase": _raw_phase(s.get("trading_hours", {}),
                                   str(g("fetch_hms") or "00:00:00")[:5]),
        "symbol_status": g("api_symbol_status"),
        "last_price": int(last_p) if last_p else None,
        "close_price": int(close_p) if close_p else None,
        "open_price": int(float(g("pf") or 0)) or None,
        "yesterday_price": int(yest_p) if yest_p else None,
        "daily_high": int(float(g("pmax") or 0)) or None,
        "daily_low": int(float(g("pmin") or 0)) or None,
        "best_bid": int(float(g("pd1") or 0)) or None,
        "bid_volume": int(g("qd1") or 0) or None,
        "best_ask": int(float(g("po1") or 0)) or None,
        "ask_volume": int(g("qo1") or 0) or None,
        "buy_order_count": int(g("zd1") or 0) or None,
        "sell_order_count": int(g("zo1") or 0) or None,
        "total_volume": int(g("tvol") or 0) or None,
        "total_value": int(tval) if tval else None,
        "total_count": int(g("tno") or 0) or None,
        "real_buy_count": rbc or None,
        "real_buy_volume": rbv or None,
        "real_buy_value": int(rbv * px) if (rbv and px) else None,
        "real_sell_count": rsc or None,
        "real_sell_volume": rsv or None,
        "real_sell_value": int(rsv * px) if (rsv and px) else None,
        "legal_buy_count": lbc or None,
        "legal_buy_volume": lbv or None,
        "legal_buy_value": int(lbv * px) if (lbv and px) else None,
        "legal_sell_count": lsc or None,
        "legal_sell_volume": lsv or None,
        "legal_sell_value": int(lsv * px) if (lsv and px) else None,
    })
    for i in range(1, 6):
        row[f"bid_price_{i}"] = int(float(g(f"pd{i}") or 0)) or None
        row[f"bid_vol_{i}"] = int(g(f"qd{i}") or 0) or None
        row[f"bid_count_{i}"] = int(g(f"zd{i}") or 0) or None
        row[f"ask_price_{i}"] = int(float(g(f"po{i}") or 0)) or None
        row[f"ask_vol_{i}"] = int(g(f"qo{i}") or 0) or None
        row[f"ask_count_{i}"] = int(g(f"zo{i}") or 0) or None

    # شاخص‌های مشتق — همان فرمول‌های data_collector.py
    pc_buy = rbv / max(rbc, 1)
    pc_sell = rsv / max(rsc, 1)
    row["per_capita_buy_real"] = round(pc_buy, 0)
    row["per_capita_sell_real"] = round(pc_sell, 0)
    # قدرت خریدار — علامت‌دار: خریدار غالب ≥ +۱، فروشنده غالب ≤ −۱ (مثلاً ‎−۱٫۱۹)
    bp = _signed_power(pc_buy / pc_sell if pc_sell else None)
    row["buyer_power"] = round(bp, 2) if bp is not None else None
    flow = (rbv - rsv) * px if px else 0
    row["real_money_flow"] = int(flow) if (rbv or rsv) else None
    # مخرج حقیقی (نه کل بازار): سهم خالص حقیقی از گردشِ خود حقیقی‌ها، بین −۱ تا +۱
    # — چون ClientType ارزش ریالی نمی‌دهد، قیمت واحد (px) از صورت و مخرج حذف می‌شود.
    real_turnover = rbv + rsv
    row["real_money_flow_ratio"] = round((rbv - rsv) / real_turnover, 4) if real_turnover else None
    # گروه «تغییرات» — اختلاف‌های خرید−فروش همان لحظه (خرید مثبت، فروش منفی)
    row["code_diff"] = rbc - rsc if (rbc or rsc) else None
    row["per_capita_diff"] = round(pc_buy - pc_sell, 0) if (rbv or rsv) else None
    # هم‌مقدار ورود پول ریالی است — طبق درخواست، ستون مستقلِ گروه «تغییرات»
    row["real_value_diff"] = int((rbv - rsv) * px) if ((rbv or rsv) and px) else None
    row["legal_value_diff"] = int((lbv - lsv) * px) if ((lbv or lsv) and px) else None
    # درصد تغییر — اول فیلد نمایشی بانک (plp/pcp)، نبود → محاسبه از pl/pc/py
    if r.get("plp") is not None:
        row["pct_last"] = float(r["plp"])
    elif yest_p > 0 and last_p:
        row["pct_last"] = round((last_p - yest_p) / yest_p * 100, 2)
    if r.get("pcp") is not None:
        row["pct_close"] = float(r["pcp"])
    elif yest_p > 0 and close_p:
        row["pct_close"] = round((close_p - yest_p) / yest_p * 100, 2)

    # کف/سقف مجاز از ماژول پروژه
    if yest_p > 0:
        dp = _daily_params(name, yest_p, root)
        if dp:
            row["min_allowed_price"] = dp["min_allowed_price"]
            row["max_allowed_price"] = dp["max_allowed_price"]
            lo, hi = dp["min_allowed_price"], dp["max_allowed_price"]
            if last_p and hi > lo:
                row["price_reaction_score"] = round((last_p - lo) / (hi - lo) * 100, 1)

    # شاخص‌های چندروزه — فرمول‌های فایل dashboard.xlsx، شیت dashboard
    ds = _daily_stats(raw_db, str(g("date_jalali") or "") or None, name)
    # تاریخ مبنا برای سطر دوم داشبورد لایو («جلسهٔ قبل — تا …»)
    row["hist_basis_date"] = ds.get("basis_date")
    # مقادیر جلسهٔ قبلِ فیلدهای مقایسه‌ای (قیمت پایانی، ورود پول، …) برای سطر دوم
    row["hist_vals"] = ds.get("basis_vals")
    if tval:
        row["money_flow_ratio_pct"] = round(flow / tval * 100, 2)
    if (rbv or rsv) and px:
        # خود میانگین‌ها هم در سطر می‌نشینند تا مبنای نسبت‌ها قابل بررسی باشد
        row["flow5_avg_abs"] = int(ds["flow5_avg_abs"]) if ds["flow5_avg_abs"] else None
        row["flow30_avg_abs"] = int(ds["flow30_avg_abs"]) if ds["flow30_avg_abs"] else None
    if ds["flow5_avg_abs"] > 0 and (rbv or rsv):
        row["mf_ratio_5d_pct"] = round(flow / ds["flow5_avg_abs"] * 100, 2)
    if ds["flow30_avg_abs"] > 0 and (rbv or rsv):
        row["mf_ratio_30d_pct"] = round(flow / ds["flow30_avg_abs"] * 100, 2)
    tvol = float(g("tvol") or 0)
    if ds["vol5_avg"] > 0 and tvol:
        row["volume_ratio_5d_pct"] = round(tvol / ds["vol5_avg"] * 100, 1)
    if ds["vol30_avg"] > 0 and tvol:
        row["volume_ratio_30d_pct"] = round(tvol / ds["vol30_avg"] * 100, 1)
    # گروه «تاریخچه» — میانگین‌های عددی ۵/۱۰/۲۰/۳۰ روزه (پنجرهٔ کامل روزهای قبل)
    if ds.get("days"):
        for k in ("flow_avg5_rial", "flow_avg10_rial", "flow_avg20_rial",
                  "flow_avg30_rial", "vol_avg5", "vol_avg10",
                  "vol_avg20", "vol_avg30", "val_avg5", "val_avg10",
                  "val_avg20", "val_avg30"):
            v = ds.get(k)
            row[k] = int(v) if v is not None else None
        for k in ("buy_power_avg5", "buy_power_avg10",
                  "buy_power_avg20", "buy_power_avg30"):
            v = ds.get(k)
            row[k] = round(v, 2) if v is not None else None
    if rbc or rsc:
        row["buyer_seller_count_ratio"] = round(rbc / max(rsc, 1), 2) if rsc else None
    bv_val, sv_val = row.get("real_buy_value") or 0, row.get("real_sell_value") or 0
    if bv_val or sv_val:
        row["buy_sell_amount_side"] = ("خرید" if bv_val > sv_val
                                       else "فروش" if sv_val > bv_val else "تعادل")

    # کیفیت داده — تعداد فیلدهای مفقودِ کلیدی
    key_fields = ["last_price", "close_price", "yesterday_price", "best_bid",
                  "best_ask", "total_volume", "total_value",
                  "real_buy_volume", "real_sell_volume"]
    missing = sum(1 for k in key_fields if not row.get(k))
    row["missing_count"] = missing
    row["data_status"] = "ok" if missing == 0 else ("partial" if missing <= 3 else "incomplete")


def latest_bank_times(root: Path) -> dict:
    """آخرین نمونهٔ هر نماد از بانک خام — برای نمایش تازگی داده در داشبورد."""
    out = {}
    for db in sorted((root / "data" / "raw").glob("raw_*.sqlite")):
        name = db.stem[len("raw_"):]
        con = sqlite3.connect(str(db))
        try:
            t = con.execute(
                "SELECT date_jalali, fetch_hms FROM raw_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            t = None
        finally:
            con.close()
        if t:
            out[name] = {"date_jalali": t[0], "fetch_hms": t[1]}
    return out


def build_payload(root: Path, trend_window: int = TREND_WINDOW_DEFAULT) -> dict:
    """ساخت payload کامل داشبورد از بانک‌های خام پروژهٔ root.

    trend_window — طول پنجرهٔ «نمونه‌های اخیر» برای روند ورود پول/قدرت خریدار.
    """
    root = Path(root)
    sym_path = root / "config" / "symbols.json"
    symbols_cfg = json.loads(sym_path.read_text(encoding="utf-8"))["symbols"]

    rows = []
    for s in symbols_cfg:
        if s.get("ok", True) is False and not s.get("ins_code"):
            continue
        name = s["name"]
        row = {en: None for en in ALL_FIELDS}
        row["_meta"] = {
            "name": name,
            "ins_code": str(s.get("ins_code", "")),
            "market_label": s.get("market_label", ""),
            "instrument_type": s.get("instrument_type", ""),
            "trading_hours": s.get("trading_hours", {}),
            "days": s.get("days", ""),
        }

        raw_db = root / "data" / "raw" / f"raw_{name}.sqlite"
        if raw_db.exists():
            con = sqlite3.connect(str(raw_db))
            con.row_factory = sqlite3.Row
            try:
                r = con.execute(
                    "SELECT * FROM raw_snapshots WHERE date_jalali = "
                    "(SELECT MAX(date_jalali) FROM raw_snapshots) "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
            finally:
                con.close()
            if r is not None:
                _compute_row(row, name, s, root, raw_db, r)
                try:
                    row.update(_session_trends(raw_db, trend_window))
                except sqlite3.Error:
                    pass  # بانک قفل/خراب — روند خالی می‌ماند
            else:
                row["data_status"] = "بدون دادهٔ امروز"
        else:
            row["data_status"] = "بدون بانک خام"
        rows.append(row)

    return {
        "version": 1,
        "date": rows[0].get("date_jalali") if rows else None,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
        "groups": [{"title": t, "cols": [{"fa": fa, "en": en} for fa, en in cols]}
                   for t, cols in GROUPS],
        "default_visible": DEFAULT_VISIBLE,
        "bank_times": latest_bank_times(root),
        "trend_window": trend_window,
    }


def main():
    ap = argparse.ArgumentParser(description="تولید دادهٔ داشبورد portfoli از بانک خام")
    ap.add_argument("-o", "--output", default="portfoli_data.json")
    ap.add_argument("--root", default=None, help="ریشهٔ پروژه (پیش‌فرض: پوشهٔ همین اسکریپت)")
    args = ap.parse_args()

    root = Path(args.root) if args.root else Path(__file__).parent
    payload = build_payload(root)
    out = Path(args.output) if Path(args.output).is_absolute() else root / args.output
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    filled = sum(1 for r in payload["rows"] if r.get("date_jalali"))
    print(f"✓ {out} — {len(payload['rows'])} نماد ({filled} نماد دارای داده)")


if __name__ == "__main__":
    main()
