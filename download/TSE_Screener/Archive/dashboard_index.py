"""
dashboard_index.py — صفحه‌ی نمایه‌ی چندنمادی.

یک سرور Flask سبک روی پورت ۸۰۵۱ که:
  - /            → صفحه‌ی HTML با ۴ کارت نماد (سرود، دابور، اهرم، ریتون)
  - /api/status  → JSON وضعیت زنده هر نماد (داده از بانک + آنلاین/آفلاین داشبورد)

هر کارت با کلیک، داشبورد آن نماد را در تب جدید باز می‌کند
(http://127.0.0.1:805X که توسط run_dashboards.py راه‌اندازی شده).

استفاده:
  python dashboard_index.py --port 8051
  (یا به‌صورت خودکار توسط run_dashboards.py)
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sqlite3
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, send_file

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning.market_detector import tehran_now, in_trading_window, MARKET_HOURS

app = Flask(__name__)

SYMBOLS_PATH = ROOT / "config" / "symbols.json"
BASE_PORT = 8052  # نماد ۰ → 8052، نماد ۱ → 8053، ...

INDEX_HTML = ROOT / "dashboard_index.html"


def load_symbols() -> list[dict]:
    if not SYMBOLS_PATH.exists():
        return []
    data = json.loads(SYMBOLS_PATH.read_text(encoding="utf-8"))
    return data.get("symbols", [])


def _port_check(host: str, port: int, timeout: float = 0.4) -> bool:
    """آیا داشبورد روی این پورت در حال اجراست؟"""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _fetch_live(host: str, port: int, timeout: float = 1.0) -> dict | None:
    """دریافت /api/live از داشبورد یک پورت.

    برمی‌گرداند: {served_symbol, sell_score, sell_tier, buy_score, buy_tier,
                  classification, ok} یا None اگر در دسترس نباشد.
    این تابع هم برای راستی‌آزمایی نماد (آیا پورت واقعاً همان نماد را سرو می‌کند؟)
    و هم برای نمایش امتیاز موتورهای تحلیلی استفاده می‌شود.
    """
    url = f"http://{host}:{port}/api/live"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError, TimeoutError):
        return None
    if not data.get("ok"):
        return {"ok": False, "served_symbol": None}
    snap = data.get("snapshot", {}) or {}
    eng = data.get("engines", {}) or {}
    sell = eng.get("sell") or {}
    buy = eng.get("buy") or {}
    return {
        "ok": True,
        "served_symbol": snap.get("symbol"),
        "sell_score": sell.get("total_score"),
        "sell_tier": eng.get("sell_tier"),
        "buy_score": buy.get("total_score"),
        "buy_tier": eng.get("buy_tier"),
        "classification": eng.get("classification"),
        "cumulative_sell_score": eng.get("cumulative_sell_score"),
        "cumulative_buy_score": eng.get("cumulative_buy_score"),
        "cumulative_samples": eng.get("cumulative_samples"),
    }


def _db_status(db_path: Path) -> dict:
    """خواندن آخرین snapshot و تعداد از بانک نماد."""
    st = {"db_exists": db_path.exists(), "snapshot_count": 0,
          "last_price": None, "last_tehran_time": None, "market_phase": None}
    if not db_path.exists():
        return st
    try:
        c = sqlite3.connect(str(db_path))
        cur = c.cursor()
        cur.execute("SELECT COUNT(*) FROM snapshots")
        st["snapshot_count"] = cur.fetchone()[0]
        cur.execute(
            "SELECT tehran_time, market_phase, last_price "
            "FROM snapshots ORDER BY snapshot_id DESC LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            st["last_tehran_time"] = row[0]
            st["market_phase"] = row[1]
            st["last_price"] = row[2]
        c.close()
    except sqlite3.Error:
        pass
    return st


def build_status(symbols: list[dict], host: str) -> list[dict]:
    """ساخت وضعیت زنده همه نمادها."""
    now = tehran_now()
    now_hhmm = now.strftime("%H:%M")
    out = []
    for i, s in enumerate(symbols):
        port = BASE_PORT + i
        db_path = ROOT / "data" / "multi" / f"{s['name']}.sqlite"
        th = s["trading_hours"]
        in_sess, status_msg = in_trading_window(th, now_hhmm)
        dbs = _db_status(db_path)
        online = _port_check(host, port)
        live = _fetch_live(host, port) if online else None
        # راستی‌آزمایی: آیا پورت واقعاً همین نماد را سرو می‌کند؟
        # (جلوگیری از باگ سرود→ریتون وقتی پروسه‌ی stale روی پورت مانده)
        served = live.get("served_symbol") if live else None
        symbol_match = bool(served) and served == s["name"]
        out.append({
            "name": s["name"],
            "full_name": s.get("full_name", ""),
            "market_type": s["market_type"],
            "market_label": s["market_label"],
            "instrument_type": s["instrument_type"],
            "trading_hours": f"{th['continuous'][0]}-{th['continuous'][1]}",
            "pre_open": f"{th['pre_open'][0]}-{th['pre_open'][1]}",
            "in_session": in_sess,
            "session_status": status_msg,
            "dashboard_port": port,
            "dashboard_url": f"http://{host}:{port}",
            "dashboard_online": online,
            "served_symbol": served,
            "symbol_match": symbol_match,
            # موتورهای تحلیلی (فقط وقتی داشبورد آنلاین است)
            "sell_score": live.get("sell_score") if live else None,
            "sell_tier": live.get("sell_tier") if live else None,
            "buy_score": live.get("buy_score") if live else None,
            "buy_tier": live.get("buy_tier") if live else None,
            "classification": live.get("classification") if live else None,
            # امتیاز تجمعی (مجموع از ابتدا تا الان)
            "cumulative_sell_score": live.get("cumulative_sell_score") if live else None,
            "cumulative_buy_score": live.get("cumulative_buy_score") if live else None,
            "cumulative_samples": live.get("cumulative_samples") if live else None,
            "now_tehran": now_hhmm,
            **dbs,
        })
    return out


@app.route("/")
def index():
    if INDEX_HTML.exists():
        return send_file(str(INDEX_HTML))
    return "<h1>dashboard_index.html پیدا نشد</h1>", 404


@app.route("/api/status")
def api_status():
    host = request_host()
    symbols = load_symbols()
    return jsonify({"symbols": build_status(symbols, host), "now": tehran_now().strftime("%H:%M:%S")})


def request_host() -> str:
    """host از query string یا پیش‌فرض 127.0.0.1."""
    from flask import request
    return request.args.get("host", "127.0.0.1")


@app.route("/open/<name>")
def open_symbol(name):
    """ری‌دایرکت به داشبورد نماد (برای لینک مستقیم)."""
    symbols = load_symbols()
    host = request_host()
    for i, s in enumerate(symbols):
        if s["name"] == name:
            port = BASE_PORT + i
            return f'<meta http-equiv="refresh" content="0;url=http://{host}:{port}">'
    return "نماد پیدا نشد", 404


def main():
    ap = argparse.ArgumentParser(description="صفحه‌ی نمایه‌ی چندنمادی")
    ap.add_argument("--port", type=int, default=8051)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    # اطمینان از وجود HTML
    if not INDEX_HTML.exists():
        generate_index_html()

    symbols = load_symbols()
    print("=" * 60)
    print("  صفحه‌ی نمایه‌ی چندنمادی — TSE Early Warning")
    print(f"  آدرس: http://{args.host}:{args.port}")
    print(f"  نمادها: {len(symbols)}")
    for i, s in enumerate(symbols):
        print(f"    {s['name']:<6} → http://{args.host}:{BASE_PORT + i}")
    print("=" * 60)
    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)


def generate_index_html():
    """تولید dashboard_index.html اگر موجود نبود (به‌عنوان fallback)."""
    INDEX_HTML.write_text(_INDEX_FALLBACK, encoding="utf-8")


_INDEX_FALLBACK = """<!DOCTYPE html>
<html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>داشبورد چندنمادی</title></head>
<body><p>داشبورد آنلاین را از <code>/api/status</code> ببینید.</p></body></html>"""


if __name__ == "__main__":
    main()
