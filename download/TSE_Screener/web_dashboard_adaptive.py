"""
web_dashboard_adaptive.py — Phase 2.1
نسخه‌ی جدید داشبورد زنده با نمایش ستون «آستانه تطبیقی».

این فایل web_dashboard_live.py را دست نمی‌زند. به‌جای آن:
  ۱. مؤلفه‌های اصلی (LiveMonitor, HTML_PAGE, load_cfg, ...) را import می‌کند.
  ۲. یک زیرکلاس AdaptiveLiveMonitor می‌سازد که payload را با اطلاعات آستانه
     تطبیقی هر شاخص (threshold, samples, mode) غنی می‌کند.
  ۳. HTML را با جایگزینی هدفمند رشته‌ای، ستون «آستانه» به جدول فاکتورها اضافه
     می‌کند (بدون بازنویسی کل صفحه).
  ۴. یک Flask app تازه با مسیرهای / و /api/live به‌همراه مسیرهای اصلی می‌سازد.

اجرای:
  python web_dashboard_adaptive.py --mode live --symbol سرود
  python web_dashboard_adaptive.py --mode demo --scenario sell_pressure

تفاوت با نسخه اصلی: فقط گروه E (جدول شاخص‌ها) یک ستون اضافی دارد:
  شاخص | امتیاز | نرمال | **آستانه** | خام/وضع
آستانه: آبی = تطبیقی (صدک ۹۰ تاریخچه + تعداد نمونه)، خاکستری = ثابت (fallback).
"""

from __future__ import annotations

import argparse
import json
import threading
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request

# مؤلفه‌های نسخه اصلی — بدون تغییر
import web_dashboard_live as orig
from web_dashboard_live import (
    LiveMonitor,
    load_cfg,
    load_price_range_live,
    today_jalali_str,
)
from early_warning import (
    MarketDataCollector,
    MarketDataStorage,
    AdaptiveNormalizer,
    MarketSnapshot,
    Trade,
    SellPressureDetector,
    BuyPressureDetector,
    AlertEngine,
)
from early_warning.alert_engine import tier, classify

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------------------
# ساخت HTML تطبیقی: جایگزینی هدفمند سه بخش از HTML_PAGE اصلی
# ---------------------------------------------------------------------------

# بخش ۱: تابع cell + حلقه ردیف‌های فاکتور → افزودن ستون آستانه
_OLD_CELL_BLOCK = """  // ردیف‌های شاخص‌ها (هر دو موتور در یک جدول)
  const sFactors = sell.factors || [];
  const bFactors = buy.factors || [];
  const nRows = Math.max(sFactors.length, bFactors.length);
  let factorRows = "";
  for (let i = 0; i < nRows; i++) {
    const sf = sFactors[i] || {};
    const bf = bFactors[i] || {};
    const cell = f => {
      if (!f.name) return '<td colspan="4" style="color:#ccc">—</td>';
      const sc = f.score || 0, mx = f.max_points || 0;
      const pct = mx > 0 ? Math.round(sc / mx * 100) : 0;
      const col = pct >= 50 ? "#c62828" : pct >= 25 ? "#f9a825" : "#2e7d32";
      const rv = (f.raw_value === null || f.raw_value === undefined) ? "—" : N(f.raw_value, 3);
      return `<td class="num" style="color:${col}">${N(sc, 1)}/${N(mx, 0)}</td>
        <td class="num">${N((f.normalized || 0) * 100, 0)}٪</td>
        <td class="num" style="font-size:9px;color:#888">${rv}</td>
        <td style="font-size:9px;color:#888" title="${f.description||''}">${f.status === 'ok' ? '✓' : (f.status||'')}</td>`;
    };
    factorRows += `<tr>
      <td style="font-size:10px">${sf.label || '—'}</td>${cell(sf)}
      <td style="font-size:10px;background:#f5f5f5">${bf.label || '—'}</td>${cell(bf)}
    </tr>`;
  }"""

_NEW_CELL_BLOCK = """  // ردیف‌های شاخص‌ها (هر دو موتور در یک جدول) — Phase 2.1: ستون آستانه تطبیقی
  const sFactors = sell.factors || [];
  const bFactors = buy.factors || [];
  const nRows = Math.max(sFactors.length, bFactors.length);
  let factorRows = "";
  for (let i = 0; i < nRows; i++) {
    const sf = sFactors[i] || {};
    const bf = bFactors[i] || {};
    const cell = f => {
      if (!f.name) return '<td colspan="5" style="color:#ccc">—</td>';
      const sc = f.score || 0, mx = f.max_points || 0;
      const pct = mx > 0 ? Math.round(sc / mx * 100) : 0;
      const col = pct >= 50 ? "#c62828" : pct >= 25 ? "#f9a825" : "#2e7d32";
      const rv = (f.raw_value === null || f.raw_value === undefined) ? "—" : N(f.raw_value, 3);
      // آستانه تطبیقی (Phase 2.1)
      let thCell;
      if (f.adaptive_threshold === undefined || f.adaptive_threshold === null) {
        thCell = '<span style="color:#ccc">—</span>';
      } else if (f.adaptive_mode) {
        thCell = `<span style="color:#1565c0;font-weight:bold">${N(f.adaptive_threshold,3)}</span>` +
                 `<br><span style="font-size:8px;color:#1565c0">تطبیقی (${f.adaptive_samples||0})</span>`;
      } else {
        const tag = (f.adaptive_enabled === false) ? 'ثابت' : 'گرم ('+(f.adaptive_samples||0)+')';
        thCell = `<span style="color:#999">${N(f.adaptive_threshold,3)}</span>` +
                 `<br><span style="font-size:8px;color:#bbb">${tag}</span>`;
      }
      return `<td class="num" style="color:${col}">${N(sc, 1)}/${N(mx, 0)}</td>
        <td class="num">${N((f.normalized || 0) * 100, 0)}٪</td>
        <td class="num" style="font-size:9px">${thCell}</td>
        <td class="num" style="font-size:9px;color:#888">${rv}</td>
        <td style="font-size:9px;color:#888" title="${f.description||''}">${f.status === 'ok' ? '✓' : (f.status||'')}</td>`;
    };
    factorRows += `<tr>
      <td style="font-size:10px">${sf.label || '—'}</td>${cell(sf)}
      <td style="font-size:10px;background:#f5f5f5">${bf.label || '—'}</td>${cell(bf)}
    </tr>`;
  }"""

# بخش ۲: سرتیس جدول → افزودن ستون «آستانه» و افزایش colspan
_OLD_HEADER = """    <table class="ttable" style="font-size:10px">
      <thead><tr>
        <th colspan="4" style="background:#fdecea;color:#c62828">شاخص‌های فروش</th>
        <th colspan="4" style="background:#e8f5e9;color:#2e7d32">شاخص‌های خرید</th>
      </tr><tr>
        <th>شاخص</th><th>امتیاز</th><th>نرمال</th><th>خام/وضع</th>
        <th>شاخص</th><th>امتیاز</th><th>نرمال</th><th>خام/وضع</th>
      </tr></thead>
      <tbody>${factorRows}</tbody>
    </table>"""

_NEW_HEADER = """    <table class="ttable" style="font-size:10px">
      <thead><tr>
        <th colspan="5" style="background:#fdecea;color:#c62828">شاخص‌های فروش</th>
        <th colspan="5" style="background:#e8f5e9;color:#2e7d32">شاخص‌های خرید</th>
      </tr><tr>
        <th>شاخص</th><th>امتیاز</th><th>نرمال</th><th>آستانه</th><th>خام/وضع</th>
        <th>شاخص</th><th>امتیاز</th><th>نرمال</th><th>آستانه</th><th>خام/وضع</th>
      </tr></thead>
      <tbody>${factorRows}</tbody>
    </table>"""

# بخش ۳: راهنمای زیر جدول → توضیح آستانه تطبیقی
_OLD_HINT = '    <div class="hint">۱۲ شاخص مستقل — فروش (قرمز) و خرید (سبز). نرمال‌سازی آستانه ثابت (Phase 1).</div>`;'

_NEW_HINT = ('    <div class="hint">۱۲ شاخص مستقل — ستون «آستانه»: '
             '<span style="color:#1565c0">آبی=تطبیقی</span> (صدک ۹۰ تاریخچه + تعداد نمونه)، '
             '<span style="color:#999">خاکستری=ثابت/گرم</span> (Phase 1 fallback).</div>`;')

# ---------------------------------------------------------------------------
# Phase 2.1+: overlay سیگنال‌های موتور روی نمودار قیمت موجود
# ---------------------------------------------------------------------------

# Patch A: درج آرایه scoreHist + تابع pushScore قبل از چرخه به‌روزرسانی
_OLD_TICK_HEADER = """/* ---------- چرخه به‌روزرسانی ---------- */
let connOk = false;"""

_NEW_TICK_HEADER = """/* ---------- Phase 2.1+: score history for signal overlay ---------- */
let scoreHist = [];
function pushScore(d) {
  if (!d || !d.ok || !d.snapshot || !d.engines) return;
  const t = d.snapshot.tehran_time;
  if (!t) return;
  const eng = d.engines, sell = eng.sell||{}, buy = eng.buy||{}, comb = eng.combined||{};
  const entry = {
    time: t,
    sell: sell.total_score || 0,
    buy: buy.total_score || 0,
    crit: (comb.is_critical === true) || /\u0628\u062d\u0631\u0627\u0646|\u062a\u0642\u0627\u0628\u0644/.test(eng.classification||''),
    cls: eng.classification || ''
  };
  if (scoreHist.length && scoreHist[scoreHist.length-1].time === t) {
    scoreHist[scoreHist.length-1] = entry;
  } else {
    scoreHist.push(entry);
  }
  if (scoreHist.length > 300) scoreHist.shift();
}

/* ---------- \u0686\u0631\u062e\u0647 \u0628\u0647\u200c\u0631\u0648\u0632\u0631\u0633\u0627\u0646\u06cc ---------- */
let connOk = false;"""

# Patch B: جایگزینی انتهای renderChart — افزودن نشانگرهای سیگنال + راهنما
_OLD_CHART_TAIL = """  const dotL = `<circle cx="${X(times.length-1)}" cy="${Y(last[last.length-1])}" r="3.5" fill="#1565c0"/>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet">
    ${grid}${bars}${refLine}${lineClose}${lineLast}${dotL}${ylabels}${xlabels}
  </svg>`;
}"""

_NEW_CHART_TAIL = """  const dotL = `<circle cx="${X(times.length-1)}" cy="${Y(last[last.length-1])}" r="3.5" fill="#1565c0"/>`;
  // Phase 2.1+: overlay engine signals on price chart
  const SIG_TH = 50;
  let sigMarkers = "", sigCount = 0;
  for (const s of scoreHist) {
    const idx = times.indexOf(s.time);
    if (idx < 0) continue;
    const x = X(idx).toFixed(1), y = Y(last[idx]);
    let m = "";
    if (s.crit) {
      m = `<polygon points="${x},${(y-10).toFixed(1)} ${(x-7)},${(y+5).toFixed(1)} ${(x+7)},${(y+5).toFixed(1)}" fill="#f9a825" stroke="#e65100" stroke-width="1.2"><title>${s.time} \u2605 critical \u2014 sell:${N(s.sell,1)} buy:${N(s.buy,1)} | ${s.cls}</title></polygon>`;
      sigCount++;
    } else if (s.sell >= SIG_TH) {
      m = `<polygon points="${x},${(y+10).toFixed(1)} ${(x-6)},${(y-3).toFixed(1)} ${(x+6)},${(y-3).toFixed(1)}" fill="#c62828"><title>${s.time} \u25bc sell:${N(s.sell,1)} | ${s.cls}</title></polygon>`;
      sigCount++;
    } else if (s.buy >= SIG_TH) {
      m = `<polygon points="${x},${(y-10).toFixed(1)} ${(x-6)},${(y+3).toFixed(1)} ${(x+6)},${(y+3).toFixed(1)}" fill="#2e7d32"><title>${s.time} \u25b2 buy:${N(s.buy,1)} | ${s.cls}</title></polygon>`;
      sigCount++;
    }
    sigMarkers += m;
  }
  const sigLegend = `<text x="${padL+4}" y="${padT+10}" font-size="11" fill="${sigCount>0?'#5a6b7f':'#bbb'}">\u0633\u06cc\u06af\u0646\u0627\u0644\u200c\u0647\u0627 \u0631\u0648\u06cc \u0646\u0645\u0648\u062f\u0627\u0631: ${sigCount} \u0644\u062d\u0638\u0647 \u2014 \u25bc\u0641\u0631\u0648\u0634(\u2265${SIG_TH}) \u25b2\u062e\u0631\u06cc\u062f(\u2265${SIG_TH}) \u2605critical</text>`;
  el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" preserveAspectRatio="xMidYMid meet">
    ${sigLegend}${grid}${bars}${refLine}${lineClose}${lineLast}${dotL}${sigMarkers}${ylabels}${xlabels}
  </svg>`;
}"""

# Patch C: فراخوانی pushScore قبل از renderChart در tick
_OLD_TICK_RENDER = """    renderChart(d);
  } catch (e) {"""

_NEW_TICK_RENDER = """    pushScore(d); renderChart(d);
  } catch (e) {"""


# Patch D: نوار کنترل شبیه‌سازی (بعد از <div id="err"></div>)
_OLD_ERR_DIV = '<div id="err"></div>'

_SIM_BAR_HTML = """<div id="err"></div>
<div id="sim-bar" style="display:none;background:linear-gradient(135deg,#1a237e,#283593);color:#fff;padding:10px 14px;border-radius:10px;margin-bottom:12px;flex-wrap:wrap;gap:10px;align-items:center;font-size:14px">
  <span style="font-weight:700;font-size:15px">▶ شبیه‌سازی</span>
  <button id="sim-play-btn" onclick="simToggle()" style="background:rgba(255,255,255,0.2);border:none;color:#fff;padding:7px 14px;border-radius:6px;cursor:pointer;font-weight:700;font-size:14px">⏸ توقف</button>
  <select id="sim-speed-sel" onchange="simSetSpeed(this.value)" style="background:rgba(255,255,255,0.15);border:1px solid rgba(255,255,255,0.3);color:#fff;padding:6px 8px;border-radius:6px;font-size:14px">
    <option value="1">۱x</option>
    <option value="2">۲x</option>
    <option value="5">۵x</option>
    <option value="10" selected>۱۰x</option>
    <option value="20">۲۰x</option>
    <option value="50">۵۰x</option>
    <option value="100">۱۰۰x</option>
  </select>
  <button onclick="simStep(-10)" style="background:rgba(255,255,255,0.15);border:none;color:#fff;padding:6px 10px;border-radius:6px;cursor:pointer">◀◀ ۱۰-</button>
  <button onclick="simStep(-1)" style="background:rgba(255,255,255,0.15);border:none;color:#fff;padding:6px 10px;border-radius:6px;cursor:pointer">◀ ۱-</button>
  <button onclick="simStep(1)" style="background:rgba(255,255,255,0.15);border:none;color:#fff;padding:6px 10px;border-radius:6px;cursor:pointer">۱ ▶</button>
  <button onclick="simStep(10)" style="background:rgba(255,255,255,0.15);border:none;color:#fff;padding:6px 10px;border-radius:6px;cursor:pointer">۱۰ ▶▶</button>
  <span id="sim-progress" style="font-size:13px;opacity:0.9"></span>
  <input type="range" id="sim-seek" min="0" max="100" value="0" oninput="simSeekInput(this.value)" style="flex:1;min-width:180px;accent-color:#fff">
</div>"""

# Patch E: JS کنترل شبیه‌سازی (بعد از setInterval(tick, 5000))
_OLD_TICK_END = "setInterval(tick, 5000);"

_SIM_JS = """setInterval(tick, 5000);

// --- کنترل‌های شبیه‌سازی ---
let _simSeeking = false;
async function checkSim() {
  try {
    const r = await fetch('/api/sim/status', {cache:'no-store'});
    const d = await r.json();
    const bar = document.getElementById('sim-bar');
    if (d.mode === 'simulation') {
      bar.style.display = 'flex';
      updateSimBar(d);
    } else {
      bar.style.display = 'none';
    }
  } catch(e) {}
}
function updateSimBar(d) {
  const prog = document.getElementById('sim-progress');
  const btn = document.getElementById('sim-play-btn');
  const spd = document.getElementById('sim-speed-sel');
  const seek = document.getElementById('sim-seek');
  const idx = d.index, total = d.total;
  prog.textContent = N(idx+1) + ' / ' + N(total) + ' — ' + (d.current_time||'—') +
    ' — ' + (d.playing ? 'پخش' : 'توقف') + ' — ' + N(d.speed,1) + 'x';
  btn.textContent = d.playing ? '⏸ توقف' : '▶ پخش';
  if (spd.value != d.speed) spd.value = d.speed;
  seek.max = Math.max(1, total - 1);
  if (!_simSeeking) seek.value = idx;
  const md = document.getElementById('h-mode');
  if (md) md.textContent = 'شبیه‌سازی: ' + (d.date||'') + ' — ' + N(d.speed,1) + 'x';
}
async function simToggle() {
  try {
    const r = await fetch('/api/sim/status', {cache:'no-store'});
    const d = await r.json();
    if (d.playing) await fetch('/api/sim/pause', {method:'POST'});
    else await fetch('/api/sim/play', {method:'POST'});
    checkSim();
  } catch(e) {}
}
async function simSetSpeed(v) {
  await fetch('/api/sim/speed', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({speed: Number(v)})});
  checkSim();
}
async function simStep(n) {
  await fetch('/api/sim/step', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({n: n})});
  checkSim();
}
async function simSeekInput(v) {
  _simSeeking = true;
  await fetch('/api/sim/seek', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({index: Number(v)})});
  setTimeout(() => { _simSeeking = false; }, 500);
  checkSim();
}
setInterval(checkSim, 1000);
checkSim();"""


def _build_adaptive_html() -> str:
    """ساخت HTML تطبیقی با جایگزینی بخش‌های HTML_PAGE اصلی."""
    html = orig.HTML_PAGE
    misses = []
    for old, new, label in [
        (_OLD_CELL_BLOCK, _NEW_CELL_BLOCK, "cell"),
        (_OLD_HEADER, _NEW_HEADER, "header"),
        (_OLD_HINT, _NEW_HINT, "hint"),
        (_OLD_TICK_HEADER, _NEW_TICK_HEADER, "scoreHist"),
        (_OLD_CHART_TAIL, _NEW_CHART_TAIL, "chart-markers"),
        (_OLD_TICK_RENDER, _NEW_TICK_RENDER, "tick-hook"),
        (_OLD_ERR_DIV, _SIM_BAR_HTML, "sim-bar"),
        (_OLD_TICK_END, _SIM_JS, "sim-js"),
    ]:
        if old in html:
            html = html.replace(old, new, 1)
        else:
            misses.append(label)
    if misses:
        print(f"  ⚠ هشدار: بخش‌های زیر در HTML اصلی پیدا نشدند (شاید ساختار تغییر کرده): {misses}")
    return html


HTML_PAGE_ADAPTIVE = _build_adaptive_html()


# ---------------------------------------------------------------------------
# زیرکلاس LiveMonitor: غنی‌سازی payload با آستانه تطبیقی
# ---------------------------------------------------------------------------

class AdaptiveLiveMonitor(LiveMonitor):
    """
    نسخه‌ی LiveMonitor که اطلاعات آستانه تطبیقی را به هر فاکتور اضافه می‌کند.

    برای هر فاکتور در payload.engines.{sell,buy}.factors:
      adaptive_threshold: آستانه فعلی (تطبیقی یا fallback)
      adaptive_fallback:  آستانه ثابت از کانفیگ (full_at)
      adaptive_samples:   تعداد مشاهدات در score_history
      adaptive_enabled:   آیا normalizer فعال است؟
      adaptive_mode:      آیا در حالت تطبیقی است (samples ≥ min_samples)؟
    """

    def _enrich_factors_adaptive(self, data: dict) -> dict:
        """افزودن فیلدهای آستانه تطبیقی به هر فاکتور در payload."""
        norm = self.normalizer
        engines = data.get("engines", {})
        if not isinstance(engines, dict):
            return data

        for side in ("sell", "buy"):
            side_data = engines.get(side, {})
            if not isinstance(side_data, dict):
                continue
            factors = side_data.get("factors", [])
            side_norm = self.cfg.get(f"{side}_pressure", {}).get("norm", {})

            for f in factors:
                if not isinstance(f, dict) or not f.get("name"):
                    continue
                fname = f["name"]
                fb = side_norm.get(fname, {}).get("full_at")
                if fb is None:
                    continue

                if norm is None:
                    # normalizer وجود ندارد → فقط fallback
                    f["adaptive_threshold"] = round(fb, 4)
                    f["adaptive_fallback"] = fb
                    f["adaptive_samples"] = 0
                    f["adaptive_enabled"] = False
                    f["adaptive_mode"] = False
                    continue

                try:
                    count = norm.storage.get_score_history_count(self.symbol, fname)
                except Exception:
                    count = 0
                threshold = norm.get_threshold(self.symbol, fname, fb)
                f["adaptive_threshold"] = round(threshold, 4)
                f["adaptive_fallback"] = fb
                f["adaptive_samples"] = count
                f["adaptive_enabled"] = norm.enabled
                f["adaptive_mode"] = bool(norm.enabled and count >= norm.min_samples)

        return data

    def payload(self) -> dict:
        """payload اصلی + غنی‌سازی آستانه تطبیقی."""
        data = super().payload()
        if not data.get("ok"):
            return data
        data = self._enrich_factors_adaptive(data)
        # بنر وضعیت adaptive (برای نمایش در داشبورد در آینده)
        norm = self.normalizer
        data["adaptive"] = {
            "enabled": bool(norm.enabled) if norm else False,
            "min_samples": norm.min_samples if norm else 0,
            "percentile": norm.percentile if norm else 0,
            "symbol": self.symbol,
        }
        return data


# ===========================================================================
# فاز شبیه‌سازی — پخش داده‌های ذخیره‌شده در بانک با کنترل سرعت و پرش
# ===========================================================================

class SimulationAdaptiveMonitor(AdaptiveLiveMonitor):
    """حالت شبیه‌سازی: پخش snapshotهای ذخیره‌شده در بانک با کنترل تعاملی.

    به‌جای دریافت لایو از TSETMC، snapshotهای یک نماد + یک تاریخ از بانک
    SQLite بارگذاری می‌شوند. موتورهای تحلیلی یک‌بار روی همه اجرا می‌شوند
    (pre-compute) تا پرش جلو/عقب فوری باشد. سپس با سرعت قابل‌تنظیم پخش
    می‌شوند با کنترل play/pause/step/seek.
    """

    def __init__(self, cfg, symbol, date_jalali, db_path,
                 time_speed=10.0, interval=1, normalizer=None, storage=None):
        super().__init__(cfg, mode="simulation", symbol=symbol,
                        interval=interval, normalizer=normalizer, storage=storage)
        self._sim_date = date_jalali
        self._sim_speed = float(time_speed)
        self._sim_playing = True
        self._sim_index = 0
        self._sim_snaps: list[MarketSnapshot] = []
        self._sim_results: list = []       # (sell_res, buy_res, combined)
        self._sim_trades_by_time: dict[str, list[Trade]] = {}
        self._load_and_precompute()

    def _load_and_precompute(self):
        """بارگذاری snapshotهای نماد + تاریخ از بانک و pre-compute موتورها."""
        # پشتیبانی از هر دو فرمت تاریخ (slash و dash)
        dates = {self._sim_date}
        dates.add(self._sim_date.replace("/", "-"))
        dates.add(self._sim_date.replace("-", "/"))

        rows = self.storage.get_snapshots_for_symbol(self.symbol) if self.storage else []
        snaps = [MarketSnapshot.from_flat_dict(r) for r in rows
                 if r.get("date_jalali") in dates]
        snaps.sort(key=lambda s: s.timestamp)
        self._sim_snaps = snaps

        # بارگذاری معاملات (گروه‌بندی بر اساس trade_time)
        if self.storage:
            trade_rows = self.storage.get_trades_for_symbol(self.symbol)
            for t in trade_rows:
                tt = t.get("trade_time", "")
                if tt:
                    self._sim_trades_by_time.setdefault(tt, []).append(
                        Trade(trade_time=tt,
                              trade_price=float(t.get("trade_price") or 0),
                              trade_volume=int(t.get("trade_volume") or 0),
                              trade_id=t.get("trade_id"),
                              aggressor_side=t.get("aggressor_side")))

        # pre-compute: اجرای موتورها روی همه‌ی snapshotها (detectorهای تازه)
        sp_det = SellPressureDetector(self.cfg, normalizer=self.normalizer)
        buy_det = BuyPressureDetector(self.cfg, normalizer=self.normalizer)
        alert_eng = AlertEngine(self.cfg)
        prev = None
        hist: list[MarketSnapshot] = []
        for snap in snaps:
            sp = sp_det.evaluate(snap, prev)
            buy = buy_det.evaluate(snap, prev, hist)
            combined = alert_eng.evaluate(sp, buy) if (sp and buy) else None
            self._sim_results.append((sp, buy, combined))
            # ثبت raw_values برای نرمال‌سازی تطبیقی
            if self.normalizer:
                if sp:
                    self.normalizer.record_factors(snap.symbol, "sell", sp.factors,
                                                   date_jalali=self._sim_date)
                if buy:
                    self.normalizer.record_factors(snap.symbol, "buy", buy.factors,
                                                   date_jalali=self._sim_date)
            prev = snap
            hist.append(snap)

        print(f"  شبیه‌سازی: {len(snaps)} نمونه برای «{self.symbol}» در تاریخ {self._sim_date}")

        # انتشار اولین نمونه برای نمایش فوری
        if snaps:
            self._publish_sim_rebuild()

    def start(self):
        """شروع حلقه‌ی پخش در پس‌زمینه."""
        self._thread = threading.Thread(target=self._loop_sim, daemon=True,
                                         name="sim-monitor")
        self._thread.start()

    def _loop_sim(self):
        """حلقه‌ی پخش: پیشبرد index بر اساس سرعت و وضعیت play/pause."""
        while not self._stop.is_set():
            if self._sim_playing and self._sim_index < len(self._sim_snaps) - 1:
                self._sim_index += 1
                self._publish_sim_forward()
            wait = self.interval / max(self._sim_speed, 0.1)
            self._stop.wait(wait)

    def _publish_sim_forward(self):
        """پیشروی طبیعی: فقط snapshot جاری را به history اضافه کن."""
        idx = self._sim_index
        if idx >= len(self._sim_snaps):
            return
        snap = self._sim_snaps[idx]
        trades = self._sim_trades_by_time.get(snap.tehran_time, [])
        with self._lock:
            self.history.append(snap)
            for tr in trades:
                self.recent_trades.append(tr)
            self.last_fetch_time = datetime.now().isoformat(timespec="seconds")
            self.last_error = ""

    def _publish_sim_rebuild(self):
        """پس از پرش: history را تا index فعلی بازسازی کن."""
        idx = self._sim_index
        if idx >= len(self._sim_snaps):
            return
        with self._lock:
            self.history.clear()
            start = max(0, idx - 299)
            for s in self._sim_snaps[start:idx + 1]:
                self.history.append(s)
            snap = self._sim_snaps[idx]
            trades = self._sim_trades_by_time.get(snap.tehran_time, [])
            self.recent_trades.clear()
            for tr in trades:
                self.recent_trades.append(tr)
            self.last_fetch_time = datetime.now().isoformat(timespec="seconds")
            self.last_error = ""
        # در شبیه‌سازی چیزی در بانک نوشته نمی‌شود (فقط خوانده می‌شود)

    def _engine_output(self, hist):
        """استفاده از نتایج pre-computed به‌جای اجرای مجدد موتورها."""
        if not self._sim_results or self._sim_index >= len(self._sim_results):
            return {"available": False}
        idx = self._sim_index
        sp, buy, combined = self._sim_results[idx]
        # امتیاز تجمعی = مجموع امتیازها تا این موقعیت
        cum_sell = sum(r[0].total_score for r in self._sim_results[:idx + 1] if r[0])
        cum_buy = sum(r[1].total_score for r in self._sim_results[:idx + 1] if r[1])
        return {
            "available": True,
            "sell": sp.to_dict() if sp else None,
            "buy": buy.to_dict() if buy else None,
            "combined": combined.to_dict() if combined else None,
            "sell_tier": tier(sp.total_score) if sp else "نامشخص",
            "buy_tier": tier(buy.total_score) if buy else "نامشخص",
            "classification": classify(
                sp.total_score if sp else None,
                buy.total_score if buy else None,
            ),
            "cumulative_sell_score": round(cum_sell, 1),
            "cumulative_buy_score": round(cum_buy, 1),
            "cumulative_samples": idx + 1,
        }

    # --- کنترل‌های تعاملی ---

    def sim_play(self):
        self._sim_playing = True

    def sim_pause(self):
        self._sim_playing = False

    def sim_set_speed(self, speed):
        self._sim_speed = max(0.1, float(speed))

    def sim_step(self, n):
        """پرش n نمونه جلو (مثبت) یا عقب (منفی)."""
        self._sim_index = max(0, min(len(self._sim_snaps) - 1, self._sim_index + n))
        self._publish_sim_rebuild()

    def sim_seek(self, idx):
        """پرش مستقیم به موقعیت idx."""
        self._sim_index = max(0, min(len(self._sim_snaps) - 1, int(idx)))
        self._publish_sim_rebuild()

    def sim_status(self) -> dict:
        return {
            "mode": "simulation",
            "symbol": self.symbol,
            "date": self._sim_date,
            "index": self._sim_index,
            "total": len(self._sim_snaps),
            "playing": self._sim_playing,
            "speed": self._sim_speed,
            "current_time": self._sim_snaps[self._sim_index].tehran_time
                            if self._sim_snaps and self._sim_index < len(self._sim_snaps) else "",
        }


# ---------------------------------------------------------------------------
# Flask app تازه با مسیرهای تطبیقی + مسیرهای اصلی
# ---------------------------------------------------------------------------

app = Flask(__name__)
MONITOR: AdaptiveLiveMonitor | None = None


@app.route("/")
def index():
    return HTML_PAGE_ADAPTIVE


@app.route("/api/live")
def api_live():
    if MONITOR is None:
        return jsonify({"ok": False, "message": "مانیتور راه‌اندازی نشده است"}), 500
    return jsonify(MONITOR.payload())


@app.route("/range-rules")
def range_rules_editor():
    """صفحه ویرایش درصد نوسان مجاز — همان نسخه اصلی."""
    return orig.range_rules_editor()


@app.route("/range-rules/save", methods=["POST"])
def range_rules_save():
    """ذخیره درصد نوسان مجاز — همان نسخه اصلی."""
    return orig.range_rules_save()


# ===========================================================================
# مسیرهای فاز شبیه‌سازی
# ===========================================================================

SYMBOLS_PATH = ROOT / "config" / "symbols.json"


def _load_symbols_list() -> list[dict]:
    """بارگذاری لیست نمادها از config/symbols.json."""
    try:
        with open(SYMBOLS_PATH, encoding="utf-8") as f:
            return json.load(f).get("symbols", [])
    except Exception:
        return []


@app.route("/sim")
def sim_setup():
    """فرم انتخاب نماد، تاریخ و سرعت برای شروع شبیه‌سازی."""
    symbols = _load_symbols_list()
    opts = "\n".join(
        f'<option value="{s["name"]}">{s["name"]} — {s.get("market_label", "")}</option>'
        for s in symbols
    )
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>شبیه‌سازی — TSE Early Warning</title>
<style>
  body {{ font-family: 'Vazirmatn', Tahoma, sans-serif; background: #f5f5f5; margin: 0; padding: 20px; }}
  .card {{ max-width: 560px; margin: 40px auto; background: #fff; border-radius: 12px;
           padding: 28px; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
  h1 {{ font-size: 22px; color: #1a237e; margin: 0 0 6px; }}
  .sub {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
  label {{ display: block; font-size: 14px; font-weight: 600; margin: 16px 0 6px; color: #333; }}
  select, input {{ width: 100%; padding: 10px 12px; border: 1px solid #ccc; border-radius: 8px;
                   font-size: 15px; box-sizing: border-box; }}
  button {{ margin-top: 24px; width: 100%; padding: 14px; background: #1a237e; color: #fff;
            border: none; border-radius: 8px; font-size: 17px; font-weight: 700; cursor: pointer; }}
  button:hover {{ background: #283593; }}
  button:disabled {{ background: #999; }}
  .hint {{ font-size: 13px; color: #888; margin-top: 12px; }}
  #msg {{ margin-top: 12px; font-size: 14px; }}
</style>
</head>
<body>
<div class="card">
  <h1>▶ شبیه‌سازی روز معاملاتی</h1>
  <div class="sub">داده‌های ذخیره‌شده در بانک را با سرعت دلخواه پخش کنید — بدون نیاز به بازار باز.</div>

  <label>نماد</label>
  <select id="symbol" onchange="loadDates()">
    <option value="">— انتخاب کنید —</option>
    {opts}
  </select>

  <label>تاریخ (روز معاملاتی ذخیره‌شده)</label>
  <select id="date" disabled>
    <option value="">— ابتدا نماد را انتخاب کنید —</option>
  </select>

  <label>سرعت گذر زمان (برابر)</label>
  <input type="number" id="speed" value="10" min="0.5" max="200" step="0.5">
  <div class="hint">مثلاً ۱۰ یعنی ۱۰ برابر سریع‌تر از زمان واقعی. کل ۳.۵ ساعت در ~۲۱ دقیقه.</div>

  <button id="startBtn" onclick="startSim()" disabled>شروع شبیه‌سازی ▶</button>
  <div id="msg"></div>
</div>
<script>
async function loadDates() {{
  const sym = document.getElementById('symbol').value;
  const dateSel = document.getElementById('date');
  const btn = document.getElementById('startBtn');
  dateSel.innerHTML = '<option value="">— در حال بارگذاری... —</option>';
  dateSel.disabled = true;
  btn.disabled = true;
  if (!sym) {{
    dateSel.innerHTML = '<option value="">— ابتدا نماد را انتخاب کنید —</option>';
    return;
  }}
  try {{
    const r = await fetch('/api/sim/dates?symbol=' + encodeURIComponent(sym));
    const dates = await r.json();
    if (!dates.length) {{
      dateSel.innerHTML = '<option value="">— داده‌ای برای این نماد نیست —</option>';
      document.getElementById('msg').textContent = 'برای این نماد snapshotی در بانک نیست. ابتدا با run_multi.py داده جمع کنید.';
      return;
    }}
    dateSel.innerHTML = dates.map(d => '<option value="' + d + '">' + d + '</option>').join('');
    dateSel.disabled = false;
    btn.disabled = false;
    document.getElementById('msg').textContent = '';
  }} catch(e) {{
    dateSel.innerHTML = '<option value="">— خطا —</option>';
  }}
}}
async function startSim() {{
  const symbol = document.getElementById('symbol').value;
  const date = document.getElementById('date').value;
  const speed = parseFloat(document.getElementById('speed').value) || 10;
  const msg = document.getElementById('msg');
  msg.textContent = 'در حال بارگذاری...';
  msg.style.color = '#666';
  try {{
    const r = await fetch('/api/sim/start', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{symbol, date, speed}})
    }});
    const d = await r.json();
    if (d.ok) {{
      window.location.href = '/';
    }} else {{
      msg.textContent = d.message || 'خطا در شروع';
      msg.style.color = '#c62828';
    }}
  }} catch(e) {{
    msg.textContent = 'خطا: ' + e.message;
    msg.style.color = '#c62828';
  }}
}}
</script>
</body>
</html>"""


@app.route("/api/sim/dates")
def sim_dates():
    """لیست تاریخ‌های موجود برای یک نماد در بانک."""
    symbol = request.args.get("symbol", "")
    db_path = ROOT / "data" / "multi" / f"{symbol}.sqlite"
    if not db_path.exists():
        return jsonify([])
    try:
        storage = MarketDataStorage(db_path)
        rows = storage.conn.execute(
            "SELECT DISTINCT date_jalali FROM snapshots WHERE symbol=? "
            "ORDER BY date_jalali DESC", (symbol,)).fetchall()
        storage.close()
        return jsonify([r[0] for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sim/start", methods=["POST"])
def sim_start():
    """شروع شبیه‌سازی: ساخت SimulationAdaptiveMonitor با پارامترهای کاربر."""
    global MONITOR
    data = request.get_json(force=True)
    symbol = data.get("symbol", "")
    date_jalali = data.get("date", "")
    speed = float(data.get("speed", 10))
    if not symbol or not date_jalali:
        return jsonify({"ok": False, "message": "نماد و تاریخ الزامی است"}), 400

    db_path = ROOT / "data" / "multi" / f"{symbol}.sqlite"
    if not db_path.exists():
        return jsonify({"ok": False, "message": f"بانک {db_path.name} وجود ندارد"}), 404

    # توقف مانیتور قبلی
    if MONITOR is not None:
        try:
            MONITOR.stop()
        except Exception:
            pass

    try:
        cfg = load_cfg()
        storage = MarketDataStorage(db_path)
        normalizer = AdaptiveNormalizer(storage, cfg)
        MONITOR = SimulationAdaptiveMonitor(
            cfg, symbol=symbol, date_jalali=date_jalali, db_path=db_path,
            time_speed=speed, normalizer=normalizer, storage=storage,
        )
        MONITOR.start()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/sim/play", methods=["POST"])
def sim_play_route():
    if MONITOR and isinstance(MONITOR, SimulationAdaptiveMonitor):
        MONITOR.sim_play()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "message": "شبیه‌سازی فعال نیست"}), 400


@app.route("/api/sim/pause", methods=["POST"])
def sim_pause_route():
    if MONITOR and isinstance(MONITOR, SimulationAdaptiveMonitor):
        MONITOR.sim_pause()
        return jsonify({"ok": True})
    return jsonify({"ok": False, "message": "شبیه‌سازی فعال نیست"}), 400


@app.route("/api/sim/speed", methods=["POST"])
def sim_speed_route():
    if MONITOR and isinstance(MONITOR, SimulationAdaptiveMonitor):
        speed = float(request.get_json(force=True).get("speed", 10))
        MONITOR.sim_set_speed(speed)
        return jsonify({"ok": True, "speed": speed})
    return jsonify({"ok": False, "message": "شبیه‌سازی فعال نیست"}), 400


@app.route("/api/sim/step", methods=["POST"])
def sim_step_route():
    if MONITOR and isinstance(MONITOR, SimulationAdaptiveMonitor):
        n = int(request.get_json(force=True).get("n", 10))
        MONITOR.sim_step(n)
        return jsonify({"ok": True, "index": MONITOR._sim_index})
    return jsonify({"ok": False, "message": "شبیه‌سازی فعال نیست"}), 400


@app.route("/api/sim/seek", methods=["POST"])
def sim_seek_route():
    if MONITOR and isinstance(MONITOR, SimulationAdaptiveMonitor):
        idx = int(request.get_json(force=True).get("index", 0))
        MONITOR.sim_seek(idx)
        return jsonify({"ok": True, "index": MONITOR._sim_index})
    return jsonify({"ok": False, "message": "شبیه‌سازی فعال نیست"}), 400


@app.route("/api/sim/status")
def sim_status_route():
    if MONITOR and isinstance(MONITOR, SimulationAdaptiveMonitor):
        return jsonify(MONITOR.sim_status())
    return jsonify({"mode": "not_simulation"})


# ---------------------------------------------------------------------------
# main — مشابه نسخه اصلی اما با AdaptiveLiveMonitor
# ---------------------------------------------------------------------------

def main():
    global MONITOR
    ap = argparse.ArgumentParser(
        description="داشبورد زنده تطبیقی (Phase 2.1) — نمایش ستون آستانه تطبیقی"
    )
    ap.add_argument("--mode", choices=["live", "demo", "simulation"], default="live",
                    help="حالت: live=TSETMC واقعی، demo=شبیه‌ساز آفلاین، simulation=پخش از بانک")
    ap.add_argument("--scenario", choices=["normal", "sell_pressure", "accumulation", "mixed"],
                    default="sell_pressure", help="سناریوی شبیه‌ساز در حالت demo")
    ap.add_argument("--symbol", default=None, help="نام نماد (پیش‌فرض: پیکربندی)")
    ap.add_argument("--ins-code", default=None, help="کد TSETMC نماد")
    ap.add_argument("--interval", type=int, default=None, help="فاصله نمونه‌برداری (ثانیه)")
    ap.add_argument("--samples", type=int, default=226, help="تعداد نمونه شبیه‌ساز (حالت demo)")
    ap.add_argument("--date", default=None,
                    help="تاریخ شمسی برای شبیه‌سازی (مثلاً 1404/08/28) — با --mode simulation")
    ap.add_argument("--time-speed", type=float, default=10.0,
                    help="سرعت گذر زمان در شبیه‌سازی (مثلاً 10 = ۱۰ برابر) — با --mode simulation")
    ap.add_argument("--db", default=None,
                    help="مسیر فایل SQLite (پیش‌فرض: data/multi/{symbol}.sqlite اگر نماد داده شده)")
    ap.add_argument("--port", type=int, default=8052)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    # اگر --db داده نشده و --symbol مشخص است، از data/multi/{symbol}.sqlite استفاده کن
    # (همان DB که run_live.py/run_multi در آن ذخیره می‌کند — برای خواندن نمونه‌های
    # ابتدای روز حتی قبل از استارت داشبورد)
    if args.db is None:
        if args.symbol:
            args.db = f"data/multi/{args.symbol}.sqlite"
        else:
            args.db = "data/early_warning_live.sqlite"

    cfg = load_cfg()
    print(f"پیکربندی بارگذاری شد - نماد پیش‌فرض: {cfg['test_symbol']['name']}")
    print(f"adaptive.enabled = {cfg.get('adaptive', {}).get('enabled', False)}")

    if args.mode == "live" and args.symbol and not args.ins_code:
        print(f"جستجوی کد نماد '{args.symbol}' در TSETMC...")
        tmp = MarketDataCollector(cfg)
        res = tmp.search_symbol(args.symbol)
        if res:
            args.ins_code = res[0]["code"]
            print(f"کد پیدا شد: {args.ins_code}")
        else:
            print(f"نماد '{args.symbol}' پیدا نشد - از کد پیکربندی استفاده می‌شود.")

    live_storage = None
    live_normalizer = None

    if args.mode == "simulation":
        # حالت شبیه‌سازی: اگر --symbol و --date داده شده، خودکار شروع کن؛
        # در غیر این صورت، کاربر از صفحه‌ی /sim استفاده می‌کند.
        if args.symbol and args.date:
            db_path = ROOT / args.db
            if db_path.exists():
                try:
                    live_storage = MarketDataStorage(db_path)
                    live_normalizer = AdaptiveNormalizer(live_storage, cfg)
                    MONITOR = SimulationAdaptiveMonitor(
                        cfg, symbol=args.symbol, date_jalali=args.date,
                        db_path=db_path, time_speed=args.time_speed,
                        normalizer=live_normalizer, storage=live_storage,
                    )
                    MONITOR.start()
                except Exception as e:
                    print(f"  ⚠ خطا در شروع شبیه‌سازی: {e}")
                    print(f"  → از صفحه‌ی /sim برای شروع دستی استفاده کنید.")
            else:
                print(f"  ⚠ بانک {db_path} وجود ندارد.")
                print(f"  → از صفحه‌ی /sim برای انتخاب نماد/تاریخ استفاده کنید.")
        else:
            print("  → بدون --symbol و --date: از صفحه‌ی /sim برای شروع شبیه‌سازی استفاده کنید.")
    else:
        sym_final = args.symbol or cfg.get("test_symbol", {}).get("name", "")
        ins_final = args.ins_code or cfg.get("test_symbol", {}).get("ins_code", "")
        if args.mode == "live" and sym_final:
            db_path = ROOT / args.db
            try:
                live_storage = MarketDataStorage(db_path)
                load_price_range_live(cfg, sym_final, ins_final, storage=live_storage)
                live_normalizer = AdaptiveNormalizer(live_storage, cfg)
            except Exception as e:
                print(f"  ⚠ خطا در ایجاد storage: {e}")
                print(f"  ⚠ daily_params/score_history ذخیره نمی‌شود اما داشبورد ادامه می‌دهد.")
                load_price_range_live(cfg, sym_final, ins_final)

        MONITOR = AdaptiveLiveMonitor(
            cfg,
            mode=args.mode,
            symbol=args.symbol,
            ins_code=args.ins_code,
            interval=args.interval,
            scenario=args.scenario,
            samples=args.samples,
            normalizer=live_normalizer,
            storage=live_storage,
        )
        MONITOR.start()

    src = ("TSETMC زنده" if args.mode == "live"
           else f"شبیه‌ساز (سناریو: {args.scenario})" if args.mode == "demo"
           else "شبیه‌سازی (پخش از بانک)")
    print("=" * 60)
    print("داشبورد رصد زنده تطبیقی — Phase 2.1 (ستون آستانه تطبیقی)")
    print(f"منبع داده : {src}")
    if MONITOR:
        print(f"نماد      : {MONITOR.symbol}")
    if args.mode == "simulation" and MONITOR:
        sm = MONITOR
        print(f"تاریخ     : {sm._sim_date}")
        print(f"نمونه‌ها   : {len(sm._sim_snaps)} (سرعت {sm._sim_speed}x)")
    elif MONITOR:
        print(f"نمونه‌برداری: هر {MONITOR.interval} ثانیه")
    if args.mode == "simulation":
        print(f"صفحه‌ی انتخاب: http://localhost:{args.port}/sim")
    if live_storage:
        print(f"بانک       : {ROOT / args.db}")
    adp = cfg.get("adaptive", {})
    status = "فعال" if adp.get("enabled") else "غیرفعال (fallback ثابت)"
    print(f"adaptive  : {status} (min_samples={adp.get('min_samples',50)}, percentile={adp.get('percentile',90)})")
    print(f"آدرس      : http://localhost:{args.port}")
    print("=" * 60)

    try:
        app.run(host=args.host, port=args.port, threaded=True, debug=False, use_reloader=False)
    finally:
        if live_storage:
            try:
                live_storage.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
