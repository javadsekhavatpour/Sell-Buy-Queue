#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
history_dashboard.py — محاسبهٔ شاخص‌های سابقهٔ روزانه برای داشبورد «سابقهٔ نمادها»

منبع داده: data/raw/history.sqlite (فقط دادهٔ خام TSETMC — history_collector.py)
فرمول‌ها: همان فرمول‌های export_portfoli_data.py؛ تنها تفاوت عمدی این است که
سابقهٔ حقیقی/حقوقی TSETMC «ارزش واقعی ریالی» (buy_I_Value/sell_I_Value) را می‌دهد،
پس جریان پول با ارزش واقعی حساب می‌شود — نسخهٔ بدون تقریبِ همان فرمول
(در لایو ارزش نداریم و (حجم × قیمت پایانی) استفاده می‌شود).

ستون‌های داشبورد سابقه (ترتیب درخواست کاربر):
  close_price      قیمت پایانی
  pct_close        ٪ نوسان پایانی          = (پایانی − دیروز) ÷ دیروز × ۱۰۰
  flow_rial        جریان پول (ریال)        = خرید حقیقی − فروش حقیقی (ارزش واقعی TSE)
  flow_avg5_rial   میانگین ۵ روزه جریان پول = میانگین جریانِ ۵ روز قبل (بدون امروز)
  flow_avg20_rial  میانگین ۲۰ روزه جریان پول = همان با ۲۰ روز قبل
  flow_avg30_rial  میانگین ۳۰ روزه جریان پول = همان با ۳۰ روز قبل
  vol_avg5         میانگین ۵ روزه حجم       = میانگین حجم ۵ روز قبل (بدون امروز)
  vol_avg20        میانگین ۲۰ روزه حجم      = همان با ۲۰ روز قبل
  vol_avg30        میانگین ۳۰ روزه حجم      = همان با ۳۰ روز قبل
  bs_count_ratio   تعداد خریدار به فروشنده  = buy_CountI ÷ sell_CountI
  real_buy_pct     درصد خرید حقیقی از کل    = ارزش خرید حقیقی ÷ ارزش کل × ۱۰۰
  reaction_pct     واکنش قیمت (٪)           = جای آخرین قیمت در بازهٔ کف تا سقف مجاز
                                             (کف/سقف = دیروز × (۱ ± pct) — price_range.py)
  (+ نسبت‌های درصدی قبلی mf5/mf30/vol5/vol30 در payload برای سازگاری حفظ شده‌اند)
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from early_warning.price_range import compute_daily_params  # noqa: E402

DB = ROOT / "data" / "raw" / "history.sqlite"


def _flow(r: dict) -> float | None:
    """جریان پول ریالی روز — ارزش واقعی خرید حقیقی منهای فروش حقیقی (خام TSE)."""
    b, s = r.get("ct_real_buy_value"), r.get("ct_real_sell_value")
    if b is None and s is None:
        return None
    return (b or 0.0) - (s or 0.0)


def _avg(xs: list[float]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def build_history_data(root: Path = ROOT, symbols: list[str] | None = None) -> dict:
    """خواندن بانک خام سابقه و ساخت ردیف‌های داشبورد — بدون تغییر بانک."""
    db = root / "data" / "raw" / "history.sqlite"
    if not db.exists():
        return {"ok": False, "error": "بانک سابقه پیدا نشد — ابتدا جمع‌آوری را اجرا کنید",
                "generated_at": None, "symbols": []}
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cols = [r[1] for r in con.execute("PRAGMA table_info(history_daily)")]
    names = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM history_daily ORDER BY symbol")]
    if symbols:
        names = [n for n in names if n in symbols]

    cfg_dir = root / "config"
    out = {"ok": True, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "symbols": []}
    for name in names:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM history_daily WHERE symbol=? ORDER BY date_greg", (name,))]
        if not rows:
            continue
        # پیش‌محاسبهٔ سری‌ها برای پنجره‌های ۵/۲۰/۳۰ روزه (مطابق _daily_statsِ exporter:
        # پنجره فقط «روزهای قبل» است، امروز داخل میانگین نمی‌آید)
        flows = [_flow(r) for r in rows]
        vols = [r.get("trade_volume") for r in rows]
        f_abs = [abs(f) if f is not None else None for f in flows]
        computed: list[dict] = []
        for i, r in enumerate(rows):
            close = r.get("close_price")
            yest = r.get("yesterday_price")
            tval = r.get("trade_value")
            row = {"date_jalali": r.get("date_jalali"), "close_price": close}
            # ٪ نوسان پایانی — فرمول pct_close (export_portfoli_data)
            row["pct_close"] = round((close - yest) / yest * 100, 2) if (close and yest) else None
            fl = flows[i]
            if fl is None:
                row["money_flow_pct"] = None
            else:
                # جریان پول (٪) — فرمول money_flow_ratio_pct
                row["money_flow_pct"] = round(fl / tval * 100, 2) if tval else None
            # نسبت‌های چندروزه — مخرج = میانگین |جریان| روزهای قبل از امروز (سازگاری payload)
            f5, f20, f30 = (_avg(f_abs[max(0, i - n):i]) for n in (5, 20, 30))
            v5, v20, v30 = (_avg(vols[max(0, i - n):i]) for n in (5, 20, 30))
            row["mf5_pct"] = round(fl / f5 * 100, 2) if (fl is not None and f5) else None
            row["mf30_pct"] = round(fl / f30 * 100, 2) if (fl is not None and f30) else None
            row["vol5_pct"] = round(vols[i] / v5 * 100, 2) if (vols[i] and v5) else None
            row["vol30_pct"] = round(vols[i] / v30 * 100, 2) if (vols[i] and v30) else None
            # ── فیلدهای جدید: مقادیر عددی جریان پول و میانگین‌های ۵/۲۰/۳۰ روزه ──
            # میانگین جریان پول با علامت (خالص جهت در بازه) — پنجره بدون امروز
            sf5, sf20, sf30 = (_avg(flows[max(0, i - n):i]) for n in (5, 20, 30))
            for n, av in ((5, sf5), (20, sf20), (30, sf30)):
                row[f"flow_avg{n}_rial"] = round(av) if av is not None else None
            # میانگین حجم — پنجره بدون امروز
            for n, av in ((5, v5), (20, v20), (30, v30)):
                row[f"vol_avg{n}"] = round(av) if av is not None else None
            # تعداد خریدار به فروشنده — فرمول buyer_seller_count_ratio
            bc, sc = r.get("ct_real_buy_count"), r.get("ct_real_sell_count")
            row["bs_count_ratio"] = round(bc / sc, 2) if (bc and sc) else None
            # درصد خرید حقیقی از کل معاملات — ارزش واقعی ÷ ارزش کل × ۱۰۰
            rbv = r.get("ct_real_buy_value")
            row["real_buy_pct"] = round(rbv / tval * 100, 2) if (rbv is not None and tval) else None
            # واکنش قیمت — فرمول price_reaction_score با کف/سقف price_range.py
            dp = compute_daily_params(name, float(yest), cfg_dir) if yest else None
            if dp and dp["max_allowed_price"] > dp["min_allowed_price"] and r.get("last_price"):
                row["reaction_pct"] = round(
                    (r["last_price"] - dp["min_allowed_price"])
                    / (dp["max_allowed_price"] - dp["min_allowed_price"]) * 100, 1)
            else:
                row["reaction_pct"] = None
            row["flow_rial"] = round(fl) if fl is not None else None
            computed.append(row)
        out["symbols"].append({"name": name, "days": len(computed),
                               # تاریخ آخرین روز جمع‌آوری — آخرین تاریخ شمسیِ بانک خام
                               "last_collected": computed[-1]["date_jalali"],
                               "rows": computed})
    con.close()
    return out


# شِمای بایگانی محاسبات — همان بانکی که portfoli_server.save_history می‌سازد
# (UNIQUE(symbol, date_jalali, fetch_hms) → ردیف تکراری ممکن نیست)
PORTFOLI_HISTORY_SQL = """
CREATE TABLE IF NOT EXISTS computed_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    saved_at TEXT NOT NULL,
    date_jalali TEXT NOT NULL,
    fetch_hms TEXT NOT NULL,
    symbol TEXT NOT NULL,
    payload TEXT NOT NULL,
    UNIQUE(symbol, date_jalali, fetch_hms)
)
"""


def backfill_portfoli_history(root: Path = ROOT, days: int = 30) -> dict:
    """پر کردن بایگانی portfoli_history.sqlite تا N روز گذشته (پیش‌فرض ۳۰، بیشینه ۹۰).

    داشبورد لایو این بانک را فقط در طول اجرا پر می‌کند؛ این تابع همان ردیف‌های
    محاسبه‌شدهٔ سابقه را از بانک خام history.sqlite به آن اضافه می‌کند تا مرور
    تاریخچه از همان روزِ نصب ممکن باشد. fetch_hms = "hist" نشان می‌دهد ردیف
    از سابقهٔ TSETMC بایگانی شده نه از نمونهٔ لحظه‌ای لایو.
    """
    days = min(max(int(days), 30), 90)  # حداقل ۳۰ روز دیفالت، تا ۹۰ روز
    data = build_history_data(root)
    hist = root / "data" / "raw" / "portfoli_history.sqlite"
    hist.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(hist))
    added = 0
    updated = 0
    last_dates = []
    try:
        con.execute(PORTFOLI_HISTORY_SQL)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for s in data.get("symbols", []):
            tail = s["rows"][-days:]
            last_dates.append({"symbol": s["name"],
                               "last_collected": s.get("last_collected"),
                               "days": len(tail)})
            for r in tail:
                payload = {"symbol": s["name"], "date_jalali": r["date_jalali"],
                           "fetch_hms": "hist",
                           "source": "history.sqlite (TSETMC سابقهٔ خام)"}
                payload.update(r)
                # اگر ردیف hist قبلاً هست فقط payload تازه می‌شود (فرمول‌های جدید)،
                # وگرنه اضافه می‌شود — در هر دو حالت یک ردیف، بدون تکرار
                has = con.execute(
                    "SELECT 1 FROM computed_samples "
                    "WHERE symbol=? AND date_jalali=? AND fetch_hms='hist'",
                    (s["name"], r["date_jalali"])).fetchone()
                if has:
                    con.execute(
                        "UPDATE computed_samples SET payload=?, saved_at=? "
                        "WHERE symbol=? AND date_jalali=? AND fetch_hms='hist'",
                        (json.dumps(payload, ensure_ascii=False), now,
                         s["name"], r["date_jalali"]))
                    updated += 1
                else:
                    con.execute(
                        "INSERT INTO computed_samples "
                        "(saved_at, date_jalali, fetch_hms, symbol, payload) "
                        "VALUES (?,?,?,?,?)",
                        (now, r["date_jalali"], "hist", s["name"],
                         json.dumps(payload, ensure_ascii=False)))
                    added += 1
        con.commit()
    finally:
        con.close()
    return {"ok": True, "days": days, "added": added, "updated": updated,
            "last_dates": last_dates}


if __name__ == "__main__":
    import json
    data = build_history_data()
    for s in data.get("symbols", []):
        last = s["rows"][-1] if s["rows"] else {}
        print(s["name"], "→", json.dumps(last, ensure_ascii=False))
