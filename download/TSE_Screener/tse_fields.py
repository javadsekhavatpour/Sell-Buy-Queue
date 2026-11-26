#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tse_fields.py — نام‌گذاری استاندارد فیلدهای بانک‌ها بر اساس فیلدهای TSETMC

مرجع نام‌ها: متغیرهای فیلترنویسی دیده‌بان بازار سایت TSETMC (همان نام‌هایی که
برای نوشتن فیلتر استفاده می‌شود) — تأییدشده از:
  - gist «متغیرهای بورس» (tayyebi): py، pf، pmin، pmax، pl، plc، plp، pc، pcc،
    pcp، tno، tvol، tval، bvol و صف سفارش‌ها pd/qd/zd (خرید) و po/qo/zo (فروش)
  - جدول «فیلترها و متغیرهای سایت tsetmc» (bourse-trader.ir/tsetmc): فیلدهای
    حقیقی/حقوقی با فرم (ct).Buy_I_Volume، (ct).Buy_CountI، (ct).Buy_I_Value و…

قاعده: هر فیلدِ «دریافتی از TSE» در بانک‌ها (raw_snapshots و history_daily) با
همان کد فیلتر TSETMC ذخیره می‌شود؛ فیلدهای محاسبه‌شدهٔ خودمان (قدرت خرید،
میانگین‌ها و…) نام معنایی خود را دارند و ۴ فیلد نمایشی سایت (plc/plp/pcc/pcp)
از pl/pc/py در لحظهٔ جمع‌آوری ساخته و در بانک هم ذخیره می‌شوند.

نقشهٔ کامل (قدیمی → کد TSE):
  قیمت‌ها:    last_price→pl   close_price→pc    open_price→pf
              yesterday_price→py   daily_high→pmax   daily_low→pmin
  معاملات:   trade_volume→tvol   trade_value→tval   trade_count→tno
  نمایشی:    plc تغییر آخرین (ریال)   plp درصد آخرین
              pcc تغییر پایانی (ریال)  pcp درصد پایانی
  حقیقی:     ct_real_buy_volume→buy_i_volume   ct_real_buy_value→buy_i_value
              ct_real_buy_count→buy_counti      (فیلتر: (ct).Buy_I_Volume …)
  حقوقی:     ct_legal_buy_volume→buy_n_volume  ct_legal_buy_value→buy_n_value
              ct_legal_buy_count→buy_countn
  فروش:      معادل‌های sell_* همان قاعده
  صف سفارش‌ها: buy_price_N→pdN  buy_volume_N→qdN  buy_orders_N→zdN
               sell_price_N→poN sell_volume_N→qoN sell_orders_N→zoN
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

# نقشهٔ تغییر نام — کلید: نام قبلی، مقدار: کد فیلتر TSETMC
TSE_FIELDS: dict[str, str] = {
    # قیمت‌ها
    "last_price": "pl",        # آخرین قیمت معامله
    "close_price": "pc",       # قیمت پایانی
    "open_price": "pf",        # اولین قیمت
    "yesterday_price": "py",   # قیمت دیروز
    "daily_high": "pmax",      # بیشترین قیمت روز
    "daily_low": "pmin",       # کمترین قیمت روز
    # معاملات
    "trade_volume": "tvol",    # حجم معاملات
    "trade_value": "tval",     # ارزش معاملات (ریال)
    "trade_count": "tno",      # تعداد معاملات
    # حقیقی/حقوقی — فرم فیلتر (ct).Buy_I_Volume و …
    "ct_real_buy_volume": "buy_i_volume",
    "ct_real_buy_value": "buy_i_value",
    "ct_real_buy_count": "buy_counti",
    "ct_legal_buy_volume": "buy_n_volume",
    "ct_legal_buy_value": "buy_n_value",
    "ct_legal_buy_count": "buy_countn",
    "ct_real_sell_volume": "sell_i_volume",
    "ct_real_sell_value": "sell_i_value",
    "ct_real_sell_count": "sell_counti",
    "ct_legal_sell_volume": "sell_n_volume",
    "ct_legal_sell_value": "sell_n_value",
    "ct_legal_sell_count": "sell_countn",
}
# صف سفارش‌ها — ۵ ردیف خرید (pd/qd/zd) و ۵ ردیف فروش (po/qo/zo)
for _i in range(1, 6):
    TSE_FIELDS[f"buy_price_{_i}"] = f"pd{_i}"      # قیمت خرید ردیف i
    TSE_FIELDS[f"buy_volume_{_i}"] = f"qd{_i}"     # حجم خرید ردیف i
    TSE_FIELDS[f"buy_orders_{_i}"] = f"zd{_i}"     # تعداد خریدار ردیف i
    TSE_FIELDS[f"sell_price_{_i}"] = f"po{_i}"     # قیمت فروش ردیف i
    TSE_FIELDS[f"sell_volume_{_i}"] = f"qo{_i}"    # حجم فروش ردیف i
    TSE_FIELDS[f"sell_orders_{_i}"] = f"zo{_i}"    # تعداد فروشنده ردیف i

# فیلدهای نمایشی TSETMC که در بانک هم ذخیره می‌شوند (از pl/pc/py)
DERIVED_FIELDS: dict[str, str] = {
    "plc": "REAL",  # تغییر آخرین قیمت (ریال) = pl − py
    "plp": "REAL",  # درصد تغییر آخرین قیمت = (pl − py) ÷ py × ۱۰۰
    "pcc": "REAL",  # تغییر قیمت پایانی (ریال) = pc − py
    "pcp": "REAL",  # درصد تغییر قیمت پایانی = (pc − py) ÷ py × ۱۰۰
}


def derived_values(pl, pc, py) -> dict:
    """محاسبهٔ ۴ فیلد نمایشی TSETMC از خام — دقیقاً مثل دیده‌بان سایت."""
    out = {"plc": None, "plp": None, "pcc": None, "pcp": None}

    def _f(v):
        try:
            return float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            return None

    pyv = _f(py)
    if not pyv:
        return out
    plv, pcv = _f(pl), _f(pc)
    if plv is not None:
        out["plc"] = plv - pyv                       # تغییر آخرین (ریال)
        out["plp"] = round((plv - pyv) / pyv * 100, 2)  # درصد آخرین
    if pcv is not None:
        out["pcc"] = pcv - pyv                       # تغییر پایانی (ریال)
        out["pcp"] = round((pcv - pyv) / pyv * 100, 2)  # درصد پایانی
    return out


def migrate_bank(db_path: Path, tables: tuple[str, ...] = ("raw_snapshots",
                                                               "history_daily")) -> dict:
    """مهاجرت نام ستون‌های بانک به کدهای TSETMC + افزودن فیلدهای نمایشی.

    برای هر جدول موجود: ستون‌های قدیمی RENAME می‌شوند (داده حفظ می‌شود)،
    سپس plc/plp/pcc/pcp در صورت نبود اضافه و از pl/pc/py پر می‌شوند.
    اجرای دوباره بی‌اثر است (idempotent).
    """
    if not db_path.exists():
        return {"ok": False, "renamed": [], "added": []}
    con = sqlite3.connect(str(db_path))
    renamed: list[str] = []
    added: list[str] = []
    try:
        for tbl in tables:
            has = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (tbl,)).fetchone()
            if not has:
                continue
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({tbl})")}
            for old, new in TSE_FIELDS.items():
                if old in cols and new not in cols:
                    con.execute(f'ALTER TABLE {tbl} RENAME COLUMN "{old}" TO "{new}"')
                    renamed.append(f"{tbl}.{old}→{new}")
                    cols.discard(old)
                    cols.add(new)
            for d, typ in DERIVED_FIELDS.items():
                if d not in cols:
                    con.execute(f"ALTER TABLE {tbl} ADD COLUMN {d} {typ}")
                    added.append(f"{tbl}.{d}")
                    cols.add(d)
            # پرکردن فیلدهای نمایشی از خام
            con.execute(
                f"UPDATE {tbl} SET plc = pl - py, "
                "plp = ROUND((pl - py) / py * 100, 2), "
                "pcc = pc - py, "
                "pcp = ROUND((pc - py) / py * 100, 2) "
                "WHERE py IS NOT NULL AND py != 0 AND plc IS NULL")
        con.commit()
    finally:
        con.close()
    return {"ok": True, "renamed": renamed, "added": added}


if __name__ == "__main__":
    import sys
    targets = sys.argv[1:] or ["data/raw"]
    for t in targets:
        p = Path(t)
        dbs = [p] if p.is_file() else sorted(p.glob("*.sqlite"))
        for db in dbs:
            r = migrate_bank(db)
            print(f"{db.name}: {len(r['renamed'])} تغییر نام، "
                  f"{len(r['added'])} ستون افزوده — {r['renamed'][:4]}…")
