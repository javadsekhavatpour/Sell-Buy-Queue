#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfoli_server.py — سرور لایو داشبورد «portfoli»

داشبورد را باز می‌کند و داده را مستقیم از بانک‌های خام (data/raw/raw_*.sqlite)
به‌صورت زنده می‌خواند؛ صفحه هر ۳۰ ثانیه یک بار خودش را تازه می‌کند (بدون رفرش صفحه).

اجرا (فایل را داخل ریشهٔ TSE_Screener کپی کنید، کنار portfoli.html):
    python portfoli_server.py                ← http://localhost:8017
    python portfoli_server.py --port 8080
    python portfoli_server.py --root مسیر/دیگر/TSE_Screener   (پیش‌فرض: پوشهٔ همین فایل)

نکته: در حالت لایو نیازی به export_portfoli_data.py نیست؛ همان موتور ساخت داده
(export_portfoli_data.build_payload) در هر درخواست مستقیم از sqlite می‌خواند.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import urllib.parse
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import export_portfoli_data as exp  # noqa: E402  (هم‌پوشان با این فایل)

DEFAULT_PORT = 8017

HISTORY_SQL = """
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


def save_history(payload: dict, root: Path) -> int:
    """ذخیرهٔ سطرهای محاسبه‌شده در data/raw/portfoli_history.sqlite (بدون تکرار).

    هر بار که داشبورد داده می‌گیرد، اگر نمونهٔ تازه‌ای در بانک خام باشد، نسخهٔ
    محاسبه‌شدهٔ کامل آن (همهٔ شاخص‌های مشتق) اینجا بایگانی می‌شود تا بعداً برای
    شبیه‌سازی و مرور در دسترس باشد.
    """
    hist = root / "data" / "raw" / "portfoli_history.sqlite"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(str(hist))
    added = 0
    try:
        con.execute(HISTORY_SQL)
        for r in payload.get("rows", []):
            if not r.get("date_jalali") or not r.get("fetch_hms"):
                continue
            cur = con.execute(
                "INSERT OR IGNORE INTO computed_samples "
                "(saved_at, date_jalali, fetch_hms, symbol, payload) VALUES (?,?,?,?,?)",
                (now, str(r["date_jalali"]), str(r["fetch_hms"]), str(r["symbol"]),
                 json.dumps(r, ensure_ascii=False)))
            added += cur.rowcount
        con.commit()
    finally:
        con.close()
    return added


def history_summary(root: Path) -> dict:
    """خلاصهٔ بایگانی محاسبات — تاریخ‌ها، تعداد نمونه‌ها و بازهٔ زمانی هر روز."""
    hist = root / "data" / "raw" / "portfoli_history.sqlite"
    if not hist.exists():
        return {"dates": []}
    con = sqlite3.connect(str(hist))
    try:
        rs = con.execute(
            "SELECT date_jalali, COUNT(*), COUNT(DISTINCT fetch_hms), "
            "MIN(fetch_hms), MAX(fetch_hms) FROM computed_samples "
            "GROUP BY date_jalali ORDER BY date_jalali"
        ).fetchall()
    finally:
        con.close()
    return {"dates": [{"date_jalali": d, "samples": n, "ticks": t,
                       "first": f, "last": l} for d, n, t, f, l in rs]}


def _norm_date(s: str | None) -> str | None:
    """نرمال‌سازی تاریخ شمسی: 1405-08-30 و 1405/8/30 → 1405/08/30."""
    s = (s or "").strip().replace("-", "/").replace(".", "/")
    if not s:
        return None
    parts = s.split("/")
    if len(parts) == 3 and all(p.isdigit() for p in parts):
        return f"{parts[0]}/{int(parts[1]):02d}/{int(parts[2]):02d}"
    return s


def _replay_frames(root: Path, symbol: str, date: str | None, max_frames: int,
                   trend_window: int) -> dict:
    """فریم‌های بازپخش از بانک خام — کل جدول یا فقط یک نماد.

    portfoli_sim تنبل import می‌شود؛ build_frames همان محاسبات لایو را روی
    نمونه‌های همان لحظه اجرا می‌کند و _meta برای نمایش داشبورد بازسازی می‌شود.
    """
    import portfoli_sim as psim  # noqa: PLC0415  (تنبل — فقط برای بازپخش)
    date, per_symbol, per_cfg = psim.collect_day(root, date)
    if symbol:
        if symbol not in per_symbol:
            raise ValueError(f"برای نماد «{symbol}» در تاریخ {date or 'آخرین روز'} "
                             "داده‌ای در بانک خام نیست")
        per_symbol = {symbol: per_symbol[symbol]}
        per_cfg = {symbol: per_cfg[symbol]}
    frames = psim.build_frames(per_symbol, per_cfg, root, date, max_frames, trend_window)
    if not frames:
        raise ValueError(f"برای تاریخ {date or 'آخرین روز'} هیچ نمونه‌ای در بانک خام نیست")
    for f in frames:
        for r in f["rows"]:
            s = per_cfg.get(r["symbol"], {})
            r["_meta"] = {"name": r["symbol"], "market_label": s.get("market_label", ""),
                          "ins_code": str(s.get("ins_code", ""))}
    return {"date": date, "symbol": symbol or None, "frames": frames,
            "trend_window": trend_window}


def available_dates(root: Path) -> list[str]:
    """همهٔ تاریخ‌های موجود در بانک‌های خام — برای پرش به تاریخ در بازپخش."""
    dates: set[str] = set()
    for db in (root / "data" / "raw").glob("raw_*.sqlite"):
        try:
            con = sqlite3.connect(str(db))
            try:
                for (d,) in con.execute("SELECT DISTINCT date_jalali FROM raw_snapshots"):
                    if d:
                        dates.add(str(d))
            finally:
                con.close()
        except sqlite3.Error:
            pass  # بانک قفل/خراب — تاریخ‌های بقیه کافی است
    return sorted(dates)


# ستون‌های گزارش سابقه — (برچسب فارسی، فیلد محاسبه‌شدهٔ build_history_data، نام فیلد بانک یا توضیح محاسبه)
HISTORY_EXPORT_COLS = [
    ("تاریخ", None, "date_jalali"),
    ("نماد", None, "symbol"),
    ("قیمت پایانی", "close_price", "close_price"),
    ("٪ نوسان پایانی", "pct_close", "محاسبه: (پایانی − دیروز) ÷ دیروز × ۱۰۰"),
    ("ورود پول (ریال)", "flow_rial", "محاسبه: ارزش خرید حقیقی − ارزش فروش حقیقی"),
    ("میانگین ۵ روزه ورود پول (ریال)", "flow_avg5_rial", "محاسبه: میانگین کامل ۵ روز قبل (بدون امروز)"),
    ("میانگین ۱۰ روزه ورود پول (ریال)", "flow_avg10_rial", "محاسبه: میانگین کامل ۱۰ روز قبل"),
    ("میانگین ۲۰ روزه ورود پول (ریال)", "flow_avg20_rial", "محاسبه: میانگین کامل ۲۰ روز قبل"),
    ("میانگین ۳۰ روزه ورود پول (ریال)", "flow_avg30_rial", "محاسبه: میانگین کامل ۳۰ روز قبل"),
    ("حجم روز", "trade_volume", "trade_volume"),
    ("میانگین ۵ روزه حجم (سهم)", "vol_avg5", "محاسبه: میانگین کامل ۵ روز قبل"),
    ("میانگین ۱۰ روزه حجم (سهم)", "vol_avg10", "محاسبه: میانگین کامل ۱۰ روز قبل"),
    ("میانگین ۲۰ روزه حجم (سهم)", "vol_avg20", "محاسبه: میانگین کامل ۲۰ روز قبل"),
    ("میانگین ۳۰ روزه حجم (سهم)", "vol_avg30", "محاسبه: میانگین کامل ۳۰ روز قبل"),
    ("قدرت خرید روز", "buy_power", "محاسبه: (ارزش خرید÷تعداد خریداران) ÷ (ارزش فروش÷تعداد فروشندگان)"),
    ("میانگین قدرت خرید ۵ روز", "buy_power_avg5", "محاسبه: میانگین کامل ۵ روز قبل"),
    ("میانگین قدرت خرید ۱۰ روز", "buy_power_avg10", "محاسبه: میانگین کامل ۱۰ روز قبل"),
    ("میانگین قدرت خرید ۲۰ روز", "buy_power_avg20", "محاسبه: میانگین کامل ۲۰ روز قبل"),
    ("میانگین قدرت خرید ۳۰ روز", "buy_power_avg30", "محاسبه: میانگین کامل ۳۰ روز قبل"),
    ("تعداد خریدار به فروشنده", "bs_count_ratio", "محاسبه: تعداد خریداران ÷ فروشندگان حقیقی"),
    ("درصد خرید حقیقی از کل معاملات", "real_buy_pct", "محاسبه: ارزش خرید حقیقی ÷ ارزش کل × ۱۰۰"),
    ("واکنش قیمت (٪)", "reaction_pct", "محاسبه: جای آخرین قیمت بین کف و سقف مجاز"),
]


def _fmt_compact(v) -> str | None:
    """همهٔ اعداد به شکل خلاصهٔ لاتین 21.24T / 885.43B / 277.88M — کوچک‌تر از میلیون بدون پسوند."""
    if v is None:
        return None
    if isinstance(v, str):
        return v
    try:
        x = float(v)
    except (TypeError, ValueError):
        return v
    a = abs(x)
    if a >= 1e12:
        return f"{x / 1e12:.2f}T"
    if a >= 1e9:
        return f"{x / 1e9:.2f}B"
    if a >= 1e6:
        return f"{x / 1e6:.2f}M"
    return f"{x:,.2f}"


def _history_export_xlsx(root: Path, symbol: str | None) -> bytes:
    """اکسل گزارش «سابقهٔ نمادها» — همان ستون‌ها و ترتیب جدول history.html.

    سطر ۱: برچسب فارسی — سطر ۲: نام فیلد بانک خام (یا توضیح محاسبه). بعد از
    ستون‌های جدول، همهٔ ستون‌های بلااستفادهٔ بانک هم می‌آیند (درخواست کاربر:
    ردیف نام فیلد بانک حتی برای فیلدهایی که ستون جدول ندارند). همهٔ اعداد
    خلاصهٔ T/B/M؛ شیت راست‌به‌چپ؛ symbol=* یا خالی یعنی همهٔ نمادها.
    """
    import history_dashboard
    data = history_dashboard.build_history_data(root)
    if not data.get("ok"):
        raise ValueError(data.get("error") or "دادهٔ سابقه در دسترس نیست")
    con = sqlite3.connect(str(root / "data" / "raw" / "history.sqlite"))
    con.row_factory = sqlite3.Row
    try:
        bank_cols = [r[1] for r in con.execute("PRAGMA table_info(history_daily)")]
        used_bank = {src for _, _, src in HISTORY_EXPORT_COLS
                     if not src.startswith("محاسبه")}
        unused = [c for c in bank_cols if c not in used_bank and c != "id"]
        if symbol and symbol != "*":
            rs = con.execute("SELECT * FROM history_daily WHERE symbol=?",
                             (symbol,)).fetchall()
        else:
            rs = con.execute("SELECT * FROM history_daily").fetchall()
    finally:
        con.close()
    raw_rows = {(r["symbol"], r["date_jalali"]): dict(r) for r in rs}

    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "سابقهٔ نمادها"
    ws.sheet_view.rightToLeft = True
    fill = PatternFill("solid", fgColor="2F5597")
    hfont = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
    sfill = PatternFill("solid", fgColor="D9E2F3")
    sfont = Font(name="Tahoma", size=8, italic=True, color="1F3864")
    body = Font(name="Tahoma", size=10)
    al = Alignment(horizontal="center", vertical="center")
    head1 = [lab for lab, _, _ in HISTORY_EXPORT_COLS] + unused
    head2 = [src for _, _, src in HISTORY_EXPORT_COLS] + unused
    for j, h in enumerate(head1, 1):
        c = ws.cell(row=1, column=j, value=h)
        c.fill, c.font, c.alignment = fill, hfont, al
    for j, s in enumerate(head2, 1):
        c = ws.cell(row=2, column=j, value=s)
        c.fill, c.font, c.alignment = sfill, sfont, al
    picked = [s for s in data["symbols"]
              if not symbol or symbol == "*" or s["name"] == symbol]
    if not picked:
        raise ValueError("نماد در بانک سابقه نیست: " + str(symbol))
    r = 3
    for s in sorted(picked, key=lambda x: x["name"]):
        for row in s["rows"]:
            raw = raw_rows.get((s["name"], row["date_jalali"])) or {}
            vals = [row.get("date_jalali"), s["name"]]
            vals += [row.get(f) for _, f, _src in HISTORY_EXPORT_COLS[2:]]
            vals += [raw.get(c) for c in unused]
            for j, v in enumerate(vals, 1):
                c = ws.cell(row=r, column=j, value=_fmt_compact(v))
                c.font, c.alignment = body, al
            r += 1
    for j, w in enumerate([12, 10, 12, 12, 13, 15, 15, 15, 15, 12, 14, 14, 14, 14,
                           12, 14, 14, 14, 14, 14, 18, 12], 1):
        ws.column_dimensions[get_column_letter(j)].width = w
    for j in range(len(HISTORY_EXPORT_COLS) + 1, len(head1) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 13
    ws.freeze_panes = "A3"
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


def _replay_export_xlsx(data: dict, root: Path) -> bytes:
    """اکسل خروجی بازپخش: شیت «لحظهٔ انتخابی» + شیت «سری زمانی تا این لحظه».

    سطرها را مرورگر می‌فرستد (ستون‌های نمایان) — هم‌شکل همان جدولی که کاربر
    می‌بیند. سطر ۱ برچسب فارسی، سطر ۲ نام فیلد بانک خام؛ بعد از ستون‌های جدول
    همهٔ ستون‌های بلااستفادهٔ بانک خام هم از نمونهٔ همان لحظه می‌آیند.
    همهٔ اعداد خلاصهٔ T/B/M.
    """
    from io import BytesIO
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    cols = data.get("cols") or []
    fill = PatternFill("solid", fgColor="2F5597")
    hfont = Font(name="Tahoma", size=10, bold=True, color="FFFFFF")
    body = Font(name="Tahoma", size=10)
    al = Alignment(horizontal="center", vertical="center")

    def fill_sheet(ws, head, srcs, rows):
        """سطر ۱: هدر فارسی — سطر ۲: نام فیلد بانک خام (یا «—» برای محاسبه‌ای)."""
        ws.sheet_view.rightToLeft = True
        for j, h in enumerate(head, 1):
            c = ws.cell(row=1, column=j, value=h)
            c.fill, c.font, c.alignment = fill, hfont, al
        sfill = PatternFill("solid", fgColor="D9E2F3")
        sfont = Font(name="Tahoma", size=8, italic=True, color="1F3864")
        for j, s in enumerate(srcs, 1):
            c = ws.cell(row=2, column=j, value=s)
            c.fill, c.font, c.alignment = sfill, sfont, al
        for i, r in enumerate(rows, 3):
            for j, v in enumerate(r, 1):
                c = ws.cell(row=i, column=j, value=_fmt_compact(v))
                c.font, c.alignment = body, al
        for j in range(1, len(head) + 1):
            ws.column_dimensions[get_column_letter(j)].width = 13
        ws.freeze_panes = "A3"

    # نام فیلد بانک هر ستون — از FIELD_SOURCESِ همان موتور محاسبه
    srcs = [(exp.FIELD_SOURCES.get(c["en"]) or (c["en"], ""))[0] for c in cols]

    # ستون‌های بلااستفادهٔ بانک خام — همهٔ ستون‌های raw_snapshots که ستون جدول
    # ندارند؛ مقدارشان از نمونهٔ خام همان (نماد، ساعت) می‌آید
    used_bank = {"symbol", "fetch_hms"} | {s for s in srcs if s not in ("—", "")}
    unused: list[str] = []
    bank_by_key: dict = {}
    bank_first: dict = {}
    bdate = data.get("date")
    all_rows = list(data.get("frame_rows") or []) + list(data.get("series_rows") or [])
    for sym in sorted({r.get("symbol") for r in all_rows if r.get("symbol")}):
        db = root / "data" / "raw" / f"raw_{sym}.sqlite"
        if not db.exists():
            continue
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        try:
            if not unused:
                bcols = [x[1] for x in con.execute("PRAGMA table_info(raw_snapshots)")]
                unused = [c for c in bcols
                          if c not in used_bank and c not in ("id", "fetch_time")]
            if bdate:
                rs = con.execute("SELECT * FROM raw_snapshots WHERE date_jalali=?",
                                 (bdate,)).fetchall()
            else:
                rs = con.execute(
                    "SELECT * FROM raw_snapshots WHERE date_jalali="
                    "(SELECT MAX(date_jalali) FROM raw_snapshots)").fetchall()
        finally:
            con.close()
        for rr in rs:
            d = dict(rr)
            bank_by_key[(sym, rr["fetch_hms"])] = d
            bank_first.setdefault(sym, d)

    def _extra(r: dict) -> list:
        b = (bank_by_key.get((r.get("symbol"), r.get("fetch_hms")))
             or bank_first.get(r.get("symbol")) or {})
        return [b.get(c) for c in unused]

    head_tail = [c["fa"] for c in cols] + unused
    src_tail = srcs + unused
    wb = Workbook()
    ws1 = wb.active
    ws1.title = "لحظهٔ انتخابی"
    fill_sheet(ws1, ["نماد"] + head_tail, ["symbol"] + src_tail,
               [[r.get("symbol")] + [r.get(c["en"]) for c in cols] + _extra(r)
                for r in data.get("frame_rows") or []])
    if data.get("series_rows"):
        # شیت سری زمانی فقط برای بازپخش — خروجی لایو (بدون سری) یک شیت دارد
        ws2 = wb.create_sheet("سری زمانی تا این لحظه")
        fill_sheet(ws2, ["زمان", "نماد"] + head_tail, ["fetch_hms", "symbol"] + src_tail,
                   [[r.get("fetch_hms"), r.get("symbol")] + [r.get(c["en"]) for c in cols]
                    + _extra(r) for r in data.get("series_rows") or []])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()


class Handler(BaseHTTPRequestHandler):
    root = HERE  # ریشهٔ پروژه — در main از آرگومان ست می‌شود

    # ── پاسخ‌ها ──
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        # اجازهٔ اتصال صفحهٔ file:// به سرور محلی (CORS)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path, _, qs = self.path.partition("?")
        if path in ("/api/data", "/portfoli_data.json"):
            try:
                # طول پنجرهٔ «نمونه‌های اخیر» برای روند — ?w=10..30 (پیش‌فرض ۲۰)
                try:
                    w = int(urllib.parse.parse_qs(qs).get("w", [exp.TREND_WINDOW_DEFAULT])[0])
                except ValueError:
                    w = exp.TREND_WINDOW_DEFAULT
                w = min(max(w, 3), 100)
                payload = exp.build_payload(self.root, trend_window=w)
                payload["live"] = True
                try:
                    save_history(payload, self.root)  # بایگانی محاسبات — خرابی‌اش سرویس را قطع نمی‌کند
                except Exception as he:
                    payload["history_error"] = str(he)
                self._send(200, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            except Exception as e:  # بانک خراب/قفل؟ پاسخ خطا، نه قطع صفحه
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
        elif path == "/api/history":
            self._send(200, json.dumps(history_summary(self.root), ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
        elif path == "/api/replay":
            p = urllib.parse.parse_qs(qs)
            symbol = (p.get("symbol", [""])[0] or "").strip()
            date = _norm_date(p.get("date", [""])[0])
            try:
                n = min(max(int(p.get("n", ["600"])[0]), 10), 3000)
            except ValueError:
                n = 600
            try:
                w = min(max(int(p.get("w", [exp.TREND_WINDOW_DEFAULT])[0]), 3), 100)
            except ValueError:
                w = exp.TREND_WINDOW_DEFAULT
            try:
                out = _replay_frames(self.root, symbol, date, n, w)
                self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            except ValueError as e:  # تاریخ/نماد بی‌داده — پیام فارسی برای صفحه
                self._send(404, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
        elif path == "/api/dates":
            self._send(200, json.dumps({"dates": available_dates(self.root)},
                                       ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")
        elif path in ("/", "/portfoli.html", "/index.html"):
            for f in (HERE / "portfoli.html", self.root / "portfoli.html"):
                if f.exists():
                    self._send(200, f.read_bytes(), "text/html; charset=utf-8")
                    return
            self._send(404, "portfoli.html کنار portfoli_server.py نیست.".encode("utf-8"),
                       "text/plain; charset=utf-8")
        elif path == "/history":  # داشبورد سابقهٔ نمادها
            for f in (HERE / "history.html", self.root / "history.html"):
                if f.exists():
                    self._send(200, f.read_bytes(), "text/html; charset=utf-8")
                    return
            self._send(404, "history.html کنار portfoli_server.py نیست.".encode("utf-8"),
                       "text/plain; charset=utf-8")
        elif path == "/api/hexport":  # گزارش اکسل سابقه — همان ستون‌های جدول history.html
            try:
                p = urllib.parse.parse_qs(qs)
                sym = (p.get("symbol", ["*"])[0] or "*").strip()
                # http.server خط درخواست را latin-1 می‌خواند — اگر مرورگر/ابزار
                # بایت‌های خام UTF-8 فرستاده باشد همین‌جا باز می‌شود
                try:
                    sym = sym.encode("latin-1").decode("utf-8")
                except (UnicodeDecodeError, UnicodeEncodeError):
                    pass
                xls = _history_export_xlsx(self.root, sym)
                if sym == "*":
                    fname = "سابقهٔ همهٔ نمادها.xlsx"
                else:
                    fname = f"سابقهٔ {sym}.xlsx"
                self.send_response(200)
                self.send_header("Content-Type",
                                 "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Length", str(len(xls)))
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename=\"history_export.xlsx\"; "
                    f"filename*=UTF-8''{urllib.parse.quote(fname)}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(xls)
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
        elif path == "/api/hdata":  # دادهٔ داشبورد سابقه — از بانک خام history.sqlite
            try:
                import history_dashboard
                p = urllib.parse.parse_qs(qs)
                syms = [s.strip() for s in p.get("symbols", [""])[0].split(",") if s.strip()]
                out = history_dashboard.build_history_data(self.root, syms or None)
                self._send(200, json.dumps(out, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
        elif path.endswith(".json"):  # فایل‌های replay/دادهٔ کنار پروژه
            for f in (HERE / path.lstrip("/"), self.root / path.lstrip("/")):
                if f.exists() and f.is_file():
                    self._send(200, f.read_bytes(), "application/json; charset=utf-8")
                    return
            self._send(404, b"json not found", "text/plain; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self) -> None:
        path, _, _ = self.path.partition("?")
        if path == "/api/export":
            try:
                n = int(self.headers.get("Content-Length") or 0)
                if n <= 0 or n > 30_000_000:
                    raise ValueError("حجم درخواست خروجی نامعتبر است")
                data = json.loads(self.rfile.read(n).decode("utf-8"))
                xls = _replay_export_xlsx(data, self.root)
                fname = f"portfoli_replay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Length", str(len(xls)))
                self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(xls)
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
        elif path == "/api/hcollect":  # اجرای history_collector + بایگانی سابقه در portfoli_history
            try:
                import subprocess
                days = 30  # حداقل ۳۰ روز دیفالت — تا ۹۰ روز قابل بایگانی
                n = int(self.headers.get("Content-Length") or 0)
                if n:
                    body = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
                    days = min(max(int(body.get("days", 30)), 30), 90)
                script = self.root / "history_collector.py"
                if not script.exists():
                    script = HERE / "history_collector.py"
                # ۱) سابقهٔ خام از TSETMC (بانک انباشته است — اجرای دوباره بدون تکرار)
                proc = subprocess.run(
                    [sys.executable, str(script), "--days", "400"],
                    capture_output=True, text=True, timeout=600, cwd=str(self.root))
                log = (proc.stdout or "").strip().splitlines()[-10:]
                # ۲) بایگانی محاسبه‌ها تا N روز گذشته در portfoli_history.sqlite
                import history_dashboard
                bf = history_dashboard.backfill_portfoli_history(self.root, days)
                self._send(200, json.dumps({
                    "ok": proc.returncode == 0 and bf.get("ok"),
                    "log": log,
                    "backfilled": bf.get("added"),
                    "updated": bf.get("updated"),
                    "archive_days": bf.get("days"),
                    "last_dates": bf.get("last_dates"),
                }, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
            except subprocess.TimeoutExpired:
                self._send(504, json.dumps({"error": "جمع‌آوری بیش از ۱۰ دقیقه طول کشید"},
                                           ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
            except Exception as e:
                self._send(500, json.dumps({"error": str(e)}, ensure_ascii=False).encode("utf-8"),
                           "application/json; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_OPTIONS(self) -> None:  # preflight — اگر مرورگر بخواهد
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args) -> None:  # بی‌صدا — فقط خطاها در main چاپ می‌شوند
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="سرور لایو داشبورد portfoli")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--root", default=None,
                    help="ریشهٔ پروژهٔ TSE_Screener (پیش‌فرض: پوشهٔ همین اسکریپت)")
    ap.add_argument("--no-browser", action="store_true", help="باز کردن خودکار مرورگر انجام نشود")
    args = ap.parse_args()

    Handler.root = Path(args.root) if args.root else HERE
    url = f"http://localhost:{args.port}/"
    print(f"✓ داشبورد لایو portfoli → {url}")
    print("  دادهٔ لایو از بانک‌های خام؛ تازه‌سازی خودکار هر ۳۰ ثانیه. توقف: Ctrl+C")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n✓ سرور متوقف شد")


if __name__ == "__main__":
    main()
