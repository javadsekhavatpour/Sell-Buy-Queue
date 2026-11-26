#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""history_local_collector.py — جمع‌آوری سابقه از فایل‌های اکسل لوکال tradersarena.ir

پس‌زمینه: خروجی اکسل tradersarena نسبت به JSON آنلاین همان سایت اطلاعات کمتری دارد
(بدون «تعداد معاملات» و حجم‌های حقیقی/حقوقی، و ارزش‌ها به تومان گرد شده‌اند) اما
همهٔ ستون‌های لازمِ بانک محاسباتی را دارد. این اسکریپت همان داده را از فایل‌های
لوکال (که با اشتراک دانلود شده‌اند) به بانک خام می‌ریزد.

قاعدهٔ ادغام: INSERT … ON CONFLICT DO UPDATE SET col=COALESCE(excluded.col, col)
— یعنی ستون‌هایی که اکسل ندارد (tno، حجم‌ها، plc/pcc) از مقدار قبلی بانک حفظ
می‌شوند و ردیف‌های TSETMC خراب نمی‌شوند.

نماد از نام فایل تشخیص داده می‌شود: tradersarena_ریتون_2026-11-26.xlsx → ریتون
(پشتیبان: نام شیت مثل tradersArena.ir-ریتون). نماد ناشناخته جمع نمی‌شود و
در خروجی هشدار می‌گیرد.

مصرف CLI:
  python history_local_collector.py --folder /path/to/xlsx-folder
  python history_local_collector.py --files a.xlsx b.xlsx --days 60

از portfoli_server (مسیر /api/hcollect_local) هم صدا زده می‌شود.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

XLSX_PAT = re.compile(r"tradersarena[_\- ]+(.+?)[_\- ]*\d{4}[-.]\d{2}[-.]\d{2}", re.I)
SHEET_PAT = re.compile(r"tradersarena\.ir[- ]+(.+)", re.I)
DATE_ROW_PAT = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")

# هدر اکسل (پس از نرمال‌سازی) → ستون بانک. ضریب ۱۰ برای ستون‌های «(تومان)»
# هنگام خواندن از خود هدر تشخیص داده می‌شود — اگر «(ریال)» بود ضریب ۱.
COLMAP = {
    "حجم": ("tvol", "num"),
    "ارزش معاملات": ("tval", "money"),
    "اولین قیمت": ("pf", "num"),
    "بیشترین قیمت": ("pmax", "num"),
    "کمترین قیمت": ("pmin", "num"),
    "آخرین قیمت": ("pl", "num"),
    "درصد تغییر آخرین قیمت": ("plp", "num"),
    "قیمت پایانی": ("pc", "num"),
    "درصد تغییر قیمت پایانی": ("pcp", "num"),
    "قیمت دیروز": ("py", "num"),
    "کدهای خریدار حقیقی": ("buy_counti", "num"),
    "کدهای فروشنده حقیقی": ("sell_counti", "num"),
    "کدهای خریدار حقوقی": ("buy_countn", "num"),
    "کدهای فروشنده حقوقی": ("sell_countn", "num"),
    "ارزش خرید حقیقی": ("buy_i_value", "money"),
    "ارزش فروش حقیقی": ("sell_i_value", "money"),
    "ارزش خرید حقوقی": ("buy_n_value", "money"),
    "ارزش فروش حقوقی": ("sell_n_value", "money"),
}
# ستون‌هایی که اکسل ندارد — در ادغام از مقدار قبلی بانک حفظ می‌شوند
EXCEL_MISSING = ("tno", "buy_i_volume", "sell_i_volume", "buy_n_volume",
                 "sell_n_volume", "plc", "pcc")


def norm_header(h: str) -> str:
    """نرمال‌سازی هدر: حذف نیم‌فاصله، فاصله‌های تکراری، پرانتز واحد پول."""
    h = (h or "").replace("\u200c", " ").replace("\xa0", " ")
    return re.sub(r"\s+", " ", h).strip()


def parse_symbol_from_filename(name: str) -> str | None:
    """نماد از نام فایل: tradersarena_ریتون_2026-11-26.xlsx → ریتون."""
    m = XLSX_PAT.search(Path(name).stem)
    if m:
        return m.group(1).strip()
    return None


def parse_symbol_from_sheet(ws) -> str | None:
    m = SHEET_PAT.search(ws.title or "")
    return m.group(1).strip() if m else None


def jalali_to_greg(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """شمسی → میلادی (الگوریتم استاندارد JDF). 1405/09/04 → (2026, 11, 25)."""
    jy += 1595
    d = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    d += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186
    gy = 400 * (d // 146097)
    d %= 146097
    if d > 36524:
        d -= 1
        gy += 100 * (d // 36524)
        d %= 36524
        if d >= 365:
            d += 1
    gy += 4 * (d // 1461)
    d %= 1461
    if d > 365:
        gy += (d - 1) // 365
        d = (d - 1) % 365
    gd = d + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    ml = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    for i in range(1, 13):
        if gd <= ml[i]:
            gm = i
            break
        gd -= ml[i]
    return gy, gm, gd


def jstr_to_greg(s: str) -> str | None:
    """'1405/09/04' یا '1405-9-4' → '20261125'."""
    m = DATE_ROW_PAT.search(s or "")
    if not m:
        return None
    gy, gm, gd = jalali_to_greg(*map(int, m.groups()))
    return f"{gy:04d}{gm:02d}{gd:02d}"


def to_num(v, factor: float = 1.0) -> float | None:
    """سلول اکسل → عدد (حذف جداکنندهٔ هزارگان). None یا متنی بی‌عدد → None."""
    if v is None or isinstance(v, (int, float)):
        return float(v) * factor if v is not None else None
    s = re.sub(r"[,\u060c\s]", "", str(v))
    if not s or not re.match(r"^-?\d+(\.\d+)?$", s):
        return None
    return float(s) * factor


def rows_from_workbook(src, symbol_hint: str | None = None) -> tuple[list[dict], str | None]:
    """خواندن ردیف‌های سابقه از یک فایل اکسل. src = مسیر یا BytesIO."""
    import openpyxl
    wb = openpyxl.load_workbook(src, read_only=True, data_only=True)
    ws = wb.active
    rows_raw = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows_raw:
        return [], symbol_hint
    # هدر: اولین ردیفی که ستون «تاریخ» را دارد
    hi = next((i for i, r in enumerate(rows_raw)
               if r and norm_header(str(r[0])) == "تاریخ"), None)
    if hi is None:
        return [], symbol_hint
    hdr = [norm_header(str(h)) if h is not None else "" for h in rows_raw[hi]]
    # واحد پول هر ستون از خود هدر: «(تومان)» → ×۱۰ ، «(ریال)» → ×۱
    money_factor = {}
    for j, h in enumerate(hdr):
        base = re.sub(r"\s*\((تومان|ریال)\)\s*$", "", h).strip()
        if base in COLMAP and COLMAP[base][1] == "money":
            money_factor[base] = 10.0 if "(تومان)" in h else 1.0
    out: list[dict] = []
    symbol = symbol_hint
    for r in rows_raw[hi + 1:]:
        if not r or r[0] is None:
            continue  # ردیف‌های خالی قالب اکسل
        rec: dict = {}
        rec["date_jalali"] = norm_header(str(r[0]))
        rec["date_greg"] = jstr_to_greg(rec["date_jalali"])
        if not rec["date_greg"]:
            continue
        for j, h in enumerate(hdr):
            base = re.sub(r"\s*\((تومان|ریال)\)\s*$", "", h).strip()
            if base in COLMAP:
                col = COLMAP[base][0]
                rec[col] = to_num(r[j], money_factor.get(base, 1.0))
        if not any(rec.get(c) is not None for c in ("pc", "pl", "tvol", "tval")):
            continue  # ردیف بی‌داده
        out.append(rec)
    if not symbol:
        symbol = parse_symbol_from_sheet(ws)
    return out, symbol


# ستون‌های ریالی که اکسل فقط با گرد شدن تومانی دارد — اگر بانک از TSETMC
# مقدار دقیق دارد، همان حفظ می‌شود؛ اکسل فقط برای روزهای نو مقدار می‌دهد.
MONEY_PREFER_EXISTING = ("tval", "buy_i_value", "sell_i_value",
                         "buy_n_value", "sell_n_value")


def upsert_rows(con: sqlite3.Connection, symbol: str, ins_code: str,
                rows: list[dict]) -> tuple[int, int]:
    """درج/ادغام با حفظ ستون‌های موجودِ بدون مقدار در اکسل. خروجی: (جدید، به‌روزرسانی)

    ستون‌های عادی (قیمت/حجم/کدها — مقادیر دقیق در اکسل): مقدار جدید مقدسِ موجود را
    اصلاح می‌کند. ستون‌های ریالی: مقدار دقیق قبلی بانک حفظ می‌شود.
    """
    cols = [c[1] for c in con.execute("PRAGMA table_info(history_daily)")]
    new = updated = 0
    for rec in rows:
        exists = con.execute(
            "SELECT 1 FROM history_daily WHERE symbol=? AND date_greg=?",
            (symbol, rec["date_greg"])).fetchone() is not None
        vals = {c: None for c in cols}
        vals.update({k: v for k, v in rec.items() if k in vals})
        vals["symbol"] = symbol
        if ins_code:
            vals["ins_code"] = ins_code
        use = [c for c in cols if c not in ("symbol", "date_greg")]
        sets = ", ".join(
            f"{c}=COALESCE({c}, excluded.{c})" if c in MONEY_PREFER_EXISTING
            else f"{c}=COALESCE(excluded.{c}, {c})" for c in use)
        con.execute(
            f"INSERT INTO history_daily (symbol, date_greg, {', '.join(use)}) "
            f"VALUES (?, ?, {', '.join('?' * len(use))}) "
            f"ON CONFLICT(symbol, date_greg) DO UPDATE SET {sets}",
            [symbol, rec["date_greg"]] + [vals[c] for c in use])
        new += 0 if exists else 1
        updated += 1 if exists else 0
    con.commit()
    return new, updated


def load_ins_codes() -> dict[str, str]:
    cfg = HERE / "config" / "symbols.json"
    try:
        d = json.loads(cfg.read_text(encoding="utf-8"))
        return {s["name"]: s.get("ins_code", "") for s in d.get("symbols", [])}
    except Exception:
        return {}


def collect(root: Path, folder: str | None = None,
            files: list[tuple[str, bytes]] | None = None,
            days: int = 30) -> dict:
    """جریان کامل: خواندن فایل‌ها → ادغام در بانک خام → بانک محاسباتی → بایگانی."""
    root = Path(root)
    codes = load_ins_codes()
    items: list[tuple[str, bytes]] = []
    if files:
        items = list(files)
    elif folder:
        p = Path(folder)
        if not p.is_dir():
            return {"ok": False, "error": f"پوشه پیدا نشد: {folder}"}
        items = [(f.name, f.read_bytes())
                 for f in sorted(p.glob("*.xlsx"))]
    if not items:
        return {"ok": False, "error": "فایل اکسلی پیدا نشد"}

    per_file, log = [], []
    db = root / "data" / "raw" / "history.sqlite"
    if not db.exists():
        return {"ok": False, "error": f"بانک خام نیست: {db} — اول جمع‌آوری آنلاین"}
    con = sqlite3.connect(str(db))
    total_new = total_upd = 0
    log.append(f"منبع: {len(items)} فایل اکسل → مقصد: data/raw/history.sqlite "
               f"(جدول history_daily) — سپس بانک محاسباتی و بایگانی")
    for name, blob in items:
        sym = parse_symbol_from_filename(name)
        try:
            rows, sym_fallback = rows_from_workbook(io.BytesIO(blob), symbol_hint=sym)
            sym = sym or sym_fallback
        except Exception as e:
            per_file.append({"file": name, "ok": False, "error": f"خواندن نشد: {e}"})
            log.append(f"✗ {name}: خواندن نشد — {e}")
            continue
        if not sym:
            per_file.append({"file": name, "ok": False, "error": "نماد از نام فایل/شیت تشخیص داده نشد"})
            log.append(f"✗ {name}: نماد تشخیص داده نشد")
            continue
        if sym not in codes:
            per_file.append({"file": name, "symbol": sym, "ok": False,
                             "error": "نماد در symbols.json نیست — نادیده گرفته شد"})
            log.append(f"⚠ {name}: نماد «{sym}» در بانک نیست — نادیده گرفته شد")
            continue
        n_new, n_upd = upsert_rows(con, sym, codes[sym], rows)
        total_new += n_new
        total_upd += n_upd
        rmin = min(rows, key=lambda r: r["date_greg"])
        rmax = max(rows, key=lambda r: r["date_greg"])
        per_file.append({"file": name, "symbol": sym, "ok": True,
                         "rows": len(rows), "new": n_new, "updated": n_upd,
                         "oldest": rmin["date_jalali"], "newest": rmax["date_jalali"]})
        log.append(f"✓ {name} → «{sym}»: {len(rows)} روز "
                   f"(از {rmin['date_jalali']} تا {rmax['date_jalali']}) — "
                   f"{n_new} جدید، {n_upd} به‌روزرسانی")
    con.close()

    import history_dashboard as hd
    res = hd.refresh_computed(root)
    bf = hd.backfill_portfoli_history(root, days)
    log.append(f"بانک محاسباتی: {'به‌روز شد' if res.get('ok') else res.get('error', 'خطا')}")
    if bf.get("ok"):
        log.append(f"بایگانی portfoli_history: {bf.get('added')} ردیف جدید تا {bf.get('days')} روز")

    return {"ok": True, "mode": "لوکال", "per_file": per_file, "log": log,
            "files": len(items), "new_rows": total_new, "updated_rows": total_upd,
            "backfilled": bf.get("added"), "archive_days": bf.get("days"),
            "last_dates": bf.get("last_dates")}


def main() -> None:
    ap = argparse.ArgumentParser(description="جمع‌آوری سابقه از اکسل‌های لوکال tradersarena")
    ap.add_argument("--folder", help="پوشهٔ فایل‌های اکسل")
    ap.add_argument("--files", nargs="*", help="فایل‌های اکسل مشخص")
    ap.add_argument("--days", type=int, default=30, help="بازهٔ بایگانی portfoli_history")
    ap.add_argument("--root", default=str(HERE), help="ریشهٔ پروژه")
    a = ap.parse_args()
    files = [(Path(f).name, Path(f).read_bytes()) for f in (a.files or [])]
    res = collect(Path(a.root), folder=a.folder, files=files, days=a.days)
    for line in res.get("log", []):
        print(line)
    if res.get("error"):
        print("خطا:", res["error"])
    sys.exit(0 if res.get("ok") else 1)


if __name__ == "__main__":
    main()
