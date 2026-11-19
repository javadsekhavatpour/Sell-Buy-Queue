"""
web_dashboard_adaptive.py — داشبورد واحد TSE Early Warning

یک سرور، سه حالت با مسیرهای /live، /db، /sim:

  /        → صفحه‌ی نمایه (انتخاب حالت + نماد)
  /live    → داده از TSETMC زنده → نمایش + ذخیره در بانک (بررسی بصری جمع‌آوری)
  /db      → خواندن لحظه‌ای آخرین داده از بانک (بررسی بصری داده‌های ذخیره‌شده)
  /sim     → پخش داده‌های بانک با کنترل play/pause/speed/step (رفع اشکال بازار بسته)
  /sim/select → فرم انتخاب نماد/تاریخ/سرعت برای شبیه‌سازی

جمع‌آوری داده (پس‌زمینه، جدا از داشبورد):
  python run_multi.py --symbols دابور

اجرا:
  python web_dashboard_adaptive.py --port 8052
  سپس: http://localhost:8052/  → /live  /db  /sim

این فایل مؤلفه‌های پایه را از web_dashboard_live.py (در ریشه) وارد می‌کند و
یک زیرکلاس AdaptiveLiveMonitor با ستون «آستانه تطبیقی» می‌سازد.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request

# مؤلفه‌های نسخه اصلی — web_dashboard_live.py در ریشه (داخلی، مستقیم اجرا نمی‌شود)
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


class DBLiveMonitor(AdaptiveLiveMonitor):
    """حالت بانک: خواندن لحظه‌ای آخرین داده از بانک (بدون TSETMC).

    وقتی run_multi.py در پس‌زمینه داده جمع می‌کند، این داشبورد آخرین
    snapshot ذخیره‌شده را هر interval ثانیه می‌خواند و نمایش می‌دهد —
    برای بررسی بصری صحت داده‌های ذخیره‌شده. هیچ فراخوانی TSETMC انجام
    نمی‌شود و چیزی در بانک نوشته نمی‌شود (فقط خوانده می‌شود).
    """

    def __init__(self, cfg, symbol, interval=5, normalizer=None, storage=None):
        super().__init__(cfg, mode="db", symbol=symbol,
                        interval=interval, normalizer=normalizer, storage=storage)

    def start(self):
        self._thread = threading.Thread(target=self._loop_db, daemon=True,
                                         name="db-monitor")
        self._thread.start()

    def _loop_db(self):
        """خواندن آخرین snapshot از بانک هر interval ثانیه."""
        prev: MarketSnapshot | None = None
        while not self._stop.is_set():
            try:
                if self.storage:
                    row = self.storage.get_last_snapshot(self.symbol)
                    if row:
                        snap = MarketSnapshot.from_flat_dict(row)
                        # معاملات این لحظه
                        trades: list[Trade] = []
                        for t in self.storage.get_trades_for_symbol(self.symbol):
                            if t.get("trade_time") == snap.tehran_time:
                                trades.append(Trade(
                                    trade_time=t.get("trade_time", ""),
                                    trade_price=float(t.get("trade_price") or 0),
                                    trade_volume=int(t.get("trade_volume") or 0),
                                    trade_id=t.get("trade_id"),
                                    aggressor_side=t.get("aggressor_side")))
                        self._publish(snap, trades)
                        prev = snap
            except Exception as e:
                with self._lock:
                    self.last_error = f"خطای خواندن از بانک: {e}"
                    self.last_fetch_time = datetime.now().isoformat(timespec="seconds")
            self._stop.wait(self.interval)


# ===========================================================================
# داشبورد واحد: switch_mode + صفحه‌ی نمایه
#
# سه حالت با مسیرهای /live، /db، /sim — یک سرور، یک فایل.
#   /live → TSETMC زنده → نمایش + بانک
#   /db   → خواندن لحظه‌ای آخرین داده از بانک
#   /sim  → پخش داده‌های بانک با کنترل
# ===========================================================================

_switch_lock = threading.Lock()
_current_mode: str | None = None      # "live" | "db" | "sim" | None
_current_symbol: str | None = None
_current_storage: MarketDataStorage | None = None


def _default_symbol() -> str:
    cfg = load_cfg()
    return cfg.get("test_symbol", {}).get("name", "ریتون")


def _latest_date_in_db(storage: MarketDataStorage, symbol: str) -> str:
    try:
        row = storage.conn.execute(
            "SELECT date_jalali FROM snapshots WHERE symbol=? "
            "ORDER BY timestamp DESC LIMIT 1", (symbol,)).fetchone()
        return row[0] if row else ""
    except Exception:
        return ""


def switch_mode(mode: str, symbol: str | None = None, date: str | None = None,
                speed: float = 10.0, interval: int = 30) -> dict:
    """توقف مانیتور قبلی و شروع مانیتور جدید برای حالت درخواستی.

    خروجی: {"ok": True/False, "mode", "symbol", "message"?}
    """
    global MONITOR, _current_mode, _current_symbol, _current_storage
    cfg = load_cfg()
    symbol = symbol or _default_symbol()
    with _switch_lock:
        # اگر همین حالت + نماد فعالی است، نیاز به تعویض نیست (مگر sim با تاریخ متفاوت)
        if (_current_mode == mode and _current_symbol == symbol and MONITOR is not None
                and not (mode == "sim" and date)):
            return {"ok": True, "mode": mode, "symbol": symbol, "switched": False}

        # توقف مانیتور قبلی
        if MONITOR is not None:
            try:
                MONITOR.stop()
            except Exception:
                pass
            MONITOR = None
            time.sleep(0.4)  # به thread وقت بده تمیز جمع شود

        # بستن storage قبلی
        if _current_storage is not None:
            try:
                _current_storage.close()
            except Exception:
                pass
            _current_storage = None

        try:
            db_path = ROOT / "data" / "multi" / f"{symbol}.sqlite"

            if mode == "live":
                ins_code = cfg.get("test_symbol", {}).get("ins_code", "")
                if symbol and not ins_code:
                    print(f"جستجوی کد نماد '{symbol}' در TSETMC...")
                    tmp = MarketDataCollector(cfg)
                    res = tmp.search_symbol(symbol)
                    if res:
                        ins_code = res[0]["code"]
                        print(f"کد پیدا شد: {ins_code}")
                storage = MarketDataStorage(db_path)
                load_price_range_live(cfg, symbol, ins_code, storage=storage)
                normalizer = AdaptiveNormalizer(storage, cfg)
                MONITOR = AdaptiveLiveMonitor(
                    cfg, mode="live", symbol=symbol, ins_code=ins_code,
                    interval=interval, normalizer=normalizer, storage=storage)
                _current_storage = storage

            elif mode == "db":
                if not db_path.exists():
                    return {"ok": False,
                            "message": f"بانک {db_path.name} وجود ندارد. "
                                       f"ابتدا با run_multi.py داده جمع کنید."}
                storage = MarketDataStorage(db_path)
                normalizer = AdaptiveNormalizer(storage, cfg)
                MONITOR = DBLiveMonitor(
                    cfg, symbol=symbol, interval=5,
                    normalizer=normalizer, storage=storage)
                _current_storage = storage

            elif mode == "sim":
                if not db_path.exists():
                    return {"ok": False,
                            "message": f"بانک {db_path.name} وجود ندارد. "
                                       f"ابتدا با run_multi.py داده جمع کنید."}
                storage = MarketDataStorage(db_path)
                normalizer = AdaptiveNormalizer(storage, cfg)
                if not date:
                    date = _latest_date_in_db(storage, symbol)
                if not date:
                    return {"ok": False,
                            "message": f"داده‌ای برای نماد '{symbol}' در بانک نیست."}
                MONITOR = SimulationAdaptiveMonitor(
                    cfg, symbol=symbol, date_jalali=date, db_path=db_path,
                    time_speed=speed, normalizer=normalizer, storage=storage)
                _current_storage = storage

            else:
                return {"ok": False, "message": f"حالت نامعتبر: {mode}"}

            MONITOR.start()
            _current_mode = mode
            _current_symbol = symbol
            return {"ok": True, "mode": mode, "symbol": symbol, "switched": True,
                    "date": date if mode == "sim" else None}
        except Exception as e:
            _current_mode = None
            return {"ok": False, "message": f"خطا در شروع حالت {mode}: {e}"}


def _index_page_html() -> str:
    """صفحه‌ی نمایه: سه دکمه برای /live، /db، /sim + انتخاب نماد."""
    symbols = _load_symbols_list()
    opts = "\n".join(
        f'<option value="{s["name"]}">{s["name"]} — {s.get("market_label", "")}</option>'
        for s in symbols) or '<option value="">— ابتدا در config/symbols.json نماد اضافه کنید —</option>'
    cur = _default_symbol()
    mode_label = {"live": "زنده (Live)", "db": "بانک (DB)", "sim": "شبیه‌سازی (Sim)"}
    cur_label = mode_label.get(_current_mode, "هیچ (انتخاب کنید)")
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>داشبورد TSE Early Warning</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: 'Vazirmatn', Tahoma, sans-serif; background: #f5f5f5;
          margin: 0; padding: 20px; }}
  .wrap {{ max-width: 720px; margin: 30px auto; }}
  h1 {{ font-size: 24px; color: #1a237e; margin: 0 0 6px; }}
  .sub {{ color: #666; font-size: 14px; margin-bottom: 24px; }}
  .card {{ background: #fff; border-radius: 14px; padding: 24px;
           box-shadow: 0 2px 12px rgba(0,0,0,0.08); margin-bottom: 20px; }}
  label {{ display: block; font-size: 14px; font-weight: 600; margin-bottom: 6px; color: #333; }}
  select {{ width: 100%; padding: 11px 14px; border: 1px solid #ccc; border-radius: 8px;
            font-size: 16px; margin-bottom: 18px; }}
  .modes {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; }}
  .mode {{ display: block; text-decoration: none; padding: 22px 16px; border-radius: 12px;
           text-align: center; font-size: 18px; font-weight: 700; color: #fff;
           transition: transform 0.15s, box-shadow 0.15s; }}
  .mode:hover {{ transform: translateY(-2px); box-shadow: 0 4px 16px rgba(0,0,0,0.15); }}
  .mode .ico {{ font-size: 28px; display: block; margin-bottom: 6px; }}
  .mode .dsc {{ font-size: 12px; font-weight: 400; opacity: 0.9; margin-top: 4px; }}
  .live {{ background: #2e7d32; }}
  .db   {{ background: #1565c0; }}
  .sim  {{ background: #6a1b9a; }}
  .cur  {{ font-size: 13px; color: #888; margin-top: 14px; text-align: center; }}
  .cur b {{ color: #1a237e; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 داشبورد TSE Early Warning</h1>
  <div class="sub">یک سرور، سه حالت — حالت را از مسیر انتخاب کنید.</div>
  <div class="card">
    <label>نماد</label>
    <select id="symbol" onchange="updateLinks()">
      <option value="{cur}" selected>— پیش‌فرض: {cur} —</option>
      {opts}
    </select>
    <div class="modes">
      <a class="mode live" id="btn-live" href="/live">
        <span class="ico">📡</span> Live
        <span class="dsc">TSETMC زنده → نمایش + بانک</span>
      </a>
      <a class="mode db" id="btn-db" href="/db">
        <span class="ico">💾</span> DB
        <span class="dsc">آخرین داده از بانک</span>
      </a>
      <a class="mode sim" id="btn-sim" href="/sim">
        <span class="ico">▶</span> Sim
        <span class="dsc">پخش بانک با کنترل</span>
      </a>
    </div>
    <div class="cur">حالت فعلی: <b>{cur_label}</b>{f' — نماد {_current_symbol}' if _current_symbol else ''}</div>
  </div>
</div>
<script>
function updateLinks() {{
  const s = document.getElementById('symbol').value;
  document.getElementById('btn-live').href = '/live?symbol=' + encodeURIComponent(s);
  document.getElementById('btn-db').href   = '/db?symbol='   + encodeURIComponent(s);
  document.getElementById('btn-sim').href  = '/sim?symbol='  + encodeURIComponent(s);
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Flask app تازه با مسیرهای تطبیقی + مسیرهای اصلی
# ---------------------------------------------------------------------------

app = Flask(__name__)
MONITOR: AdaptiveLiveMonitor | None = None


@app.route("/")
def index():
    """صفحه‌ی نمایه: سه دکمه برای /live، /db، /sim."""
    return _index_page_html()


@app.route("/live")
def route_live():
    """حالت زنده: TSETMC → نمایش + بانک."""
    symbol = request.args.get("symbol") or _default_symbol()
    interval = int(request.args.get("interval", 30))
    res = switch_mode("live", symbol, interval=interval)
    if not res.get("ok"):
        return (_index_page_html() + f"<p style='color:#c62828;text-align:center'>"
                f"خطا: {res.get('message')}</p>"), 500
    return HTML_PAGE_ADAPTIVE


@app.route("/db")
def route_db():
    """حالت بانک: خواندن لحظه‌ای آخرین داده از بانک."""
    symbol = request.args.get("symbol") or _default_symbol()
    res = switch_mode("db", symbol)
    if not res.get("ok"):
        return (_index_page_html() + f"<p style='color:#c62828;text-align:center'>"
                f"خطا: {res.get('message')}</p>"), 500
    return HTML_PAGE_ADAPTIVE


@app.route("/api/live")
def api_live():
    if MONITOR is None:
        return jsonify({"ok": False, "message": "مانیتور راه‌اندازی نشده است — "
                         "به /live، /db یا /sim بروید."}), 500
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


def _sim_select_html(default_symbol: str | None = None) -> str:
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
      window.location.href = '/sim?symbol=' + encodeURIComponent(symbol) + '&date=' + encodeURIComponent(date);
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


@app.route("/sim")
def sim_route():
    """حالت شبیه‌سازی: پخش داده‌های بانک با کنترل.

    - با ?symbol=X&date=Y → مستقیم شبیه‌سازی را شروع کن و داشبورد نشان بده.
    - بدون پارامتر و sim فعال → داشبورد فعلی.
    - بدون پارامتر و sim فعال نیست → فرم انتخاب.
    """
    symbol = request.args.get("symbol") or _default_symbol()
    date = request.args.get("date")
    speed = float(request.args.get("speed", 10))
    # اگر sim همین نماد فعالی است و تاریخ جدید ندادیم → داشبورد
    if (_current_mode == "sim" and _current_symbol == symbol
            and not date and MONITOR is not None):
        return HTML_PAGE_ADAPTIVE
    res = switch_mode("sim", symbol, date=date, speed=speed)
    if res.get("ok"):
        return HTML_PAGE_ADAPTIVE
    # داده نبود → فرم انتخاب نشان بده
    return _sim_select_html(default_symbol=symbol)


@app.route("/sim/select")
def sim_select_route():
    """فرم انتخاب نماد/تاریخ/سرعت برای شبیه‌سازی."""
    return _sim_select_html()


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
    """شروع شبیه‌سازی از طریق فرم /sim/select — از switch_mode استفاده می‌کند."""
    data = request.get_json(force=True)
    symbol = data.get("symbol", "")
    date_jalali = data.get("date", "")
    speed = float(data.get("speed", 10))
    if not symbol or not date_jalali:
        return jsonify({"ok": False, "message": "نماد و تاریخ الزامی است"}), 400
    res = switch_mode("sim", symbol, date=date_jalali, speed=speed)
    if res.get("ok"):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "message": res.get("message", "خطا")}), 500


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
    """داشبورد واحد — یک سرور، سه حالت با مسیرهای /live، /db، /sim.

    دیگر نیازی به --mode نیست. حالت را از مسیر انتخاب کنید:
      http://localhost:PORT/        → صفحه‌ی نمایه (انتخاب حالت)
      http://localhost:PORT/live    → TSETMC زنده → نمایش + بانک
      http://localhost:PORT/db      → خواندن لحظه‌ای از بانک
      http://localhost:PORT/sim     → پخش بانک با کنترل
      http://localhost:PORT/sim/select → فرم انتخاب نماد/تاریخ/سرعت
    """
    ap = argparse.ArgumentParser(
        description="داشبورد واحد TSE Early Warning — /live، /db، /sim")
    ap.add_argument("--port", type=int, default=8052)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    cfg = load_cfg()
    adp = cfg.get("adaptive", {})
    status = "فعال" if adp.get("enabled") else "غیرفعال (fallback ثابت)"

    print("=" * 60)
    print("داشبورد واحد TSE Early Warning")
    print(f"نماد پیش‌فرض: {cfg.get('test_symbol', {}).get('name', 'ریتون')}")
    print(f"adaptive   : {status} (min_samples={adp.get('min_samples',50)}, percentile={adp.get('percentile',90)})")
    print("-" * 60)
    print("حالت را از مسیر انتخاب کنید:")
    print(f"  نمایه     : http://localhost:{args.port}/")
    print(f"  Live (زنده): http://localhost:{args.port}/live")
    print(f"  DB   (بانک): http://localhost:{args.port}/db")
    print(f"  Sim  (شبیه): http://localhost:{args.port}/sim")
    print(f"  فرم Sim    : http://localhost:{args.port}/sim/select")
    print("-" * 60)
    print("جمع‌آوری داده (پس‌زمینه): python run_multi.py --symbols <نماد>")
    print("=" * 60)

    try:
        app.run(host=args.host, port=args.port, threaded=True,
                debug=False, use_reloader=False)
    finally:
        # بستن storage اگر مانیتوری فعال است
        if _current_storage is not None:
            try:
                _current_storage.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()
