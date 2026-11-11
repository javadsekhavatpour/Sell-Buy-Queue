"""
web_dashboard_live.py (نسخه جدید داشبورد رصد و تایید بصری)
داشبورد وب زنده برای نمایش شش گروه داده تابلو در یک صفحه، شبیه تابلوی TSETMC.

چیدمان صفحه (راست به چپ، مطابق تابلوی معاملاتی):
  سطر اول:  راست = گروه A (اطلاعات پایه و قیمت) | مرکز = گروه C (حجم/ارزش تجمعی) | چپ = گروه E (معاملات انجام‌شده)
  سطر دوم:  راست = گروه B (عمق بازار - پنج ردیف)  | مرکز = گروه D (حقیقی/حقوقی)   | چپ = گروه F (وضعیت بازار)
  سطر سوم:  نمودار روند قیمت در نمونه‌های اخیر

مهم:
  - این داشبورد «فقط نمایشی» است. هیچ داده‌ای در پایگاه داده، فایل یا CSV
    ذخیره نمی‌شود. همه‌چیز فقط در حافظه (RAM) نگه‌داری می‌شود و با بستن
    برنامه از بین می‌رود.
  - به‌روزرسانی خودکار صفحه هر ۵ ثانیه از طریق /api/live

دو حالت منبع داده:
  live  = دریافت زنده از TSETMC (مثل run_live.py)
  demo  = پخش داده شبیه‌ساز برای تست آفلاین چیدمان و تایید بصری

نحوه اجرا:
  python web_dashboard_live.py                     # حالت زنده با نماد پیکربندی
  python web_dashboard_live.py --mode demo         # تست آفلاین با شبیه‌ساز
  python web_dashboard_live.py --symbol دابور      # حالت زنده با نماد دیگر
  سپس مرورگر: http://localhost:8051

پارامترها:
  --mode      live | demo            (پیش‌فرض live)
  --scenario  normal | sell_pressure | accumulation | mixed   (فقط demo)
  --symbol    نام نماد               (پیش‌فرض: نماد پیکربندی)
  --ins-code  کد TSETMC              (اگر فقط --symbol بدهید خودکار جستجو می‌شود)
  --interval  فاصله نمونه‌برداری ثانیه  (پیش‌فرض: زنده ۱۵، شبیه‌سازی ۳)
  --samples   تعداد نمونه شبیه‌ساز    (پیش‌فرض ۲۲۶ = یک روز کامل)
  --port      پورت سرور              (پیش‌فرض 8051)
  --host      میزبان                 (پیش‌فرض 127.0.0.1)
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

try:
    from flask import Flask, jsonify
except ImportError:
    print("کتابخانه Flask نصب نیست.")
    print("نصب با: pip install flask")
    sys.exit(1)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning.data_collector import (
    MarketDataCollector,
    SimulationDataCollector,
    MarketSnapshot,
    Trade,
)


# ---------------------------------------------------------------------------
# تبدیل تاریخ میلادی به شمسی (الگوریتم استاندارد JDF - بدون وابستگی بیرونی)
# ---------------------------------------------------------------------------

def gregorian_to_jalali(gy: int, gm: int, gd: int):
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + (days // 31)
        jd = 1 + (days % 31)
    else:
        jm = 7 + ((days - 186) // 30)
        jd = 1 + ((days - 186) % 30)
    return jy, jm, jd


def today_jalali_str() -> str:
    n = datetime.now()
    jy, jm, jd = gregorian_to_jalali(n.year, n.month, n.day)
    return f"{jy}-{jm:02d}-{jd:02d}"


def load_cfg() -> dict:
    p = ROOT / "config" / "warning_thresholds.json"
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# مانیتور زنده - فقط حافظه، بدون هیچ ذخیره‌سازی
# ---------------------------------------------------------------------------

class LiveMonitor:
    """
    جمع‌آوری نمونه‌های تابلو در حافظه و ساخت بار JSON برای داشبورد.

    حالت live : هر interval ثانیه یک نمونه از TSETMC دریافت می‌شود.
    حالت demo : سری کامل شبیه‌ساز یک‌بار ساخته می‌شود و نمونه‌به‌نمونه
                (هر interval ثانیه) پخش می‌شود تا داشبورد «زنده» دیده شود.
    """

    def __init__(self, cfg: dict, mode: str = "live", symbol: str | None = None,
                 ins_code: str | None = None, interval: int | None = None,
                 scenario: str = "sell_pressure", samples: int = 226,
                 max_history: int = 300):
        self.cfg = cfg
        self.mode = mode
        sym = cfg.get("test_symbol", {})
        self.symbol = symbol or sym.get("name", "ریتون")
        self.ins_code = str(ins_code or sym.get("ins_code", ""))
        self.interval = interval or (15 if mode == "live" else 3)
        self.scenario = scenario
        self.samples = samples
        self.history: deque[MarketSnapshot] = deque(maxlen=max_history)
        self.recent_trades: deque[Trade] = deque(maxlen=15)
        self.last_error: str = ""
        self.last_fetch_time: str = ""
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.collector = None
        self._demo_snaps: list[MarketSnapshot] = []
        self._trades_by_time: dict[str, list[Trade]] = {}

    # --- اجرای حلقه پس‌زمینه ---

    def start(self):
        if self.mode == "live":
            self.collector = MarketDataCollector(self.cfg)
            target = self._loop_live
        else:
            sim = SimulationDataCollector(self.cfg, scenario=self.scenario)
            snaps, trades = sim.generate_series(num_samples=self.samples)
            self._demo_snaps = snaps
            for tr in trades:
                self._trades_by_time.setdefault(tr.trade_time, []).append(tr)
            target = self._loop_demo
        self._thread = threading.Thread(target=target, daemon=True, name="live-monitor")
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _publish(self, snap: MarketSnapshot, trades: list[Trade] | None):
        if snap and not snap.date_jalali:
            snap.date_jalali = today_jalali_str()
        with self._lock:
            if snap is not None:
                self.history.append(snap)
            for tr in (trades or []):
                self.recent_trades.append(tr)
            self.last_error = (snap.fetch_error if snap else "") or ""
            self.last_fetch_time = datetime.now().isoformat(timespec="seconds")

    def _loop_live(self):
        prev: MarketSnapshot | None = None
        while not self._stop.is_set():
            try:
                snap, trades = self.collector.collect(self.symbol, self.ins_code, prev)
                self._publish(snap, trades)
                prev = snap if (snap is not None and snap.data_status != "error") else None
            except Exception as e:
                with self._lock:
                    self.last_error = f"خطای جمع‌آوری: {e}"
                    self.last_fetch_time = datetime.now().isoformat(timespec="seconds")
            self._stop.wait(self.interval)

    def _loop_demo(self):
        n = len(self._demo_snaps)
        i = 0
        while not self._stop.is_set():
            snap = self._demo_snaps[i % n]
            self._publish(snap, self._trades_by_time.get(snap.tehran_time, []))
            i += 1
            self._stop.wait(self.interval)

    # --- شاخص‌های مشتق برای تایید بصری (گروه A) ---

    def _derived(self, hist: list[MarketSnapshot]) -> dict:
        s = hist[-1]
        d: dict = {}
        y = s.yesterday_price or 0.0
        d["change_pct"] = round((s.last_price - y) / y * 100, 2) if y > 0 else None
        d["close_change_pct"] = round((s.close_price - y) / y * 100, 2) if y > 0 else None
        d["last_to_close_diff"] = round(s.last_price - s.close_price, 2) if s.close_price > 0 else None
        d["last_to_close_pct"] = (round((s.last_price - s.close_price) / s.close_price * 100, 2)
                                  if s.close_price > 0 else None)
        d["dist_to_floor_pct"] = (round((s.min_allowed_price - s.last_price) / s.min_allowed_price * 100, 2)
                                  if s.min_allowed_price > 0 else None)
        d["dist_to_ceiling_pct"] = (round((s.max_allowed_price - s.last_price) / s.max_allowed_price * 100, 2)
                                    if s.max_allowed_price > 0 else None)
        # سرعت تغییر قیمت آخرین (ریال بر دقیقه) بر اساس فاصله واقعی زمانی نمونه‌ها
        d["speed_per_min"] = None
        if len(hist) >= 6:
            older, newer = hist[-6], hist[-1]
            try:
                t0 = datetime.fromisoformat(older.timestamp)
                t1 = datetime.fromisoformat(newer.timestamp)
                minutes = (t1 - t0).total_seconds() / 60.0
                if minutes > 0:
                    d["speed_per_min"] = round((newer.last_price - older.last_price) / minutes, 1)
            except Exception:
                pass
        d["volume_vs_base_pct"] = (round(s.total_volume / s.base_volume * 100, 1)
                                   if s.base_volume and s.base_volume > 0 else None)
        return d

    # --- بار JSON برای صفحه ---

    def payload(self) -> dict:
        with self._lock:
            hist = list(self.history)
            trades = list(self.recent_trades)
            last_error = self.last_error
            last_fetch = self.last_fetch_time
        base = {
            "mode": self.mode,
            "scenario": self.scenario if self.mode == "demo" else "",
            "interval": self.interval,
            "server_time": datetime.now().isoformat(timespec="seconds"),
        }
        if not hist:
            base.update({
                "ok": False,
                "message": "در حال دریافت نخستین نمونه از منبع داده...",
                "collector": {"last_fetch": last_fetch, "last_error": last_error},
            })
            return base
        s = hist[-1]
        base.update({
            "ok": True,
            "samples": len(hist),
            "snapshot": s.to_dict(),
            "derived": self._derived(hist),
            "trades": [
                {
                    "trade_time": t.trade_time,
                    "trade_price": t.trade_price,
                    "trade_volume": t.trade_volume,
                    "trade_id": t.trade_id or "",
                    "aggressor_side": t.aggressor_side or "",
                }
                for t in list(reversed(trades[-12:]))
            ],
            "history": {
                "time": [h.tehran_time for h in hist],
                "last": [h.last_price for h in hist],
                "close": [h.close_price for h in hist],
                "interval_volume": [h.interval_volume for h in hist],
            },
            "collector": {"last_fetch": last_fetch, "last_error": last_error},
        })
        return base


# ---------------------------------------------------------------------------
# سرور Flask
# ---------------------------------------------------------------------------

MONITOR: LiveMonitor | None = None
app = Flask(__name__)


@app.route("/")
def index():
    return HTML_PAGE


@app.route("/api/live")
def api_live():
    if MONITOR is None:
        return jsonify({"ok": False, "message": "مانیتور راه‌اندازی نشده است"}), 500
    return jsonify(MONITOR.payload())


# ---------------------------------------------------------------------------
# صفحه داشبورد (HTML/CSS/JS داخلی - بدون کتابخانه بیرونی)
# ---------------------------------------------------------------------------

HTML_PAGE = """<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>داشبورد رصد زنده تابلو - گروه‌های A تا F</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css">
<style>
:root{
  --up:#0a8f3c; --up-bg:#e6f5ec;
  --down:#c62828; --down-bg:#fdeaea;
  --blue:#1565c0; --amber:#ef6c00;
  --panel-head:#22344c; --line:#d8e0ea; --ink:#1f2d3d; --muted:#5a6b7f;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:Vazirmatn,Tahoma,'Segoe UI',sans-serif;background:#e9edf2;color:var(--ink);font-size:13px;padding:10px}
.wrap{max-width:1560px;margin:0 auto}
/* نوار بالا */
header.top{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 14px;display:flex;flex-wrap:wrap;gap:10px 18px;align-items:center;margin-bottom:10px}
header.top .sym{font-size:22px;font-weight:800}
header.top .code{font-size:12px;color:var(--muted);font-weight:400}
.badge{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:20px;font-size:12px;font-weight:600;white-space:nowrap}
.b-blue{background:#e3f0fd;color:var(--blue)}
.b-amber{background:#fff3e0;color:var(--amber)}
.b-green{background:var(--up-bg);color:var(--up)}
.b-red{background:var(--down-bg);color:var(--down)}
.b-gray{background:#eceff3;color:var(--muted)}
.dot{width:9px;height:9px;border-radius:50%;background:var(--up);display:inline-block}
.dot.off{background:var(--down)}
.clockbox{margin-inline-start:auto;text-align:left;min-width:150px}
.clock{font-size:16px;font-weight:700;direction:ltr}
.note-nodb{font-size:11px;color:var(--muted)}
/* شبکه سه‌ستونه */
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px}
@media(max-width:1100px){.grid3{grid-template-columns:1fr}}
.panel{background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden;display:flex;flex-direction:column}
.panel h2{background:var(--panel-head);color:#fff;font-size:13px;font-weight:700;padding:8px 12px;display:flex;align-items:center;gap:8px}
.gnum{width:22px;height:22px;border-radius:50%;background:#f0a500;color:#fff;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;flex-shrink:0}
.panel .body{padding:8px 12px;flex:1}
.hint{font-size:11px;color:var(--muted);margin-top:6px}
/* قیمت بزرگ گروه A */
.bigrow{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;margin-bottom:8px}
.bigprice{font-size:30px;font-weight:800;direction:ltr}
.chg{font-size:14px;font-weight:700}
table{width:100%;border-collapse:collapse}
td,th{padding:4px 6px;border-bottom:1px solid #eef2f6;text-align:right}
tr:last-child td{border-bottom:none}
.kv td:first-child{color:var(--muted);width:55%;font-size:12px}
td.num{direction:ltr;text-align:right;font-variant-numeric:tabular-nums}
.up{color:var(--up)} .down{color:var(--down)} .blue{color:var(--blue)}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:4px}
.chip{background:#eceff3;color:var(--muted);border-radius:4px;padding:1px 7px;font-size:11px;direction:ltr}
/* نوار بازه مجاز */
.range{direction:ltr;position:relative;height:30px;margin:14px 2px 34px;background:linear-gradient(to right,var(--down-bg),#fff,var(--up-bg));border:1px solid var(--line);border-radius:6px}
.mk{position:absolute;top:-5px;transform:translateX(-50%);text-align:center;min-width:70px}
.mk i{display:block;width:3px;height:12px;margin:0 auto;border-radius:2px}
.mk span{font-size:10px;color:var(--muted);white-space:nowrap;line-height:1.3}
/* نوار پیشرفت */
.pbar{position:relative;height:16px;background:#eceff3;border-radius:4px;overflow:hidden;margin-top:4px}
.pbar i{position:absolute;inset-inline-start:0;top:0;bottom:0;background:#5c8bd6;border-radius:4px}
.pbar b{position:relative;z-index:1;font-size:11px;color:#233;line-height:16px;display:block;text-align:center}
/* عمق بازار گروه B */
.ob{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.ob .side h3{font-size:12px;text-align:center;padding:3px;border-radius:5px;margin-bottom:4px}
.ob .buy h3{background:var(--up-bg);color:var(--up)}
.ob .sell h3{background:var(--down-bg);color:var(--down)}
.obt{width:100%}
.obt th{font-size:11px;color:var(--muted);font-weight:600;border-bottom:1px solid var(--line)}
.obt td{padding:3px 4px;font-variant-numeric:tabular-nums}
.bar{position:relative;height:18px;display:flex;align-items:center}
.bar i{position:absolute;top:2px;bottom:2px;inset-inline-start:0;border-radius:3px}
.bar.buy i{background:rgba(10,143,60,.16)}
.bar.sell i{background:rgba(198,40,40,.13)}
.bar b{position:relative;z-index:1;font-size:11px;font-weight:600;direction:ltr}
.spread{display:flex;justify-content:space-between;background:#f4f7fa;border-radius:6px;padding:5px 10px;margin-top:8px;font-size:12px}
/* معاملات گروه E */
.ttable td,.ttable th{padding:3px 6px;text-align:center}
.ttable th{font-size:11px;color:var(--muted);border-bottom:1px solid var(--line)}
.side-buy{color:var(--up);font-weight:700}
.side-sell{color:var(--down);font-weight:700}
.wait{color:var(--muted);padding:14px 6px;text-align:center;font-size:12px}
/* نمودار سطر سوم */
#chart{direction:ltr;width:100%}
.legend{display:flex;gap:16px;font-size:11px;color:var(--muted);margin-top:6px;direction:rtl;justify-content:center}
.legend span b{display:inline-block;width:14px;height:3px;border-radius:2px;vertical-align:middle;margin-inline-end:4px}
#err{display:none;background:var(--down-bg);color:var(--down);border:1px solid #f2c1c1;border-radius:8px;padding:8px 12px;margin-bottom:10px;font-weight:600}
</style>
</head>
<body>
<div class="wrap">

  <div id="err"></div>

  <header class="top">
    <div>
      <div class="sym"><span id="h-symbol">—</span> <span class="code" id="h-code"></span></div>
      <div class="note-nodb">داشبورد فقط نمایشی - هیچ داده‌ای در پایگاه داده یا فایل ذخیره نمی‌شود</div>
    </div>
    <span class="badge b-blue" id="h-phase">—</span>
    <span class="badge b-gray" id="h-mode">—</span>
    <span class="badge b-gray" id="h-datast">—</span>
    <span class="badge b-green" id="h-conn"><span class="dot"></span>متصل</span>
    <div class="clockbox">
      <div class="clock" id="h-clock">—</div>
      <div class="note-nodb" id="h-date">—</div>
    </div>
  </header>

  <!-- سطر اول: راست A | مرکز C | چپ E -->
  <div class="grid3">
    <section class="panel">
      <h2><span class="gnum">A</span> اطلاعات پایه و قیمت</h2>
      <div class="body" id="p-a"><div class="wait">در انتظار داده...</div></div>
    </section>
    <section class="panel">
      <h2><span class="gnum">C</span> حجم، ارزش و تعداد معاملات تجمعی</h2>
      <div class="body" id="p-c"><div class="wait">در انتظار داده...</div></div>
    </section>
    <section class="panel">
      <h2><span class="gnum">E</span> معاملات انجام‌شده</h2>
      <div class="body" id="p-e"><div class="wait">در انتظار داده...</div></div>
    </section>
  </div>

  <!-- سطر دوم: راست B | مرکز D | چپ F -->
  <div class="grid3">
    <section class="panel">
      <h2><span class="gnum">B</span> عمق بازار - پنج ردیف سفارش خرید و فروش</h2>
      <div class="body" id="p-b"><div class="wait">در انتظار داده...</div></div>
    </section>
    <section class="panel">
      <h2><span class="gnum">D</span> اطلاعات حقیقی و حقوقی</h2>
      <div class="body" id="p-d"><div class="wait">در انتظار داده...</div></div>
    </section>
    <section class="panel">
      <h2><span class="gnum">F</span> وضعیت بازار و کیفیت داده</h2>
      <div class="body" id="p-f"><div class="wait">در انتظار داده...</div></div>
    </section>
  </div>

  <!-- سطر سوم: نمودار روند قیمت -->
  <section class="panel">
    <h2><span class="gnum">~</span> نمودار روند قیمت در نمونه‌های اخیر</h2>
    <div class="body">
      <div id="chart"><div class="wait">در انتظار نمونه‌های بیشتر...</div></div>
      <div class="legend">
        <span><b style="background:#1565c0"></b>آخرین قیمت معامله</span>
        <span><b style="background:#ef6c00"></b>قیمت پایانی</span>
        <span><b style="background:#9e9e9e"></b>قیمت دیروز</span>
        <span><b style="background:#90a4ae"></b>حجم معاملات فاصله‌ای</span>
      </div>
    </div>
  </section>

</div>

<script>
"use strict";
const PHASE = {pre_open:"پیش‌گشایش", opening_auction:"حراج نوبت", continuous:"معاملات پیوسته", halted:"توقف نماد", suspended:"ممنوع معامله", closed:"بازار بسته"};
const SYMST = {allowed:"مجاز", restricted:"ممنوع", halted:"متوقف"};
const DATAST = {ok:"کامل", partial:"ناقص", error:"خطا"};

const N = (v, d=0) => (v===null || v===undefined || isNaN(v)) ? "—" : Number(v).toLocaleString("fa-IR", {minimumFractionDigits:d, maximumFractionDigits:d});
const P = v => (v===null || v===undefined) ? "—" : (v>0?"+":"") + N(v,2) + "٪";
const CLS = v => v>0 ? "up" : (v<0 ? "down" : "");
const ARROW = v => v>0 ? "▲" : (v<0 ? "▼" : "");
const BIG = v => { if(v===null||v===undefined||isNaN(v)) return "—"; const a=Math.abs(v);
  if(a>=1e9) return N(v/1e9,2)+" میلیارد"; if(a>=1e6) return N(v/1e6,2)+" میلیون"; if(a>=1e3) return N(v/1e3,1)+" هزار"; return N(v); };
const SIDE = a => a==="buy" ? '<span class="side-buy">خرید</span>' : (a==="sell" ? '<span class="side-sell">فروش</span>' : "—");

function kv(label, value, cls="") {
  return `<tr><td>${label}</td><td class="num ${cls}">${value}</td></tr>`;
}

/* ---------- سربرگ ---------- */
function renderHeader(d) {
  const s = d.snapshot;
  document.getElementById("h-symbol").textContent = s.symbol || "—";
  document.getElementById("h-code").textContent = s.ins_code ? ("کد: " + s.ins_code) : "";
  document.getElementById("h-date").textContent = s.date_jalali || "—";
  document.getElementById("h-clock").textContent = s.tehran_time || "—";
  const ph = PHASE[s.market_phase] || s.market_phase;
  const phEl = document.getElementById("h-phase");
  phEl.textContent = ph;
  phEl.className = "badge " + (s.market_phase==="continuous" ? "b-green" : (s.market_phase==="closed" ? "b-gray" : "b-amber"));
  const md = document.getElementById("h-mode");
  md.textContent = d.mode==="live" ? "منبع: زنده (TSETMC)" : "منبع: شبیه‌ساز (" + d.scenario + ")";
  const ds = document.getElementById("h-datast");
  const dst = DATAST[s.data_status] || s.data_status;
  ds.textContent = "داده: " + dst + (s.data_complete ? "" : " (ناقص)");
  ds.className = "badge " + (s.data_status==="ok" ? "b-green" : (s.data_status==="error" ? "b-red" : "b-amber"));
}

/* ---------- گروه A ---------- */
function renderA(d) {
  const s = d.snapshot, der = d.derived;
  const chg = der.change_pct;
  const el = document.getElementById("p-a");
  let rangeBar = "";
  const mn = s.min_allowed_price, mx = s.max_allowed_price;
  if (mn>0 && mx>0 && mx>mn) {
    const pos = v => Math.max(1, Math.min(99, (v-mn)/(mx-mn)*100));
    const mk = (v,color,label) => `<div class="mk" style="left:${pos(v)}%"><i style="background:${color}"></i><span>${label}<br>${N(v)}</span></div>`;
    rangeBar = `<div class="range">
      ${mk(mn,"#c62828","کف مجاز")}
      ${s.last_price>0 ? mk(s.last_price,"#1565c0","آخرین") : ""}
      ${s.close_price>0 ? mk(s.close_price,"#ef6c00","پایانی") : ""}
      ${mk(mx,"#0a8f3c","سقف مجاز")}
    </div>`;
  }
  el.innerHTML = `
    <div class="bigrow">
      <div class="bigprice ${CLS(chg)}">${N(s.last_price)}</div>
      <div class="chg ${CLS(chg)}">${ARROW(chg)} ${P(chg)}<br><span style="font-size:11px;color:#5a6b7f">نسبت به دیروز</span></div>
      <div class="chg ${CLS(der.close_change_pct)}">${ARROW(der.close_change_pct)} ${P(der.close_change_pct)}<br><span style="font-size:11px;color:#5a6b7f">پایانی نسبت به دیروز</span></div>
    </div>
    <table class="kv">
      ${kv("تاریخ شمسی / زمان نمونه", (s.date_jalali||"—") + " - " + (s.tehran_time||"—"))}
      ${kv("قیمت پایانی", N(s.close_price))}
      ${kv("اولین قیمت روز", N(s.open_price))}
      ${kv("قیمت دیروز", N(s.yesterday_price))}
      ${kv("بالاترین قیمت روز", N(s.daily_high), "up")}
      ${kv("پایین‌ترین قیمت روز", N(s.daily_low), "down")}
      ${kv("کمترین قیمت مجاز", N(s.min_allowed_price))}
      ${kv("بیشترین قیمت مجاز", N(s.max_allowed_price))}
    </table>
    ${rangeBar}
    <table class="kv" style="margin-top:6px">
      ${kv("فاصله آخرین تا پایانی", `${N(der.last_to_close_diff)} (${P(der.last_to_close_pct)})`, CLS(der.last_to_close_diff))}
      ${kv("فاصله تا کف مجاز", P(der.dist_to_floor_pct), CLS(der.dist_to_floor_pct))}
      ${kv("فاصله تا سقف مجاز", P(der.dist_to_ceiling_pct), "")}
      ${kv("سرعت تغییر آخرین قیمت", (der.speed_per_min===null?"—":N(der.speed_per_min,1)+" ریال در دقیقه"), CLS(der.speed_per_min))}
    </table>`;
}

/* ---------- گروه C ---------- */
function renderC(d) {
  const s = d.snapshot, der = d.derived;
  const vb = der.volume_vs_base_pct;
  const w = Math.min(100, vb||0);
  document.getElementById("p-c").innerHTML = `
    <table class="kv">
      ${kv("حجم کل معاملات", N(s.total_volume))}
      ${kv("ارزش کل معاملات (ریال)", BIG(s.total_value))}
      ${kv("تعداد کل معاملات", N(s.total_trade_count))}
      ${kv("حجم مبنا", N(s.base_volume))}
      ${kv("حجم معاملات فاصله اخیر", N(s.interval_volume))}
      ${kv("ارزش معاملات فاصله اخیر (ریال)", BIG(s.interval_value))}
      ${kv("تعداد معاملات فاصله اخیر", N(s.interval_trade_count))}
    </table>
    <div class="hint">سهم حجم کل نسبت به حجم مبنا</div>
    <div class="pbar"><i style="width:${w}%"></i><b>${vb===null?"—":N(vb,1)+"٪ حجم مبنا"}</b></div>
    <div class="hint">مقادیر فاصله‌ای از تفاضل دو نمونه آخر به‌دست می‌آیند (در نخستین نمونه صفر هستند).</div>`;
}

/* ---------- گروه E ---------- */
function renderE(d) {
  const el = document.getElementById("p-e");
  const trs = d.trades || [];
  if (!trs.length) {
    const msg = d.mode==="live"
      ? "در نسخه فعلی جمع‌کننده زنده، فهرست لحظه‌ای معاملات از منبع در دسترس نیست (ستون اختیاری گروه E)."
      : "در انتظار معاملات...";
    el.innerHTML = `<div class="wait">${msg}</div>`;
    return;
  }
  let rows = "";
  for (const t of trs) {
    rows += `<tr>
      <td class="num">${t.trade_time}</td>
      <td class="num">${N(t.trade_price)}</td>
      <td class="num">${N(t.trade_volume)}</td>
      <td class="num" style="font-size:10px;color:#5a6b7f">${t.trade_id||"—"}</td>
      <td>${SIDE(t.aggressor_side)}</td>
    </tr>`;
  }
  el.innerHTML = `
    <table class="ttable">
      <thead><tr><th>زمان</th><th>قیمت</th><th>حجم</th><th>شناسه</th><th>آغازگر</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
    <div class="hint">۱۲ معامله آخر در حافظه - جدیدترین در بالا.</div>`;
}

/* ---------- گروه B ---------- */
function renderB(d) {
  const s = d.snapshot;
  const el = document.getElementById("p-b");
  const buys = s.buy_rows || [], sells = s.sell_rows || [];
  if (!buys.length && !sells.length) {
    el.innerHTML = `<div class="wait">عمق بازار در دسترس نیست (در حالت خطای اتصال رخ می‌دهد).</div>`;
    return;
  }
  const maxVol = Math.max(1, ...buys.map(r=>r.volume), ...sells.map(r=>r.volume));
  const side = (rows, cls) => {
    let h = `<div class="side ${cls}"><h3>${cls==="buy"?"خرید":"فروش"}</h3>
      <table class="obt"><thead><tr><th>قیمت</th><th>حجم</th><th>تعداد</th></tr></thead><tbody>`;
    for (const r of rows) {
      const w = Math.round(r.volume/maxVol*100);
      h += `<tr>
        <td class="num ${cls}">${N(r.price)}</td>
        <td><div class="bar ${cls}"><i style="width:${w}%"></i><b>${N(r.volume)}</b></div></td>
        <td class="num">${N(r.order_count)}</td>
      </tr>`;
    }
    h += `</tbody></table></div>`;
    return h;
  };
  const spread = (s.best_sell_price>0 && s.best_buy_price>0) ? (s.best_sell_price - s.best_buy_price) : null;
  el.innerHTML = `
    <div class="ob">
      ${side(buys,"buy")}
      ${side(sells,"sell")}
    </div>
    <div class="spread">
      <span>بهترین خرید: <b class="up">${N(s.best_buy_price)}</b> (${N(s.best_buy_volume)})</span>
      <span>اختلاف: <b>${N(spread)}</b></span>
      <span>بهترین فروش: <b class="down">${N(s.best_sell_price)}</b> (${N(s.best_sell_volume)})</span>
    </div>
    <div class="hint">مجموع تعداد سفارش‌های خرید: ${N(s.buy_order_count)} - مجموع فروش: ${N(s.sell_order_count)}</div>`;
}

/* ---------- گروه D ---------- */
function renderD(d) {
  const s = d.snapshot;
  const tv = s.total_volume>0 ? s.total_volume : 1;
  const row = (name, b, sl) => `
    <tr>
      <td>${name}</td>
      <td class="num">${N(b.count)}</td><td class="num">${N(b.volume)}</td><td class="num">${BIG(b.value)}</td>
      <td class="num">${N(sl.count)}</td><td class="num">${N(sl.volume)}</td><td class="num">${BIG(sl.value)}</td>
    </tr>`;
  const share = v => Math.round(v/tv*1000)/10;
  document.getElementById("p-d").innerHTML = `
    <table>
      <thead>
        <tr><th rowspan="2"></th><th colspan="3" class="up">خرید</th><th colspan="3" class="down">فروش</th></tr>
        <tr><th class="up">تعداد</th><th class="up">حجم</th><th class="up">ارزش</th><th class="down">تعداد</th><th class="down">حجم</th><th class="down">ارزش</th></tr>
      </thead>
      <tbody>
        ${row("حقیقی", {count:s.real_buy_count, volume:s.real_buy_volume, value:s.real_buy_value},
                        {count:s.real_sell_count, volume:s.real_sell_volume, value:s.real_sell_value})}
        ${row("حقوقی", {count:s.legal_buy_count, volume:s.legal_buy_volume, value:s.legal_buy_value},
                        {count:s.legal_sell_count, volume:s.legal_sell_volume, value:s.legal_sell_value})}
      </tbody>
    </table>
    <table class="kv" style="margin-top:6px">
      ${kv("سهم حقیقی از حجم کل (خرید / فروش)", `${N(share(s.real_buy_volume),1)}٪ / ${N(share(s.real_sell_volume),1)}٪`)}
      ${kv("سرانه خرید حقیقی", N(s.per_capita_buy_real,0))}
      ${kv("سرانه فروش حقیقی", N(s.per_capita_sell_real,0))}
      ${kv("قدرت خریدار حقیقی (سرانه خرید به فروش)", N(s.buyer_power,2), CLS(s.buyer_power-1))}
      ${kv("پول حقیقی خالص (ریال)", BIG(s.real_money_flow), CLS(s.real_money_flow))}
      ${kv("نسبت پول حقیقی به ارزش کل", P(s.real_money_flow_ratio*100), CLS(s.real_money_flow))}
    </table>`;
}

/* ---------- گروه F ---------- */
function renderF(d) {
  const s = d.snapshot, c = d.collector || {};
  const ph = PHASE[s.market_phase] || s.market_phase;
  const st = SYMST[s.symbol_status] || s.symbol_status;
  const missing = s.missing_fields || [];
  let chips = "";
  for (const m of missing) chips += `<span class="chip">${m}</span>`;
  const errRow = (c.last_error || s.fetch_error)
    ? kv("خطای دریافت داده", '<span class="down">' + (s.fetch_error || c.last_error) + "</span>")
    : kv("خطای دریافت داده", "ندارد");
  document.getElementById("p-f").innerHTML = `
    <table class="kv">
      ${kv("وضعیت بازار", ph)}
      ${kv("وضعیت نماد", st)}
      ${kv("آخرین به‌روزرسانی منبع", (s.source_update_time||"—").replace("T"," ").slice(0,19))}
      ${kv("وضعیت داده نمونه", (DATAST[s.data_status]||s.data_status) + (s.data_complete ? " (کامل)" : ""))}
      ${errRow}
      ${kv("حالت منبع", d.mode==="live" ? "زنده (TSETMC)" : "شبیه‌ساز - سناریوی " + d.scenario)}
      ${kv("فاصله نمونه‌برداری", N(d.interval) + " ثانیه")}
      ${kv("تعداد نمونه در حافظه", N(d.samples))}
      ${kv("آخرین دریافت جمع‌کننده", (c.last_fetch||"—").replace("T"," ").slice(0,19) || "—")}
    </table>
    ${missing.length ? '<div class="hint">فیلدهای ناقص این نمونه:</div><div class="chips">'+chips+'</div>' : ""}
    <div class="hint">گروه F برای جلوگیری از تفسیر اشتباه سایر گروه‌ها نمایش داده می‌شود.</div>`;
}

/* ---------- نمودار سطر سوم ---------- */
function renderChart(d) {
  const h = d.history || {};
  const el = document.getElementById("chart");
  const n = (h.last||[]).length;
  if (n < 2) { el.innerHTML = '<div class="wait">در انتظار نمونه‌های بیشتر...</div>'; return; }
  const K = 120;
  const times = h.time.slice(-K), last = h.last.slice(-K), close = h.close.slice(-K), vol = (h.interval_volume||[]).slice(-K);
  const W = 1400, H = 300, padL = 10, padR = 74, padT = 14, padB = 30, volH = 62;
  const plotW = W - padL - padR, priceH = H - padT - padB - volH;
  const yst = d.snapshot.yesterday_price;
  let mn = Math.min(...last, ...close), mx = Math.max(...last, ...close);
  if (yst > 0) { mn = Math.min(mn, yst); mx = Math.max(mx, yst); }
  const pad = (mx-mn)*0.06 || 1; mn -= pad; mx += pad;
  const X = i => padL + (plotW * i / (times.length-1));
  const Y = v => padT + priceH * (1 - (v-mn)/(mx-mn));
  const vmax = Math.max(1, ...vol);
  const pts = arr => arr.map((v,i)=>`${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(" ");
  let grid = "", ylabels = "";
  for (let g=0; g<=4; g++) {
    const v = mn + (mx-mn)*g/4, y = Y(v);
    grid += `<line x1="${padL}" y1="${y}" x2="${W-padR}" y2="${y}" stroke="#e3e9f0" stroke-width="1"/>`;
    ylabels += `<text x="${W-padR+6}" y="${y+4}" font-size="11" fill="#5a6b7f">${N(v)}</text>`;
  }
  let xlabels = "";
  const step = Math.max(1, Math.ceil(times.length/6));
  for (let i=0; i<times.length; i+=step) {
    xlabels += `<text x="${X(i)}" y="${H-8}" font-size="11" fill="#5a6b7f" text-anchor="middle">${times[i]}</text>`;
  }
  let bars = "";
  const bw = Math.max(1, plotW/times.length - 1.5);
  for (let i=0; i<times.length; i++) {
    if (!vol[i]) continue;
    const bh = volH * vol[i]/vmax;
    bars += `<rect x="${(X(i)-bw/2).toFixed(1)}" y="${(H-padB-volH+ (volH-bh)).toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" fill="#b9c7d8" opacity="0.75"/>`;
  }
  const lineLast = `<polyline points="${pts(last)}" fill="none" stroke="#1565c0" stroke-width="2.2" stroke-linejoin="round"/>`;
  const lineClose = `<polyline points="${pts(close)}" fill="none" stroke="#ef6c00" stroke-width="1.6" stroke-dasharray="5 4"/>`;
  let refLine = "";
  if (yst > 0 && yst>=mn && yst<=mx) {
    refLine = `<line x1="${padL}" y1="${Y(yst)}" x2="${W-padR}" y2="${Y(yst)}" stroke="#9e9e9e" stroke-width="1" stroke-dasharray="2 4"/>
      <text x="${padL+4}" y="${Y(yst)-4}" font-size="10" fill="#9e9e9e">دیروز ${N(yst)}</text>`;
  }
  const dotL = `<circle cx="${X(times.length-1)}" cy="${Y(last[last.length-1])}" r="3.5" fill="#1565c0"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet">
    ${grid}${bars}${refLine}${lineClose}${lineLast}${dotL}${ylabels}${xlabels}
  </svg>`;
}

/* ---------- چرخه به‌روزرسانی ---------- */
let connOk = false;
async function tick() {
  try {
    const r = await fetch("/api/live", {cache:"no-store"});
    const d = await r.json();
    connOk = true;
    document.getElementById("err").style.display = "none";
    const conn = document.getElementById("h-conn");
    conn.className = "badge b-green";
    conn.innerHTML = '<span class="dot"></span>متصل';
    if (!d.ok) {
      document.getElementById("p-a").innerHTML = '<div class="wait">' + (d.message||"در انتظار داده...") + "</div>";
      return;
    }
    renderHeader(d);
    renderA(d);
    renderC(d);
    renderE(d);
    renderB(d);
    renderD(d);
    renderF(d);
    renderChart(d);
  } catch (e) {
    connOk = false;
    const conn = document.getElementById("h-conn");
    conn.className = "badge b-red";
    conn.innerHTML = '<span class="dot off"></span>قطع ارتباط با سرور';
  }
}
tick();
setInterval(tick, 5000);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# اجرا
# ---------------------------------------------------------------------------

def main():
    global MONITOR
    ap = argparse.ArgumentParser(description="داشبورد زنده رصد تابلو (فقط نمایش، بدون ذخیره‌سازی)")
    ap.add_argument("--mode", choices=["live", "demo"], default="live",
                    help="حالت منبع داده: live=TSETMC واقعی، demo=شبیه‌ساز آفلاین")
    ap.add_argument("--scenario", choices=["normal", "sell_pressure", "accumulation", "mixed"],
                    default="sell_pressure", help="سناریوی شبیه‌ساز در حالت demo")
    ap.add_argument("--symbol", default=None, help="نام نماد (پیش‌فرض: پیکربندی)")
    ap.add_argument("--ins-code", default=None, help="کد TSETMC نماد")
    ap.add_argument("--interval", type=int, default=None, help="فاصله نمونه‌برداری (ثانیه)")
    ap.add_argument("--samples", type=int, default=226, help="تعداد نمونه شبیه‌ساز (حالت demo)")
    ap.add_argument("--port", type=int, default=8051)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    cfg = load_cfg()
    print(f"پیکربندی بارگذاری شد - نماد پیش‌فرض: {cfg['test_symbol']['name']}")

    if args.mode == "live" and args.symbol and not args.ins_code:
        print(f"جستجوی کد نماد '{args.symbol}' در TSETMC...")
        tmp = MarketDataCollector(cfg)
        res = tmp.search_symbol(args.symbol)
        if res:
            args.ins_code = res[0]["code"]
            print(f"کد پیدا شد: {args.ins_code}")
        else:
            print(f"نماد '{args.symbol}' پیدا نشد - از کد پیکربندی استفاده می‌شود.")

    MONITOR = LiveMonitor(
        cfg,
        mode=args.mode,
        symbol=args.symbol,
        ins_code=args.ins_code,
        interval=args.interval,
        scenario=args.scenario,
        samples=args.samples,
    )
    MONITOR.start()

    src = "TSETMC زنده" if args.mode == "live" else f"شبیه‌ساز (سناریو: {args.scenario})"
    print("=" * 60)
    print("داشبورد رصد زنده تابلو - فقط نمایش، بدون ذخیره‌سازی")
    print(f"منبع داده : {src}")
    print(f"نماد      : {MONITOR.symbol} (کد: {MONITOR.ins_code})")
    print(f"نمونه‌برداری: هر {MONITOR.interval} ثانیه")
    print(f"آدرس      : http://localhost:{args.port}")
    print("=" * 60)

    app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
