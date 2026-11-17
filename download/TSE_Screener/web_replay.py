"""
web_replay.py — ابزار بازپخش روزانه (Daily Replay)
بازپخش آفلاین snapshot‌های ذخیره‌شده یک نماد در یک روز، از طریق موتورهای
تحلیلی، و نمایش نتیجه روی نمودار قیمت-زمان با نشانگرهای هشدار.

جریان:
  snapshots table (SQLite)  →  بازسازی MarketSnapshot  →  بازپخش موتورها
       →  امتیاز/هشدار در هر لحظه  →  نمودار Plotly (قیمت + نشانگرها)

استفاده:
  python web_replay.py --db Archive/data/early_warning.sqlite --port 8060
  سپس: http://localhost:8060/replay

مسیرها:
  /                 → صفحه انتخاب نماد + تاریخ
  /replay           → نمودار (query: ?symbol=...&date=...)
  /api/replay       → JSON امتیاز+هشدار در هر لحظه
  /api/symbols      → لیست نمادها و تاریخ‌های موجود در DB
"""

from __future__ import annotations

import argparse
import json
from dataclasses import fields as dataclass_fields
from pathlib import Path
from typing import Dict, List, Optional

from flask import Flask, jsonify, request

from early_warning import (
    MarketDataStorage,
    SellPressureDetector,
    BuyPressureDetector,
    AlertEngine,
    AdaptiveNormalizer,
)
from early_warning.data_collector import MarketSnapshot, BestLimitRow
from early_warning.alert_engine import tier, classify

ROOT = Path(__file__).resolve().parent
app = Flask(__name__)

# ---------------------------------------------------------------------------
# بازسازی MarketSnapshot از ردیف DB
# ---------------------------------------------------------------------------

# فیلدهای مستقیم dataclass (نه buy_rows/sell_rows/missing_fields)
_SNAP_DIRECT_FIELDS = {
    f.name for f in dataclass_fields(MarketSnapshot)
    if f.name not in ("buy_rows", "sell_rows", "missing_fields")
}


def snapshot_from_db_row(row: Dict) -> MarketSnapshot:
    """
    بازسازی MarketSnapshot از یک ردیف جدول snapshots.

    برعکس to_flat_dict: فیلدهای مستقیم از row، و buy_rows/sell_rows
    از ستون‌های bid_*/ask_* بازسازی می‌شوند.
    """
    snap = MarketSnapshot()
    # فیلدهای مستقیم
    for fname in _SNAP_DIRECT_FIELDS:
        if fname in row:
            val = row[fname]
            ftype = type(getattr(snap, fname))
            # تبدیل نوع برای فیلدهای عددی (SQLite ممکن است int/float/None برگرداند)
            if ftype is bool:
                val = bool(val) if val is not None else False
            elif ftype is float and val is not None:
                try:
                    val = float(val)
                except (TypeError, ValueError):
                    val = 0.0
            elif ftype is int and val is not None:
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    val = 0
            setattr(snap, fname, val)

    # بازسازی buy_rows از bid_price/volume/count 1..5
    buy_rows = []
    for i in range(1, 6):
        price = row.get(f"bid_price_{i}")
        vol = row.get(f"bid_volume_{i}")
        cnt = row.get(f"bid_count_{i}")
        if price is not None or vol is not None:
            buy_rows.append(BestLimitRow(
                price=float(price or 0),
                volume=int(vol or 0),
                order_count=int(cnt or 0),
            ))
    snap.buy_rows = buy_rows

    # بازسازی sell_rows از ask_price/volume/count 1..5
    sell_rows = []
    for i in range(1, 6):
        price = row.get(f"ask_price_{i}")
        vol = row.get(f"ask_volume_{i}")
        cnt = row.get(f"ask_count_{i}")
        if price is not None or vol is not None:
            sell_rows.append(BestLimitRow(
                price=float(price or 0),
                volume=int(vol or 0),
                order_count=int(cnt or 0),
            ))
    snap.sell_rows = sell_rows

    # missing_fields از رشته
    mf = row.get("missing_fields", "")
    snap.missing_fields = [x for x in str(mf).split(",") if x] if mf else []

    return snap


# ---------------------------------------------------------------------------
# بازپخش موتورها روی snapshot‌های یک روز
# ---------------------------------------------------------------------------

def replay_day(storage: MarketDataStorage, cfg: Dict, symbol: str,
               date_jalali: str) -> Dict:
    """
    بازپخش کامل یک نماد در یک روز: خواندن snapshot‌ها، عبور از موتورها،
    و بازگشت سری زمانی امتیاز/هشدار.

    خروجی:
      {
        "symbol", "date", "count",
        "timeline": [
          {"time", "price", "close_price", "market_phase",
           "sell_score", "buy_score", "sell_tier", "buy_tier",
           "classification", "is_critical",
           "sell_factors": [...], "buy_factors": [...], "alert": {...}|null},
          ...
        ],
        "alerts": [ {time, type, sell_score, buy_score, ...}, ... ]  # فقط لحظات هشدار
      }
    """
    # خواندن همه snapshot‌های این نماد در این روز
    all_rows = storage.get_snapshots_for_symbol(symbol)
    rows = [r for r in all_rows if r.get("date_jalali") == date_jalali]
    if not rows:
        return {"ok": False, "message": f"داده‌ای برای {symbol} در {date_jalali} نیست"}

    # بازسازی snapshot‌ها به ترتیب زمانی
    snaps = [snapshot_from_db_row(r) for r in rows]

    # موتورها (بدون normalizer — بازپخش از داده موجود، آستانه ثابت Phase 1)
    sp_det = SellPressureDetector(cfg)
    buy_det = BuyPressureDetector(cfg)
    alert_eng = AlertEngine(cfg)

    timeline = []
    alerts = []
    history = []  # برای buy_support (۳۶ نمونه)

    for i, snap in enumerate(snaps):
        prev = snaps[i - 1] if i > 0 else None
        entry = {
            "time": snap.tehran_time,
            "timestamp": snap.timestamp,
            "price": snap.last_price,
            "close_price": snap.close_price,
            "daily_high": snap.daily_high,
            "daily_low": snap.daily_low,
            "market_phase": snap.market_phase,
            "total_volume": snap.total_volume,
            "interval_volume": snap.interval_volume,
        }

        # فقط در فاز continuous موتورها اجرا می‌شوند (مثل run_live)
        if snap.market_phase != "continuous":
            entry.update({
                "sell_score": None, "buy_score": None,
                "sell_tier": "—", "buy_tier": "—",
                "classification": "غیرمعاملاتی",
                "is_critical": False,
                "sell_factors": [], "buy_factors": [],
                "alert": None,
            })
            timeline.append(entry)
            history.append(snap)
            continue

        try:
            sp = sp_det.evaluate(snap, prev)
            buy = buy_det.evaluate(snap, prev, history)
            combined = alert_eng.evaluate(sp, buy)
        except Exception as e:
            entry.update({
                "sell_score": None, "buy_score": None,
                "sell_tier": "—", "buy_tier": "—",
                "classification": f"خطا: {e}",
                "is_critical": False,
                "sell_factors": [], "buy_factors": [],
                "alert": None,
            })
            timeline.append(entry)
            history.append(snap)
            continue

        s_score = round(sp.total_score, 1)
        b_score = round(buy.total_score, 1)
        cls = classify(s_score, b_score) if combined else "—"
        is_crit = bool(getattr(combined, "is_critical", False))

        entry.update({
            "sell_score": s_score,
            "buy_score": b_score,
            "sell_tier": tier(s_score) if s_score is not None else "—",
            "buy_tier": tier(b_score) if b_score is not None else "—",
            "classification": cls,
            "is_critical": is_crit,
            "sell_factors": [f.to_dict() for f in sp.factors],
            "buy_factors": [f.to_dict() for f in buy.factors],
            "alert": combined.to_dict() if combined else None,
        })
        timeline.append(entry)

        # ثبت لحظات هشدار: critical همیشه، و sell/buy ≥ ۵۰ (فشار قوی)
        # ۳۵ (هشدار اولیه) برای نمودار شلوغ است — فقط لحظات مهم نشانگر می‌شوند
        ALERT_THRESHOLD = 50
        s_alert = s_score is not None and s_score >= ALERT_THRESHOLD
        b_alert = b_score is not None and b_score >= ALERT_THRESHOLD
        if s_alert or b_alert or is_crit:
            alert_type = []
            if is_crit:
                alert_type.append("critical")
            if s_alert:
                alert_type.append("sell")
            if b_alert:
                alert_type.append("buy")
            alerts.append({
                "time": snap.tehran_time,
                "type": "+".join(alert_type),
                "sell_score": s_score,
                "buy_score": b_score,
                "classification": cls,
                "price": snap.last_price,
            })

        history.append(snap)

    return {
        "ok": True,
        "symbol": symbol,
        "date": date_jalali,
        "count": len(snaps),
        "continuous_count": sum(1 for s in snaps if s.market_phase == "continuous"),
        "timeline": timeline,
        "alerts": alerts,
    }


# ---------------------------------------------------------------------------
# مسیرهای API
# ---------------------------------------------------------------------------

@app.route("/api/symbols")
def api_symbols():
    """لیست نمادها و تاریخ‌های موجود در DB."""
    db_path = app.config.get("DB_PATH")
    if not db_path or not Path(db_path).exists():
        return jsonify({"ok": False, "message": "فایل DB پیدا نشد"})
    storage = MarketDataStorage(Path(db_path))
    try:
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT symbol, date_jalali FROM snapshots "
            "ORDER BY symbol, date_jalali"
        )
        data = {}
        for sym, dt in cur.fetchall():
            data.setdefault(sym, []).append(dt)
        conn.close()
        return jsonify({"ok": True, "symbols": data})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)})


@app.route("/api/replay")
def api_replay():
    """بازپخش کامل: ?symbol=...&date=..."""
    symbol = request.args.get("symbol", "")
    date = request.args.get("date", "")
    if not symbol or not date:
        return jsonify({"ok": False, "message": "symbol و date لازم است"}), 400

    db_path = app.config.get("DB_PATH")
    cfg = app.config.get("CFG")
    if not db_path or not Path(db_path).exists():
        return jsonify({"ok": False, "message": "فایل DB پیدا نشد"}), 500

    storage = MarketDataStorage(Path(db_path))
    try:
        result = replay_day(storage, cfg, symbol, date)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


# ---------------------------------------------------------------------------
# صفحات HTML
# ---------------------------------------------------------------------------

INDEX_PAGE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>بازپخش روزانه — تحلیل سیگنال‌ها</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<style>
  body { font-family: Tahoma, sans-serif; margin: 0; background:#f5f6f8; color:#333; }
  .bar { background:#1a237e; color:#fff; padding:10px 16px; font-size:15px; }
  .wrap { max-width:1200px; margin:0 auto; padding:16px; }
  select, button, input { padding:8px 12px; font-size:14px; border:1px solid #ccc;
    border-radius:6px; background:#fff; }
  button { background:#1a237e; color:#fff; border:none; cursor:pointer; }
  button:hover { background:#283593; }
  .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:12px; }
  .card { background:#fff; border:1px solid #e0e0e0; border-radius:8px; padding:12px; margin-bottom:12px; }
  #chart { width:100%; height:520px; }
  #alertList { font-size:13px; max-height:200px; overflow:auto; }
  #alertList table { width:100%; border-collapse:collapse; }
  #alertList th, #alertList td { padding:4px 8px; border-bottom:1px solid #eee; text-align:center; }
  #alertList th { background:#f0f0f0; }
  .stat { display:inline-block; padding:4px 12px; background:#e8eaf6; border-radius:6px; margin:2px; font-size:13px; }
  .hint { color:#888; font-size:12px; }
</style>
</head>
<body>
<div class="bar">📊 بازپخش روزانه — بررسی سیگنال‌های موتور روی نمودار قیمت-زمان</div>
<div class="wrap">
  <div class="card">
    <div class="row">
      <label>نماد:</label>
      <select id="sym"></select>
      <label>تاریخ:</label>
      <select id="date"></select>
      <button onclick="load()">▶ بازپخش</button>
    </div>
    <div id="stats" class="row"></div>
  </div>
  <div class="card">
    <div id="chart"></div>
    <div class="hint">🔴 = هشدار فروش &nbsp; 🟢 = هشدار خرید &nbsp; ⚡ = رویداد critical &nbsp; — میله‌های پایین = امتیاز فروش (قرمز) / خرید (سبز)</div>
  </div>
  <div class="card">
    <h3 style="margin:4px 0">📋 لحظات هشدار</h3>
    <div id="alertList"></div>
  </div>
</div>
<script>
function N(v, d) { d = d||0; if (v===null||v===undefined||isNaN(v)) return "—"; return Number(v).toFixed(d); }

async function loadSymbols() {
  const r = await fetch("/api/symbols");
  const d = await r.json();
  if (!d.ok) { document.getElementById("stats").innerHTML = "⚠ " + d.message; return; }
  const syms = Object.keys(d.symbols).sort();
  const sel = document.getElementById("sym");
  sel.innerHTML = syms.map(s => `<option value="${s}">${s}</option>`).join("");
  sel.onchange = () => {
    const dates = d.symbols[sel.value] || [];
    document.getElementById("date").innerHTML = dates.map(x=>`<option>${x}</option>`).join("");
  };
  sel.onchange();
}

async function load() {
  const sym = document.getElementById("sym").value;
  const date = document.getElementById("date").value;
  if (!sym || !date) return;
  const r = await fetch(`/api/replay?symbol=${encodeURIComponent(sym)}&date=${encodeURIComponent(date)}`);
  const d = await r.json();
  if (!d.ok) { document.getElementById("stats").innerHTML = "⚠ " + d.message; return; }
  renderChart(d);
  renderAlerts(d.alerts);
  renderStats(d);
}

function renderStats(d) {
  const al = d.alerts.length;
  const crit = d.alerts.filter(a=>a.type.includes("critical")).length;
  document.getElementById("stats").innerHTML = `
    <span class="stat">نماد: ${d.symbol}</span>
    <span class="stat">تاریخ: ${d.date}</span>
    <span class="stat">نمونه‌ها: ${d.count}</span>
    <span class="stat">معاملاتی: ${d.continuous_count}</span>
    <span class="stat">هشدارها: ${al}</span>
    <span class="stat">critical: ${crit}</span>`;
}

function renderAlerts(alerts) {
  if (!alerts.length) { document.getElementById("alertList").innerHTML = "<div class='hint'>هشداری ثبت نشد.</div>"; return; }
  let h = "<table><tr><th>زمان</th><th>نوع</th><th>فروش</th><th>خرید</th><th>طبقه</th><th>قیمت</th></tr>";
  for (const a of alerts) {
    const tc = a.type.includes("critical") ? "#c62828" : a.type.includes("sell") ? "#e53935" : "#43a047";
    h += `<tr><td>${a.time}</td><td style="color:${tc};font-weight:bold">${a.type}</td>
      <td>${N(a.sell_score,1)}</td><td>${N(a.buy_score,1)}</td>
      <td>${a.classification}</td><td>${N(a.price,0)}</td></tr>`;
  }
  h += "</table>";
  document.getElementById("alertList").innerHTML = h;
}

function renderChart(d) {
  const tl = d.timeline;
  const times = tl.map(t => t.time);
  const prices = tl.map(t => t.price);
  const sellScores = tl.map(t => t.sell_score);
  const buyScores = tl.map(t => t.buy_score);

  // نشانگرها
  const sellAlerts = { x:[], y:[], text:[], mode:"markers", type:"scatter",
    name:"هشدار فروش", marker:{color:"#c62828", size:11, symbol:"triangle-down"},
    hovertemplate:"<b>%{text}</b><br>زمان: %{x}<br>قیمت: %{y}<extra></extra>" };
  const buyAlerts = { x:[], y:[], text:[], mode:"markers", type:"scatter",
    name:"هشدار خرید", marker:{color:"#2e7d32", size:11, symbol:"triangle-up"},
    hovertemplate:"<b>%{text}</b><br>زمان: %{x}<br>قیمت: %{y}<extra></extra>" };
  const critAlerts = { x:[], y:[], text:[], mode:"markers", type:"scatter",
    name:"critical", marker:{color:"#f9a825", size:14, symbol:"star"},
    hovertemplate:"<b>%{text}</b><br>زمان: %{x}<br>قیمت: %{y}<extra></extra>" };

  for (const a of d.alerts) {
    const t = tl.find(t => t.time === a.time);
    if (!t) continue;
    const txt = `${a.type}\\nفروش:${N(a.sell_score,1)} خرید:${N(a.buy_score,1)}\\n${a.classification}`;
    if (a.type.includes("critical")) critAlerts.x.push(a.time), critAlerts.y.push(a.price), critAlerts.text.push(txt);
    else if (a.type.includes("sell")) sellAlerts.x.push(a.time), sellAlerts.y.push(a.price), sellAlerts.text.push(txt);
    else if (a.type.includes("buy")) buyAlerts.x.push(a.time), buyAlerts.y.push(a.price), buyAlerts.text.push(txt);
  }

  // تریس‌ها
  const priceTrace = { x:times, y:prices, mode:"lines", type:"scatter",
    name:"قیمت (last)", line:{color:"#1565c0", width:2},
    hovertemplate:"زمان: %{x}<br>قیمت: %{y}<extra></extra>" };

  const scoreTraces = [
    { x:times, y:sellScores, mode:"lines", type:"scatter", name:"امتیاز فروش",
      yaxis:"y2", line:{color:"#e53935", width:1}, fill:"tozeroy",
      hovertemplate:"زمان: %{x}<br>فروش: %{y}<extra></extra>" },
    { x:times, y:buyScores, mode:"lines", type:"scatter", name:"امتیاز خرید",
      yaxis:"y2", line:{color:"#43a047", width:1}, fill:"tonexty",
      hovertemplate:"زمان: %{x}<br>خرید: %{y}<extra></extra>" },
  ];

  const layout = {
    title: `${d.symbol} — ${d.date}`,
    margin:{t:40,b:40,l:60,r:60},
    xaxis:{title:"زمان", tickangle:-45},
    yaxis:{title:"قیمت", side:"right", gridcolor:"#eee"},
    yaxis2:{title:"امتیاز", overlaying:"y", side:"left", range:[0,100], showgrid:false},
    legend:{orientation:"h", y:1.12},
    hovermode:"x unified",
    shapes:[]
  };
  // خطوط عمودی برای لحظات هشدار
  for (const a of d.alerts) {
    layout.shapes.push({type:"line", x0:a.time, x1:a.time, y0:0, y1:1, yref:"paper",
      line:{color:"#bbb", width:1, dash:"dot"}});
  }

  Plotly.newPlot("chart", [priceTrace, ...scoreTraces, sellAlerts, buyAlerts, critAlerts], layout, {
    responsive:true, displaylogo:false
  });
}

loadSymbols();
</script>
</body>
</html>"""


@app.route("/")
def index():
    return INDEX_PAGE


@app.route("/replay")
def replay_page():
    return INDEX_PAGE


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def load_cfg() -> dict:
    import json
    return json.load(open(ROOT / "config" / "warning_thresholds.json", encoding="utf-8"))


def main():
    ap = argparse.ArgumentParser(
        description="بازپخش روزانه — بررسی سیگنال‌های موتور روی نمودار قیمت-زمان"
    )
    ap.add_argument("--db", default="data/early_warning_live.sqlite",
                    help="مسیر فایل SQLite حاوی snapshot‌ها")
    ap.add_argument("--port", type=int, default=8060)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    db_path = ROOT / args.db
    cfg = load_cfg()
    app.config["DB_PATH"] = str(db_path)
    app.config["CFG"] = cfg

    print("=" * 60)
    print("📊 بازپخش روزانه — تحلیل سیگنال‌ها روی نمودار قیمت-زمان")
    print(f"بانک داده: {db_path} ({'موجود' if db_path.exists() else '⚠ وجود ندارد'})")
    if db_path.exists():
        import sqlite3
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(DISTINCT symbol), COUNT(*) FROM snapshots")
            ns, n = cur.fetchone()
            print(f"نمادها: {ns}، مجموع snapshot‌ها: {n}")
        except Exception:
            pass
        conn.close()
    print(f"آدرس    : http://localhost:{args.port}")
    print("=" * 60)
    print("نکته: ابتدا نماد و تاریخ را انتخاب کنید، سپس «بازپخش» را بزنید.")
    print("      نماد از test_symbol خوانده نمی‌شود — از داده‌های DB انتخاب می‌شود.")

    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
