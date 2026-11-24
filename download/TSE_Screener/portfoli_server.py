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
        elif path in ("/", "/portfoli.html", "/index.html"):
            for f in (HERE / "portfoli.html", self.root / "portfoli.html"):
                if f.exists():
                    self._send(200, f.read_bytes(), "text/html; charset=utf-8")
                    return
            self._send(404, "portfoli.html کنار portfoli_server.py نیست.".encode("utf-8"),
                       "text/plain; charset=utf-8")
        elif path.endswith(".json"):  # فایل‌های replay/دادهٔ کنار پروژه
            for f in (HERE / path.lstrip("/"), self.root / path.lstrip("/")):
                if f.exists() and f.is_file():
                    self._send(200, f.read_bytes(), "application/json; charset=utf-8")
                    return
            self._send(404, b"json not found", "text/plain; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain; charset=utf-8")

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
