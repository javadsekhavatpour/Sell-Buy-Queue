#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
raw_collector.py — جمع‌آورِ دادهٔ خام (نسخهٔ ایزوله برای حل مشکل ذخیره‌سازی)

فلسفه: فقط همان چیزی که از لایو بازار دریافت می‌شود، مستقیم در بانک:
  - یک بانک، یک جدول (raw_snapshots) — بدون aggregate/trades/metadata
  - بدون هیچ محاسبه روی فیلدها — بدون derived، بدون min/max مجاز، بدون فاز بازار،
    بدون data_status، بدون carry-forward. هر مقدار دقیقاً همان پاسخ TSETMC است.
  - اگر endpoint قیمت جواب نداد → آن دوره هیچ ردیفی در بانک نمی‌گیرد
    (بدون دادهٔ ساختگی/صفر).
  - endpoint سفارش‌ها یا حقیقی/حقوقی اگر خطا داد → ستون‌هایش NULL می‌ماند
    (NULL = «دریافت نشد»، به‌صورت «—» در داشبورد) — نه صفر ساختگی.
  - پیش‌فرض هر ۳۰ ثانیه (با --interval قابل تغییر برای تست).

فیلدهای دریافت‌شده از لایو (مپ ۱:۱ با کلیدهای API — نام ستون بانک = کد فیلتر
TSETMC، مطابق tse_fields.py):

  ClosingPrice/GetClosingPriceInfo/{insCode}
    pDrCotVal      → pl           (آخرین قیمت معامله)
    pClosing       → pc           (قیمت پایانی)
    priceFirst     → pf           (اولین قیمت روز)
    priceYesterday → py           (قیمت دیروز)
    priceMax       → pmax         (بیشترین قیمت روز)
    priceMin       → pmin         (کمترین قیمت روز)
    qTotTran5J     → tvol         (حجم کل معاملات)
    qTotCap        → tval         (ارزش کل - ریال)
    zTotTran       → tno          (تعداد معاملات)
    hEven          → api_last_trade_time (ساعت آخرین معامله طبق TSETMC)
    dEven          → api_date          (تاریخ پاسخ API - میلادی yyyymmdd)
    instrumentState.cEtavalTitle → api_symbol_status (مجاز/مسدود/...)

  BestLimits/{insCode}  (۵ ردیف خرید + ۵ ردیف فروش)
    pMeDem / qTitMeDem / zOrdMeDem → buy_price_N / buy_volume_N / buy_orders_N
    pMeOf  / qTitMeOf  / zOrdMeOf   → sell_price_N / sell_volume_N / sell_orders_N

  ClientType/GetClientType/{insCode}
    buy_I_Volume   → ct_real_buy_volume    (حجم خرید حقیقی)
    buy_N_Volume   → ct_legal_buy_volume   (حجم خرید حقوقی)
    sell_I_Volume  → ct_real_sell_volume   (حجم فروش حقیقی)
    sell_N_Volume  → ct_legal_sell_volume  (حجم فروش حقوقی)
    buy_CountI     → ct_real_buy_count     (تعداد خریداران حقیقی)
    buy_CountN     → ct_legal_buy_count    (تعداد خریداران حقوقی)
    sell_CountI    → ct_real_sell_count    (تعداد فروشندگان حقیقی)
    sell_CountN    → ct_legal_sell_count   (تعداد فروشندگان حقوقی)

  + شناسه‌های ثبت (نه دادهٔ بازار، نه محاسبه): fetch_time، fetch_hms،
    date_jalali، symbol، ins_code

اجرا (چندنمادی — پیش‌فرض ۱۴ نماد، تایم‌کاری از config/symbols.json):
  python raw_collector.py                       # همهٔ ۱۴ نماد، هر ۳۰ ثانیه، همیشه اجرا
  python raw_collector.py --symbols سرود,کپارس  # زیرمجموعه
  python raw_collector.py --symbol سرود         # تک‌نماد

گیت تایم‌کاری: فقط وقتی ساعت تهران داخل بازه‌های pre_open/continuous همان نماد
در config/symbols.json باشد رکورد می‌شود (معادل فاز preopen/continuous)؛ بیرون
آن‌ها هیچ ردیفی نوشته نمی‌شود.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from early_warning.data_collector import MarketDataCollector
from early_warning.market_detector import tehran_now
from early_warning.price_range import to_jalali
from tse_fields import derived_values as tse_derived  # فیلدهای نمایشی TSETMC

# ترتیب ستون‌های جدول خام — هر ستون یا مستقیم از API است یا شناسهٔ ثبت
COLUMNS = [
    "fetch_time", "fetch_hms", "date_jalali", "symbol", "ins_code",
    "api_date", "api_last_trade_time", "api_symbol_status",
    # قیمت‌ها و معاملات — کدهای فیلترنویسی TSETMC (تغییر نام از نسخهٔ قبل)
    "pl", "pc", "pf", "py", "pmax", "pmin",
    "plc", "plp", "pcc", "pcp",   # نمایشی — از pl/pc/py در لحظهٔ دریافت
    "tvol", "tval", "tno",
    # صف سفارش‌ها — pd/qd/zd خرید، po/qo/zo فروش (۱ تا ۵)
    "pd1", "qd1", "zd1", "pd2", "qd2", "zd2", "pd3", "qd3", "zd3",
    "pd4", "qd4", "zd4", "pd5", "qd5", "zd5",
    "po1", "qo1", "zo1", "po2", "qo2", "zo2", "po3", "qo3", "zo3",
    "po4", "qo4", "zo4", "po5", "qo5", "zo5",
    # حقیقی/حقوقی — فرم فیلتر (ct).Buy_I_Volume و …
    "buy_i_volume", "sell_i_volume", "buy_n_volume", "sell_n_volume",
    "buy_counti", "sell_counti", "buy_countn", "sell_countn",
]


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    real = {"pl", "pc", "pf", "py", "pmax", "pmin", "tval",
            "plc", "plp", "pcc", "pcp",
            "pd1", "pd2", "pd3", "pd4", "pd5", "po1", "po2", "po3", "po4", "po5"}
    cols = ",\n    ".join(
        f"{c} {'TEXT' if c in ('fetch_time', 'fetch_hms', 'date_jalali', 'symbol', 'ins_code', 'api_date', 'api_last_trade_time', 'api_symbol_status') else 'REAL' if c in real else 'INTEGER'}"
        for c in COLUMNS
    )
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS raw_snapshots (\n"
        f"    id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        f"    {cols}\n"
        f")"
    )
    conn.commit()
    return conn


def _num(v):
    """تبدیل نوع (بدون هیچ تغییر مقداری). مقدار غایب → None."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _int(v):
    n = _num(v)
    return None if n is None else int(n)


def _fmt_heven(v):
    """فقط قالب‌بندی نمایشی ساعت خام API (int HHMMSS مثل 95424 → '09:54:24')."""
    if v is None or v == "":
        return None
    try:
        n = int(v)
        return f"{n // 10000:02d}:{(n // 100) % 100:02d}:{n % 100:02d}"
    except (TypeError, ValueError):
        return str(v)


def fetch_raw(c: MarketDataCollector, ins_code: str) -> dict | None:
    """دریافت خام از سه endpoint. اگر قیمت نیامد → None (بدون ردیف)."""
    price = c._api_get(f"ClosingPrice/GetClosingPriceInfo/{ins_code}")
    info = (price or {}).get("closingPriceInfo") if isinstance(price, dict) else None
    if not isinstance(info, dict) or not info:
        return None

    row = {k: None for k in COLUMNS}
    now = tehran_now()
    row["fetch_time"] = now.isoformat(timespec="seconds")
    row["fetch_hms"] = now.strftime("%H:%M:%S")
    row["date_jalali"] = to_jalali(date.today())
    row["symbol"] = ""  # در main پر می‌شود
    row["ins_code"] = str(ins_code)

    # ── قیمت‌ها (دقیقاً همان پاسخ API) ──
    row["api_date"] = str(info.get("dEven") or "") or None
    row["api_last_trade_time"] = _fmt_heven(info.get("hEven"))
    st = info.get("instrumentState") or {}
    row["api_symbol_status"] = str(st.get("cEtavalTitle") or "") or None
    row["pl"] = _num(info.get("pDrCotVal"))         # pl — آخرین قیمت معامله
    row["pc"] = _num(info.get("pClosing"))          # قیمت پایانی
    row["pf"] = _num(info.get("priceFirst"))        # اولین قیمت
    row["py"] = _num(info.get("priceYesterday"))    # قیمت دیروز
    row["pmax"] = _num(info.get("priceMax"))        # بیشترین روز
    row["pmin"] = _num(info.get("priceMin"))        # کمترین روز
    row["tvol"] = _int(info.get("qTotTran5J"))      # حجم معاملات
    row["tval"] = _num(info.get("qTotCap"))         # ارزش معاملات (ریال)
    row["tno"] = _int(info.get("zTotTran"))         # تعداد معاملات
    # فیلدهای نمایشی TSETMC — همان اعدادی که دیده‌بان سایت نشان می‌دهد
    row.update(tse_derived(row["pl"], row["pc"], row["py"]))

    # ── ۵ ردیف سفارش خرید/فروش (به ترتیب پاسخ API؛ خالی → NULL) ──
    lim = c._api_get(f"BestLimits/{ins_code}")
    lst = []
    if isinstance(lim, dict):
        lst = (lim.get("bestLimits") or lim.get("BestLimits")
               or lim.get("bestLimitsHistory") or [])
    b = s = 0
    for r in lst:
        if not isinstance(r, dict):
            continue
        bp, bv, bc = r.get("pMeDem"), r.get("qTitMeDem"), r.get("zOrdMeDem")
        sp, sv, sc = r.get("pMeOf"), r.get("qTitMeOf"), r.get("zOrdMeOf")
        if bp and b < 5:
            b += 1
            row[f"pd{b}"] = _num(bp)     # قیمت خرید ردیف b
            row[f"qd{b}"] = _num(bv)     # حجم خرید ردیف b
            row[f"zd{b}"] = _int(bc)     # تعداد خریدار ردیف b
        if sp and s < 5:
            s += 1
            row[f"po{s}"] = _num(sp)     # قیمت فروش ردیف s
            row[f"qo{s}"] = _num(sv)     # حجم فروش ردیف s
            row[f"zo{s}"] = _int(sc)     # تعداد فروشنده ردیف s

    # ── حقیقی/حقوقی — کلیدهای mapped خروجی fetch_clienttype؛ خطا → همه NULL ──
    try:
        ct = c.fetch_clienttype(ins_code) or {}
    except Exception:
        ct = {}
    row["buy_i_volume"] = _num(ct.get("real_buy_volume"))    # (ct).Buy_I_Volume
    row["buy_n_volume"] = _num(ct.get("legal_buy_volume"))   # (ct).Buy_N_Volume
    row["sell_i_volume"] = _num(ct.get("real_sell_volume"))  # (ct).Sell_I_Volume
    row["sell_n_volume"] = _num(ct.get("legal_sell_volume"))  # (ct).Sell_N_Volume
    row["buy_counti"] = _int(ct.get("real_buy_count"))       # (ct).Buy_CountI
    row["buy_countn"] = _int(ct.get("legal_buy_count"))      # (ct).Buy_CountN
    row["sell_counti"] = _int(ct.get("real_sell_count"))     # (ct).Sell_CountI
    row["sell_countn"] = _int(ct.get("legal_sell_count"))    # (ct).Sell_CountN
    return row


# نمادهای پیش‌فرض جمع‌آوری (به‌ازای هر نماد یک بانک جدا در data/raw)
DEFAULT_SYMBOLS = ["فسوژ", "سیسکو", "کاما", "سرود", "صبا", "پخش", "کپارس",
                   "ریتون", "رانیز", "دلر", "کلوند", "دبالک", "غدانه", "سفانو"]


def load_symbols() -> dict:
    """بارگذاری نمادها از config/symbols.json (نام → رکورد کامل با تایم‌کاری)."""
    path = ROOT / "config" / "symbols.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["name"]: s for s in data.get("symbols", [])}


def in_trading_window(scfg: dict, now) -> bool:
    """گیت تایم‌کاری کانفیگ — معادل فازهای preopen/continuous.
    فقط داخل بازه‌های pre_open و continuous رکورد می‌شود؛ بیرون آن‌ها نه."""
    hm = now.strftime("%H:%M")
    for key in ("pre_open", "continuous"):
        w = (scfg.get("trading_hours") or {}).get(key) or []
        if len(w) == 2 and w[0] <= hm <= w[1]:
            return True
    return False


def main():
    ap = argparse.ArgumentParser(description="جمع‌آوری دادهٔ خام TSETMC — چندنمادی، یک جدول، بدون محاسبه")
    ap.add_argument("--symbols", default=None,
                    help="زیرمجموعه با کاما (پیش‌فرض: همهٔ ۱۴ نماد DEFAULT_SYMBOLS)")
    ap.add_argument("--symbol", default=None, help="تک‌نماد (جایگزین چندنمادی)")
    ap.add_argument("--ins-code", default=None, help="کد نماد تک‌نمادی (اگر در کانفیگ نیست)")
    ap.add_argument("--interval", type=int, default=30, help="ثانیه (پیش‌فرض ۳۰)")
    ap.add_argument("--max-cycles", type=int, default=0, help="۰ = همیشه اجرا (تا Ctrl+C)")
    args = ap.parse_args()

    # overrides برای حالت --symbol وقتی نماد در کانفیگ نیست
    overrides: dict = {}
    if args.symbol:
        names = [args.symbol]
        if args.ins_code:
            overrides[args.symbol] = {"name": args.symbol, "ins_code": args.ins_code,
                                      "trading_hours": {"pre_open": ["08:45", "09:00"],
                                                        "continuous": ["09:00", "12:30"]}}
        elif args.symbol not in load_symbols():
            print(f"✗ {args.symbol} در config/symbols.json نیست و --ins-code داده نشد.")
            sys.exit(1)
    else:
        names = ([s.strip() for s in args.symbols.split(",")] if args.symbols
                 else list(DEFAULT_SYMBOLS))

    c = MarketDataCollector({})
    conns: dict = {}  # نام نماد → اتصال بانک خودش

    print("=" * 70)
    print("  جمع‌آوری خام چندنمادی — فقط دادهٔ دریافتی از لایو، بدون هیچ محاسبه")
    print("=" * 70)
    print(f"  نمادهای درخواستی ({len(names)}): {', '.join(names)}")
    print(f"  بازه: هر {args.interval} ثانیه — فقط در pre_open/continuous رکورد می‌شود")
    print("  کانفیگ در هر دوره تازه خوانده می‌شود؛ افزودن نماد به symbols.json بدون")
    print(f"  راه‌اندازی مجدد، در دورهٔ بعدی فعال می‌شود.")
    print("  توقف: Ctrl+C")
    print()

    n_ok = n_fail = n_skip = 0
    cycle = 0
    last_missing = None
    try:
        while args.max_cycles == 0 or cycle < args.max_cycles:
            cycle += 1
            now = tehran_now()
            # تازه‌خوانی کانفیگ هر دوره — نمادهای افزوده‌شده بدون ری‌استارت فعال شوند
            syms = load_symbols()
            syms.update(overrides)
            selected = [n for n in names if n in syms]
            missing = [n for n in names if n not in syms]
            if missing and missing != last_missing:
                print(f"  ⚠ {len(missing)} نماد در config/symbols.json نیست و رد می‌شوند: {missing}")
                print(f"    نمادهای فعال این دوره: {len(selected)}/{len(names)} — کانفیگ را به‌روز کنید")
                last_missing = missing
            elif not missing and last_missing:
                print(f"  ✓ کانفیگ کامل شد — {len(selected)}/{len(names)} نماد فعال")
                last_missing = None
            if not selected:
                if args.max_cycles == 0 or cycle < args.max_cycles:
                    time.sleep(args.interval)
                continue
            any_window = False
            for n in selected:
                scfg = syms[n]
                if not in_trading_window(scfg, now):
                    n_skip += 1
                    continue
                any_window = True
                row = fetch_raw(c, str(scfg["ins_code"]))
                if row is None:
                    n_fail += 1
                    print(f"  [{now.strftime('%H:%M:%S')}] ✗ {n}: قیمت از لایو دریافت نشد — ردیفی نوشته نشد")
                    continue
                row["symbol"] = n
                conn = conns.setdefault(n, init_db(ROOT / f"data/raw/raw_{n}.sqlite"))
                conn.execute(
                    f"INSERT INTO raw_snapshots ({', '.join(COLUMNS)}) VALUES ({', '.join('?' for _ in COLUMNS)})",
                    [row[c_] for c_ in COLUMNS],
                )
                conn.commit()
                n_ok += 1
                print(f"  [{row['fetch_hms']}] ✓ {n} | pl={row['pl']} pf={row['pf']} "
                      f"pc={row['pc']} | معاملهٔ لایو: {row['api_last_trade_time']} | "
                      f"bid1={row['pd1']} ask1={row['po1']}")
            if not any_window:
                print(f"  [{now.strftime('%H:%M:%S')}] … خارج از تایم‌کاری — همهٔ {len(selected)} نماد رد شد "
                      f"(فقط preopen/continuous رکورد می‌شود)")
            if args.max_cycles == 0 or cycle < args.max_cycles:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n  توقف با Ctrl+C")
    finally:
        for conn in conns.values():
            conn.close()
        print(f"  پایان: {n_ok} ردیف نوشته شد، {n_fail} دورهٔ بدون داده، {n_skip} ردِ خارج از تایم‌کاری")


if __name__ == "__main__":
    main()
