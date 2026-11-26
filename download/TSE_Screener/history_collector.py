#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
history_collector.py — جمع‌آورِ سابقهٔ روزانهٔ نمادها (فقط دادهٔ خام TSETMC)

روش دریافت — همان دو endpoint سابقهٔ ریپوی مرجع dashboard (update_input.py):
  ClosingPrice/GetClosingPriceDailyList/{insCode}/{days}  ← سابقهٔ قیمت و معاملات
  ClientType/GetClientTypeHistory/{insCode}               ← سابقهٔ حقیقی/حقوقی
                                                              (حجم + ارزش + تعداد)

اصل بانک خام (همان فلسفهٔ raw_collector.py):
  - فقط مقادیر خام پاسخ TSETMC ذخیره می‌شود — بدون هیچ شاخص محاسبه‌ای؛
    جریان پول، نسبت‌ها و واکنش قیمت در زمان نمایش، با فرمول‌های
    export_portfoli_data.py ساخته می‌شوند (history_dashboard.py).
  - نکتهٔ مهم: سابقهٔ حقیقی/حقوقی «ارزش ریالی واقعی» را هم می‌دهد
    (buy_I_Value / sell_I_Value) — همان چیزی که endpoint لایو ندارد.

جلوگیری از رکورد تکراری:
  PRIMARY KEY (symbol, date_greg) + INSERT OR REPLACE → اجرای دوباره فقط
  همان ردیف را به‌روز می‌کند؛ هیچ ردیف دوباره‌ای ساخته نمی‌شود.

محل ذخیره: data/raw/history.sqlite — جدول history_daily (کنار بانک‌های raw_{نماد}).

اجرا:
  python history_collector.py                      # همهٔ نمادهای symbols.json، ۴۰۰ روز
  python history_collector.py --days 120           # بازهٔ کوتاه‌تر
  python history_collector.py --symbols سرود,کپارس # زیرمجموعه
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from early_warning.price_range import to_jalali  # noqa: E402  — همان تبدیل پروژه

API_BASE = "https://cdn.tsetmc.com/api"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://old.tsetmc.com/",
    "Origin": "https://old.tsetmc.com",
}

# فیلدهای خام — مپ ۱:۱ با کلیدهای پاسخ TSETMC (همان نام‌گذاری raw_collector)
PRICE_MAP = {   # GetClosingPriceDailyList → closingPriceDaily[]
    "pDrCotVal":       "last_price",        # آخرین قیمت معامله
    "pClosing":        "close_price",       # قیمت پایانی
    "priceFirst":      "open_price",        # اولین قیمت
    "priceYesterday":  "yesterday_price",   # قیمت دیروز
    "priceMax":        "daily_high",        # بیشترین روز
    "priceMin":        "daily_low",         # کمترین روز
    "qTotTran5J":      "trade_volume",      # حجم کل معاملات
    "qTotCap":         "trade_value",       # ارزش کل (ریال)
    "zTotTran":        "trade_count",       # تعداد معاملات
}
CT_MAP = {      # GetClientTypeHistory → clientType[]
    "buy_I_Volume":    "ct_real_buy_volume",
    "buy_I_Value":     "ct_real_buy_value",     # ارزش واقعی خرید حقیقی (ریال)
    "buy_I_Count":     "ct_real_buy_count",
    "buy_N_Volume":    "ct_legal_buy_volume",
    "buy_N_Value":     "ct_legal_buy_value",
    "buy_N_Count":     "ct_legal_buy_count",
    "sell_I_Volume":   "ct_real_sell_volume",
    "sell_I_Value":    "ct_real_sell_value",
    "sell_I_Count":    "ct_real_sell_count",
    "sell_N_Volume":   "ct_legal_sell_volume",
    "sell_N_Value":    "ct_legal_sell_value",
    "sell_N_Count":    "ct_legal_sell_count",
}

ID_COLS = ["symbol", "ins_code", "date_greg", "date_jalali"]
VALUE_COLS = list(PRICE_MAP.values()) + list(CT_MAP.values())
ALL_COLS = ID_COLS + VALUE_COLS


def api_get(session: requests.Session, path: str, tries: int = 3) -> dict:
    for t in range(tries):
        try:
            r = session.get(f"{API_BASE}{path}", headers=HEADERS, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if t == tries - 1:
                raise
            time.sleep(1.5 * (t + 1))
    return {}


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cols = ",\n    ".join(
        f"{c} {'TEXT' if c in ID_COLS else 'REAL'}" for c in ALL_COLS
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS history_daily (\n"
        f"    {cols},\n"
        "    PRIMARY KEY (symbol, date_greg)\n"   # رکورد تکراری ممکن نیست
        ") WITHOUT ROWID"
    )
    conn.commit()
    return conn


def _num(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect_symbol(session: requests.Session, conn: sqlite3.Connection,
                   name: str, ins_code: str, days: int) -> tuple[int, int]:
    """دریافت و ادغام سابقهٔ قیمت + حقیقی/حقوقی یک نماد. خروجی: (قیمت، حقیقی/حقوقی)."""
    price_items = api_get(session, f"/ClosingPrice/GetClosingPriceDailyList/{ins_code}/{days}"
                          ).get("closingPriceDaily") or []
    ct_items = api_get(session, f"/ClientType/GetClientTypeHistory/{ins_code}"
                       ).get("clientType") or []

    # ادغام بر تاریخ میلادی yyyymmdd — سابقهٔ حقیقی/حقوقی کل عمر نماد را می‌دهد
    by_date: dict[int, dict] = {}
    for p in price_items:
        d = int(p["dEven"])
        row = by_date.setdefault(d, {})
        for k, v in PRICE_MAP.items():
            row[v] = _num(p.get(k))
    ct_days = 0
    for h in ct_items:
        d = int(h["recDate"])
        if days and d not in by_date and price_items and \
           d < int(price_items[0]["dEven"]) - (days * 2):
            continue  # خارج از بازهٔ درخواستی — فقط جلوی دادهٔ بی‌قیمت را می‌گیریم
        row = by_date.setdefault(d, {})
        for k, v in CT_MAP.items():
            row[v] = _num(h.get(k))
        ct_days += 1

    n = 0
    for d, vals in sorted(by_date.items()):
        gy, gm, gd = d // 10000, (d // 100) % 100, d % 100
        try:
            jal = to_jalali(date(gy, gm, gd))
        except ValueError:
            continue  # تاریخ نامعتبر پاسخ
        rec = {"symbol": name, "ins_code": str(ins_code), "date_greg": str(d),
               "date_jalali": jal}
        rec.update({k: vals.get(k) for k in VALUE_COLS})
        # فقط روزهایی که قیمت دارند (پاسخ حقیقی/حقوقی گاهی روز بدون معامله دارد)
        if rec["close_price"] is None:
            continue
        conn.execute(
            f"INSERT OR REPLACE INTO history_daily ({', '.join(ALL_COLS)}) "
            f"VALUES ({', '.join('?' for _ in ALL_COLS)})",
            [rec[c] for c in ALL_COLS])
        n += 1
    conn.commit()
    return n, ct_days


def main() -> None:
    ap = argparse.ArgumentParser(description="جمع‌آوری سابقهٔ روزانهٔ نمادها — فقط دادهٔ خام")
    ap.add_argument("--days", type=int, default=400, help="بازهٔ سابقهٔ قیمت (روز، پیش‌فرض ۴۰۰)")
    ap.add_argument("--symbols", type=str, default=None, help="نمادها با کاما (پیش‌فرض: همه)")
    args = ap.parse_args()

    cfg = (ROOT / "config" / "symbols.json").read_text(encoding="utf-8")
    symbols = __import__("json").loads(cfg)["symbols"]
    if args.symbols:
        want = [s.strip() for s in args.symbols.split(",")]
        symbols = [s for s in symbols if s["name"] in want]

    db = ROOT / "data" / "raw" / "history.sqlite"
    conn = init_db(db)
    print(f"بانک سابقه: {db} — {len(symbols)} نماد، بازهٔ {args.days} روز")
    total = 0
    with requests.Session() as ses:
        for s in symbols:
            if s.get("ok", True) is False or not s.get("ins_code"):
                print(f"  {s['name']}: بدون ins_code — رد شد")
                continue
            t0 = time.time()
            try:
                n, ct = collect_symbol(ses, conn, s["name"], s["ins_code"], args.days)
                total += n
                print(f"  {s['name']}: {n} روز نوشته شد (حقیقی/حقوقی: {ct} روز) — {time.time()-t0:.1f}s")
            except Exception as e:
                print(f"  {s['name']}: خطا — {e}")
    # شمار کل بدون تکرار
    rows = conn.execute("SELECT COUNT(*) FROM history_daily").fetchone()[0]
    syms = conn.execute("SELECT COUNT(DISTINCT symbol) FROM history_daily").fetchone()[0]
    print(f"✓ این اجرا: {total} ردیف | کل بانک: {rows} ردیف، {syms} نماد — بدون تکرار")
    # بانک محاسباتی — میانگین‌های ۵/۱۰/۲۰/۳۰ و شاخص‌ها «در لحظهٔ جمع‌آوری»
    # محاسبه و در history_computed.sqlite (جدا از بانک خام) ذخیره می‌شوند
    try:
        import history_dashboard
        t0 = time.time()
        res = history_dashboard.refresh_computed(ROOT)
        if res.get("ok"):
            print(f"✓ بانک محاسباتی: {res['symbols']} نماد ذخیره شد "
                  f"(history_computed.sqlite) — {time.time()-t0:.1f}s")
        else:
            print(f"بانک محاسباتی: خطا — {res.get('error')}")
    except Exception as e:
        print(f"بانک محاسباتی: خطا — {e}")


if __name__ == "__main__":
    main()
