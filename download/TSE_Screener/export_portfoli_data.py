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
        ("نسبت جریان پول ٪", "money_flow_ratio_pct"),
        ("نسبت ۵ روزه جریان پول ٪", "mf_ratio_5d_pct"),
        ("نسبت ۵ روزه حجم ٪", "volume_ratio_5d_pct"),
        ("نسبت ۳۰ روزه حجم ٪", "volume_ratio_30d_pct"),
        ("از نظر مبلغ خرید یا فروش", "buy_sell_amount_side"),
        ("نسبت تعداد خریدار به فروشنده", "buyer_seller_count_ratio"),
        ("امتیاز واکنش قیمت", "price_reaction_score"),
    ]),
    ("روند جلسه", [
        ("میانگین نسبت جریان پول (N نمادهٔ اخیر)", "flow_ratio_recent_avg"),
        ("روند جریان پول از ابتدای جلسه", "trend_flow_session"),
        ("روند جریان پول (N نمادهٔ اخیر)", "trend_flow_recent"),
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


def _daily_stats(db_path: Path, today: str | None) -> dict:
    """آمار روزانه از آخرین نمونهٔ هر روز معاملاتی — برای شاخص‌های چندروزهٔ شیت dashboard.

    جریان پول هر روز = (خرید حقیقی − فروش حقیقی) × قیمت پایانیِ آخرین نمونهٔ آن روز.
    روزِ امروز (today) از آمار «روزهای قبل» کنار گذاشته می‌شود.
    """
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT date_jalali, ct_real_buy_volume, ct_real_sell_volume, "
            "close_price, trade_volume FROM raw_snapshots WHERE id IN "
            "(SELECT MAX(id) FROM raw_snapshots GROUP BY date_jalali) "
            "ORDER BY date_jalali DESC"
        ).fetchall()
    finally:
        con.close()
    if today:
        rows = [r for r in rows if r["date_jalali"] != today]
    flows, vols = [], []
    for r in rows[:30]:
        px = float(r["close_price"] or 0)
        flows.append(abs((int(r["ct_real_buy_volume"] or 0) -
                          int(r["ct_real_sell_volume"] or 0)) * px))
        vols.append(float(r["trade_volume"] or 0))
    f5, v5, v30 = flows[:5], vols[:5], vols[:30]
    return {
        "flow5_avg_abs": sum(f5) / len(f5) if f5 else 0.0,
        "vol5_avg": sum(v5) / len(v5) if v5 else 0.0,
        "vol30_avg": sum(v30) / len(v30) if v30 else 0.0,
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


def _trend_label(values) -> str | None:
    """برچسب روند یک سری زمانی — شیب رگرسیون خطی نرمال‌شده به دامنهٔ نوسان سری.

    norm = کل تغییرِ پیش‌بینی‌شدهٔ روند در طول پنجره ÷ دامنهٔ نوسان؛
    خط صاف = ۱٫۰. آستانه‌ها: |norm|≥۰٫۵ قوی، ≥۰٫۱۵ ملایم، کمتر = خنثی.
    """
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < 4:
        return None
    mx = (n - 1) / 2
    my = sum(vals) / n
    sxx = sum((i - mx) ** 2 for i in range(n))
    sxy = sum((i - mx) * (v - my) for i, v in enumerate(vals))
    slope = sxy / sxx if sxx else 0.0
    span = max(vals) - min(vals)
    norm = slope * (n - 1) / span if span > 1e-12 else 0.0
    if norm >= 0.5:
        return "قوی صعودی"
    if norm >= 0.15:
        return "صعودی"
    if norm <= -0.5:
        return "قوی نزولی"
    if norm <= -0.15:
        return "نزولی"
    return "خنثی"


def _trends_from_series(flow, power, window: int = TREND_WINDOW_DEFAULT) -> dict:
    """روند جریان پول و قدرت خریدار از سری‌های نمونه‌ای — بین export و شبیه‌سازی مشترک.

    واژگونی = جهت روند پنجرهٔ اخیر معکوس جهت روند کل جلسه (مثلاً جلسه صعودی ولی
    N نمادهٔ اخیر نزولی) — مبنای هایلایت کل سطر در داشبورد.
    """
    w = max(3, int(window))
    fs, ps = list(flow)[-w:], list(power)[-w:]
    out = {
        "trend_flow_session": _trend_label(flow),
        "trend_flow_recent": _trend_label(fs),
        "trend_power_session": _trend_label(power),
        "trend_power_recent": _trend_label(ps),
        "flow_ratio_recent_avg": round(sum(fs) / len(fs), 2) if fs else None,
    }
    names, kind = [], None
    for name, ses, rec in (("جریان پول", out["trend_flow_session"], out["trend_flow_recent"]),
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
    """سری‌های نسبت جریان پول و قدرت خریدارِ جلسه از بانک خام و روند آن‌ها."""
    con = sqlite3.connect(str(raw_db))
    try:
        rows = con.execute(
            "SELECT ct_real_buy_volume, ct_real_sell_volume, ct_real_buy_count, "
            "ct_real_sell_count, trade_value, close_price, last_price "
            "FROM raw_snapshots WHERE date_jalali = (SELECT MAX(date_jalali) "
            "FROM raw_snapshots) ORDER BY id"
        ).fetchall()
    finally:
        con.close()
    flow, power = [], []
    for rbv, rsv, rbc, rsc, tval, close_p, last_p in rows:
        rbv, rsv, rbc, rsc, tval = (x or 0 for x in (rbv, rsv, rbc, rsc, tval))
        px = float(close_p or 0) or float(last_p or 0)
        if tval and px:
            flow.append((rbv - rsv) * px / tval * 100)
        if rbc and rsc:
            power.append((rbv / rbc) / (rsv / rsc))
    return _trends_from_series(flow, power, window)


def _compute_row(row: dict, name: str, s: dict, root: Path, raw_db: Path, r) -> None:
    """محاسبهٔ یک سطر داشبورد از نمونهٔ خام r — بین export و شبیه‌سازی (portfoli_sim) مشترک.

    row باید از قبل کلیدهای ALL_FIELDS را داشته باشد؛ این تابع مقادیر را پر می‌کند.
    """
    def g(key, default=None):
        v = r[key]
        return default if v is None else v

    last_p = float(g("last_price") or 0)
    close_p = float(g("close_price") or 0)
    yest_p = float(g("yesterday_price") or 0)
    px = close_p if close_p > 0 else last_p

    rbv = int(g("ct_real_buy_volume") or 0)
    rsv = int(g("ct_real_sell_volume") or 0)
    rbc = int(g("ct_real_buy_count") or 0)
    rsc = int(g("ct_real_sell_count") or 0)
    lbv = int(g("ct_legal_buy_volume") or 0)
    lsv = int(g("ct_legal_sell_volume") or 0)
    lbc = int(g("ct_legal_buy_count") or 0)
    lsc = int(g("ct_legal_sell_count") or 0)
    tval = float(g("trade_value") or 0)

    row.update({
        "date_jalali": g("date_jalali"),
        "fetch_hms": g("fetch_hms"),
        "symbol": name,
        "market_phase": _raw_phase(s.get("trading_hours", {}),
                                   str(g("fetch_hms") or "00:00:00")[:5]),
        "symbol_status": g("api_symbol_status"),
        "last_price": int(last_p) if last_p else None,
        "close_price": int(close_p) if close_p else None,
        "open_price": int(float(g("open_price") or 0)) or None,
        "yesterday_price": int(yest_p) if yest_p else None,
        "daily_high": int(float(g("daily_high") or 0)) or None,
        "daily_low": int(float(g("daily_low") or 0)) or None,
        "best_bid": int(float(g("buy_price_1") or 0)) or None,
        "bid_volume": int(g("buy_volume_1") or 0) or None,
        "best_ask": int(float(g("sell_price_1") or 0)) or None,
        "ask_volume": int(g("sell_volume_1") or 0) or None,
        "buy_order_count": int(g("buy_orders_1") or 0) or None,
        "sell_order_count": int(g("sell_orders_1") or 0) or None,
        "total_volume": int(g("trade_volume") or 0) or None,
        "total_value": int(tval) if tval else None,
        "total_count": int(g("trade_count") or 0) or None,
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
        row[f"bid_price_{i}"] = int(float(g(f"buy_price_{i}") or 0)) or None
        row[f"bid_vol_{i}"] = int(g(f"buy_volume_{i}") or 0) or None
        row[f"bid_count_{i}"] = int(g(f"buy_orders_{i}") or 0) or None
        row[f"ask_price_{i}"] = int(float(g(f"sell_price_{i}") or 0)) or None
        row[f"ask_vol_{i}"] = int(g(f"sell_volume_{i}") or 0) or None
        row[f"ask_count_{i}"] = int(g(f"sell_orders_{i}") or 0) or None

    # شاخص‌های مشتق — همان فرمول‌های data_collector.py
    pc_buy = rbv / max(rbc, 1)
    pc_sell = rsv / max(rsc, 1)
    row["per_capita_buy_real"] = round(pc_buy, 0)
    row["per_capita_sell_real"] = round(pc_sell, 0)
    row["buyer_power"] = round(pc_buy / max(pc_sell, 1e-9), 2) if pc_sell else None
    flow = (rbv - rsv) * px if px else 0
    row["real_money_flow"] = int(flow) if (rbv or rsv) else None
    row["real_money_flow_ratio"] = round(flow / max(tval, 1.0), 4) if tval else None
    if yest_p > 0:
        if last_p:
            row["pct_last"] = round((last_p - yest_p) / yest_p * 100, 2)
        if close_p:
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
    ds = _daily_stats(raw_db, str(g("date_jalali") or "") or None)
    if tval:
        row["money_flow_ratio_pct"] = round(flow / tval * 100, 2)
    if ds["flow5_avg_abs"] > 0 and (rbv or rsv):
        row["mf_ratio_5d_pct"] = round(flow / ds["flow5_avg_abs"] * 100, 2)
    tvol = float(g("trade_volume") or 0)
    if ds["vol5_avg"] > 0 and tvol:
        row["volume_ratio_5d_pct"] = round(tvol / ds["vol5_avg"] * 100, 1)
    if ds["vol30_avg"] > 0 and tvol:
        row["volume_ratio_30d_pct"] = round(tvol / ds["vol30_avg"] * 100, 1)
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

    trend_window — طول پنجرهٔ «نمونه‌های اخیر» برای روند جریان پول/قدرت خریدار.
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
