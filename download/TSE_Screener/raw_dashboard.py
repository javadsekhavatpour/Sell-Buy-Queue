#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
raw_dashboard.py — داشبورد تائید بصری دادهٔ خام

فقط همان داده‌ای که raw_collector.py از لایو دریافت و در بانک نوشته را نشان
می‌دهد — بدون هیچ محاسبه‌ای روی مقادیر. برای هر عدد، کنارش «ساعت آخرین معاملهٔ
لایو طبق TSETMC» و «زمان دریافت» نمایش داده می‌شود تا بتوانید چشمی تأیید کنید
که دادهٔ ذخیره‌شده همان لایو بازار است.

- هر مقدار صفر یا NULL در فیلدهای قیمتی با قرمز هایلایت می‌شود (نشانهٔ مشکل).
- فقط خواندن از بانک (mode=ro) — بانک را تغییر نمی‌دهد.

اجرا:
  python raw_dashboard.py --db data/raw/raw_سرود.sqlite --port 8060
سپس در مرورگر: http://localhost:8060
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent

# فیلدهای قیمتی — صفر/NULL در آن‌ها هنگام نمایش قرمز می‌شود
PRICE_FIELDS = {
    "last_price", "close_price", "open_price", "yesterday_price",
    "daily_high", "daily_low",
    "buy_price_1", "buy_price_2", "buy_price_3", "buy_price_4", "buy_price_5",
    "sell_price_1", "sell_price_2", "sell_price_3", "sell_price_4", "sell_price_5",
}

LABELS = {
    "fetch_hms": "زمان دریافت",
    "api_last_trade_time": "آخرین معاملهٔ لایو (TSETMC)",
    "api_symbol_status": "وضعیت نماد",
    "api_date": "تاریخ API",
    "last_price": "آخرین قیمت",
    "close_price": "قیمت پایانی",
    "open_price": "اولین قیمت",
    "yesterday_price": "قیمت دیروز",
    "daily_high": "بیشترین امروز",
    "daily_low": "کمترین امروز",
    "trade_volume": "حجم کل",
    "trade_value": "ارزش کل (ریال)",
    "trade_count": "تعداد معاملات",
}

CT_FIELDS = [
    ("ct_real_buy_volume", "حجم خرید حقیقی"),
    ("ct_real_sell_volume", "حجم فروش حقیقی"),
    ("ct_legal_buy_volume", "حجم خرید حقوقی"),
    ("ct_legal_sell_volume", "حجم فروش حقوقی"),
    ("ct_real_buy_count", "تعداد خریداران حقیقی"),
    ("ct_real_sell_count", "تعداد فروشندگان حقیقی"),
    ("ct_legal_buy_count", "تعداد خریداران حقوقی"),
    ("ct_legal_sell_count", "تعداد فروشندگان حقوقی"),
]

PAGE = r"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>داشبورد دادهٔ خام — تائید بصری</title>
<style>
  :root { --bg:#0d1117; --card:#161b22; --line:#30363d; --tx:#e6edf3; --dim:#8b949e;
          --ok:#3fb950; --bad:#f85149; --accent:#58a6ff; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--tx);
         font-family:Vazirmatn,Tahoma,'Segoe UI',sans-serif;
         font-size:clamp(13px,2.6vw,15px); }
  .wrap { max-width:1200px; margin:0 auto; padding:clamp(10px,3vw,24px); }
  h1 { font-size:clamp(17px,4.5vw,24px); margin:0 0 4px; }
  .sub { color:var(--dim); font-size:clamp(11px,2.6vw,13px); margin-bottom:14px;
         word-break:break-all; }
  .bar { display:flex; flex-wrap:wrap; gap:8px; align-items:center;
         background:var(--card); border:1px solid var(--line); border-radius:10px;
         padding:10px 14px; margin-bottom:14px; }
  .badge { border-radius:20px; padding:3px 12px; font-size:clamp(11px,2.6vw,13px);
           border:1px solid var(--line); }
  .ok  { color:var(--ok); border-color:var(--ok); }
  .bad { color:var(--bad); border-color:var(--bad); }
  .grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr));
          gap:10px; margin-bottom:14px; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:10px 12px; }
  .card .t { color:var(--dim); font-size:clamp(10px,2.4vw,12px); margin-bottom:4px; }
  .card .v { font-size:clamp(15px,3.8vw,22px); font-weight:700;
             font-variant-numeric:tabular-nums; }
  .card .v.bad { color:var(--bad); }
  h2 { font-size:clamp(14px,3.6vw,17px); margin:18px 0 8px; color:var(--accent); }
  .scroll { overflow-x:auto; border:1px solid var(--line); border-radius:10px;
            background:var(--card); max-width:100%; }
  .two > div { min-width:0; }  /* جلوگیری از انبساط grid توسط جدول پهن */
  table { border-collapse:collapse; width:100%; min-width:640px;
          font-variant-numeric:tabular-nums; }
  th,td { padding:7px 10px; border-bottom:1px solid var(--line); text-align:center;
          white-space:nowrap; font-size:clamp(11px,2.6vw,13px); }
  th { color:var(--dim); position:sticky; top:0; background:var(--card); }
  td.buy { color:#7ee787; } td.sell { color:#ffa657; }
  .zero { color:var(--bad); font-weight:700; }
  .na   { color:var(--dim); }
  .two  { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  @media (max-width:640px){ .two { grid-template-columns:1fr; } }
  .foot { color:var(--dim); font-size:clamp(10px,2.4vw,12px); margin-top:16px;
          line-height:1.8; }
  .refresh { margin-inline-start:auto; color:var(--dim); font-size:12px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>داشبورد دادهٔ خام <span id="sym"></span></h1>
  <div class="sub" id="dbpath"></div>

  <div class="bar">
    <span class="badge" id="rows"></span>
    <span class="badge" id="fresh"></span>
    <span class="badge" id="status"></span>
    <span class="refresh">رفرش خودکار هر ۱۰ ثانیه</span>
  </div>

  <h2>آخرین ردیف — دقیقاً همان چیزی که از لایو دریافت شده</h2>
  <div class="grid" id="cards"></div>

  <div class="two">
    <div>
      <h2>سفارش‌های خرید (bid) — خام</h2>
      <div class="scroll"><table id="buys"></table></div>
    </div>
    <div>
      <h2>سفارش‌های فروش (ask) — خام</h2>
      <div class="scroll"><table id="sells"></table></div>
    </div>
  </div>

  <h2>حقیقی / حقوقی — خام</h2>
  <div class="scroll"><table id="ct"></table></div>

  <h2>تاریخچه (۶۰ ردیف آخر)</h2>
  <div class="scroll"><table id="hist"></table></div>

  <div class="foot">
    هر عدد در این صفحه بدون هیچ محاسبه‌ای مستقیماً از جدول raw_snapshots خوانده شده.
    «آخرین معاملهٔ لایو» همان hEven پاسخ TSETMC است؛ اگر بین دو ردیف پشت‌سرهم تغییر
    نکرده باشد یعنی TSETMC دادهٔ جدیدی نداشته (کش/بدون معاملهٔ جدید). مقادیر قرمز =
    صفر یا NULL در فیلد قیمتی — باید بررسی شود.
  </div>
</div>

<script>
const PRICE = new Set(%PRICE_FIELDS%);
const LBL = %LABELS%;
const isNumStr = s => /^-?\d+(\.\d+)?$/.test(String(s).trim());
const fa = n => (n===null||n===undefined||n==='') ? '—'
  : (typeof n==='string' && !isNumStr(n)) ? n   // رشتهٔ خام (ساعت/وضعیت) بدون تغییر
  : Number(n).toLocaleString('fa-IR');
const cell = (k,v) => {
  if (v===null||v===undefined||v==='') return `<td class="na">—</td>`;
  const bad = PRICE.has(k) && Number(v)===0;
  return `<td class="${bad?'zero':''}">${fa(v)}</td>`;
};
async function load(){
  try {
    const d = await (await fetch('/api/data')).json();
    document.getElementById('sym').textContent = d.symbol || '';
    document.getElementById('dbpath').textContent = 'بانک: ' + d.db;
    document.getElementById('rows').textContent = 'ردیف‌ها: ' + fa(d.total);
    const L = d.latest || {};
    document.getElementById('status').textContent = 'وضعیت نماد: ' + (L.api_symbol_status || '—');
    // تازگی: دو مقدار خام کنار هم — مقایسه با چشم
    document.getElementById('fresh').textContent =
      `دریافت: ${L.fetch_hms||'—'}  |  آخرین معاملهٔ لایو: ${L.api_last_trade_time||'—'}`;
    const cards = Object.entries(LBL).map(([k,t]) => {
      const raw = (k==='api_date') ? (L[k]||'—') : fa(L[k]); // تاریخ API هم رشتهٔ خام
      const bad = PRICE.has(k) && Number(L[k])===0;
      return `<div class="card"><div class="t">${t}</div><div class="v ${bad?'bad':''}">${raw}</div></div>`;
    }).join('');
    document.getElementById('cards').innerHTML = cards;
    // سفارش‌ها
    const ob = (side) => [1,2,3,4,5].map(i =>
      `<tr><td>${fa(i)}</td>${cell(side+'_price_'+i, L[side+'_price_'+i])}${cell(side+'_volume_'+i, L[side+'_volume_'+i])}${cell(side+'_orders_'+i, L[side+'_orders_'+i])}</tr>`).join('');
    document.getElementById('buys').innerHTML =
      '<tr><th>ردیف</th><th>قیمت</th><th>حجم</th><th>تعداد سفارش</th></tr>' + ob('buy');
    document.getElementById('sells').innerHTML =
      '<tr><th>ردیف</th><th>قیمت</th><th>حجم</th><th>تعداد سفارش</th></tr>' + ob('sell');
    document.getElementById('ct').innerHTML =
      '<tr><th>شرح</th><th>مقدار (خام)</th></tr>' +
      %CT_FIELDS%.map(([k,t]) => `<tr><td style="text-align:right">${t}</td>${cell(k,L[k])}</tr>`).join('');
    // تاریخچه
    const H = ['fetch_hms','api_last_trade_time','last_price','close_price','open_price',
               'yesterday_price','trade_volume','buy_price_1','sell_price_1'];
    document.getElementById('hist').innerHTML =
      '<tr><th>دریافت</th><th>معاملهٔ لایو</th><th>آخرین</th><th>پایانی</th><th>اولین</th><th>دیروز</th><th>حجم</th><th>bid1</th><th>ask1</th></tr>' +
      (d.rows||[]).map(r => `<tr><td>${r.fetch_hms||'—'}</td><td>${r.api_last_trade_time||'—'}</td>` +
        ['last_price','close_price','open_price','yesterday_price','trade_volume','buy_price_1','sell_price_1']
        .map(k => cell(k,r[k])).join('') + '</tr>').join('');
  } catch(e) {
    document.getElementById('fresh').textContent = 'خطای خواندن بانک: ' + e.message;
  }
}
load(); setInterval(load, 10000);
</script>
</body>
</html>
"""


def read_bank(db_path: Path, limit: int = 60) -> dict:
    """فقط خواندن (ro). بدون هیچ محاسبه — ردیف خام به JSON."""
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(raw_snapshots)")]
        if not cols:
            return {"error": "جدول raw_snapshots هنوز ساخته نشده"}
        total = conn.execute("SELECT COUNT(*) FROM raw_snapshots").fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM raw_snapshots ORDER BY id DESC LIMIT {int(limit)}"
        ).fetchall()
        latest = dict(rows[0]) if rows else None
        return {
            "db": str(db_path),
            "symbol": latest.get("symbol") if latest else "",
            "total": total,
            "latest": latest,
            "rows": [dict(r) for r in rows],
        }
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    db_path: Path = None

    def log_message(self, *a):  # بی‌سروصدا
        pass

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urlparse(self.path)
        if p.path == "/api/data":
            q = parse_qs(p.query)
            limit = int(q.get("limit", ["60"])[0])
            try:
                data = read_bank(self.db_path, limit)
                body = json.dumps(data, ensure_ascii=False, default=str).encode()
                self._send(200, body, "application/json; charset=utf-8")
            except Exception as e:
                body = json.dumps({"error": str(e)}, ensure_ascii=False).encode()
                self._send(500, body, "application/json; charset=utf-8")
        elif p.path in ("/", "/index.html"):
            html = (PAGE
                    .replace("%PRICE_FIELDS%", json.dumps(sorted(PRICE_FIELDS)))
                    .replace("%LABELS%", json.dumps(LABELS, ensure_ascii=False))
                    .replace("%CT_FIELDS%", json.dumps(CT_FIELDS, ensure_ascii=False)))
            self._send(200, html.encode(), "text/html; charset=utf-8")
        else:
            self._send(404, b"not found", "text/plain")


def main():
    ap = argparse.ArgumentParser(description="داشبورد تائید بصری دادهٔ خام")
    ap.add_argument("--db", default="data/raw/raw_سرود.sqlite")
    ap.add_argument("--port", type=int, default=8060)
    args = ap.parse_args()

    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    Handler.db_path = db_path

    print("=" * 70)
    print("  داشبورد دادهٔ خام — فقط نمایش، بدون محاسبه")
    print("=" * 70)
    print(f"  بانک : {db_path}")
    print(f"  آدرس : http://localhost:{args.port}   (توقف: Ctrl+C)")
    try:
        HTTPServer(("", args.port), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n  توقف")


if __name__ == "__main__":
    main()
