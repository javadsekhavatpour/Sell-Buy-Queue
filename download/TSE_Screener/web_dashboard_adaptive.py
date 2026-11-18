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
)

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


def _build_adaptive_html() -> str:
    """ساخت HTML تطبیقی با جایگزینی شش بخش از HTML_PAGE اصلی."""
    html = orig.HTML_PAGE
    misses = []
    for old, new, label in [
        (_OLD_CELL_BLOCK, _NEW_CELL_BLOCK, "cell"),
        (_OLD_HEADER, _NEW_HEADER, "header"),
        (_OLD_HINT, _NEW_HINT, "hint"),
        (_OLD_TICK_HEADER, _NEW_TICK_HEADER, "scoreHist"),
        (_OLD_CHART_TAIL, _NEW_CHART_TAIL, "chart-markers"),
        (_OLD_TICK_RENDER, _NEW_TICK_RENDER, "tick-hook"),
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


# ---------------------------------------------------------------------------
# main — مشابه نسخه اصلی اما با AdaptiveLiveMonitor
# ---------------------------------------------------------------------------

def main():
    global MONITOR
    ap = argparse.ArgumentParser(
        description="داشبورد زنده تطبیقی (Phase 2.1) — نمایش ستون آستانه تطبیقی"
    )
    ap.add_argument("--mode", choices=["live", "demo"], default="live",
                    help="حالت منبع داده: live=TSETMC واقعی، demo=شبیه‌ساز آفلاین")
    ap.add_argument("--scenario", choices=["normal", "sell_pressure", "accumulation", "mixed"],
                    default="sell_pressure", help="سناریوی شبیه‌ساز در حالت demo")
    ap.add_argument("--symbol", default=None, help="نام نماد (پیش‌فرض: پیکربندی)")
    ap.add_argument("--ins-code", default=None, help="کد TSETMC نماد")
    ap.add_argument("--interval", type=int, default=None, help="فاصله نمونه‌برداری (ثانیه)")
    ap.add_argument("--samples", type=int, default=226, help="تعداد نمونه شبیه‌ساز (حالت demo)")
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

    sym_final = args.symbol or cfg.get("test_symbol", {}).get("name", "")
    ins_final = args.ins_code or cfg.get("test_symbol", {}).get("ins_code", "")
    live_storage = None
    live_normalizer = None
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

    src = "TSETMC زنده" if args.mode == "live" else f"شبیه‌ساز (سناریو: {args.scenario})"
    print("=" * 60)
    print("داشبورد رصد زنده تطبیقی — Phase 2.1 (ستون آستانه تطبیقی)")
    print(f"منبع داده : {src}")
    print(f"نماد      : {MONITOR.symbol} (کد: {MONITOR.ins_code})")
    print(f"نمونه‌برداری: هر {MONITOR.interval} ثانیه")
    if live_storage:
        print(f"بانک       : {ROOT / args.db} (daily_params + score_history)")
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
