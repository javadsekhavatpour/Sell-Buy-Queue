#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
history_dashboard.py — محاسبهٔ شاخص‌های سابقهٔ روزانه برای داشبورد «سابقهٔ نمادها»

منبع داده: data/raw/history.sqlite (فقط دادهٔ خام TSETMC — history_collector.py)
فرمول‌ها: همان فرمول‌های export_portfoli_data.py؛ تنها تفاوت عمدی این است که
سابقهٔ حقیقی/حقوقی TSETMC «ارزش واقعی ریالی» (buy_I_Value/sell_I_Value) را می‌دهد،
پس ورود پول با ارزش واقعی حساب می‌شود — نسخهٔ بدون تقریبِ همان فرمول
(در لایو ارزش نداریم و (حجم × قیمت پایانی) استفاده می‌شود).

ستون‌های داشبورد سابقه (ترتیب درخواست کاربر) — همهٔ میانگین‌ها «وزنی»:
جمع تجمیعی اجزا روی پنجرهٔ روزهای قبل، نه میانگین سادهٔ مقادیر روزانه:

  close_price      قیمت پایانی
  pct_close        ٪ نوسان پایانی          = (پایانی − دیروز) ÷ دیروز × ۱۰۰
  flow_rial        ورود پول (ریال)        = خرید حقیقی − فروش حقیقی (ارزش واقعی TSE)
  flow_avg5_rial   میانگین وزنی ۵ روزه ورود پول = (Σ ارزش خرید − Σ ارزش فروش) ÷ تعداد روز
  flow_avg20_rial  میانگین وزنی ۲۰ روزه ورود پول = همان با ۲۰ روز قبل
  flow_avg30_rial  میانگین وزنی ۳۰ روزه ورود پول = همان با ۳۰ روز قبل
  trade_volume     حجم روز                  = qTotTran5J (کل حجم معاملات روز)
  vol_avg5         میانگین وزنی ۵ روزه حجم  = Σ حجم ÷ تعداد روز (پنجرهٔ کامل)
  vol_avg10        میانگین وزنی ۱۰ روزه حجم = همان با ۱۰ روز قبل
  vol_avg20        میانگین وزنی ۲۰ روزه حجم = همان با ۲۰ روز قبل
  vol_avg30        میانگین وزنی ۳۰ روزه حجم = همان با ۳۰ روز قبل
  buy_power        قدرت خرید روز            = علامت‌دار: (ارزش خرید ÷ تعداد خریداران) ÷
                                              (ارزش فروش ÷ تعداد فروشندگان)؛ نسبت < ۱ ← معکوس
                                              با علامت منفی (مثلاً ۰٫۸۴ ← ‎−۱٫۱۹)؛ مطلق همیشه ≥ ۱
  buy_power_avg5   میانگین وزنی قدرت خرید ۵ روز = (Σ ارزش خرید ÷ Σ خریداران) ÷
                                              (Σ ارزش فروش ÷ Σ فروشندگان) — بعد علامت‌دار
  buy_power_avg10  میانگین وزنی قدرت خرید ۱۰ روز = همان با ۱۰ روز قبل
  buy_power_avg20  میانگین وزنی قدرت خرید ۲۰ روز = همان با ۲۰ روز قبل
  buy_power_avg30  میانگین وزنی قدرت خرید ۳۰ روز = همان با ۳۰ روز قبل
  bs_count_ratio   تعداد خریدار به فروشنده  = buy_CountI ÷ sell_CountI
  real_buy_pct     درصد خرید حقیقی از کل    = ارزش خرید حقیقی ÷ ارزش کل × ۱۰۰
  reaction_pct     واکنش قیمت (٪)           = جای آخرین قیمت در بازهٔ کف تا سقف مجاز
                                             (کف/سقف = دیروز × (۱ ± pct) — price_range.py)
  (+ نسبت‌های درصدی قبلی mf5/mf30/vol5/vol30 در payload برای سازگاری حفظ شده‌اند)

بانک محاسباتی: نتیجهٔ همهٔ این ستون‌ها در data/raw/history_computed.sqlite
(جدا از بانک خام) ذخیره می‌شود — در لحظهٔ جمع‌آوری تاریخچه
(history_collector.py → refresh_computed) و بار اولِ هر بازخوانی؛ پس گزارش‌ها
و داشبورد به‌جای محاسبهٔ مجدد، مستقیم از آن بازخوانی می‌کنند (سرعت).
تازگی با تعداد ردیف بانک خام کنترل می‌شود؛ تغییر خام ← بازمحاسبهٔ خودکار.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from early_warning.price_range import compute_daily_params  # noqa: E402

try:
    # قرارداد واحد قدرت خرید علامت‌دار — همان تابع exporter
    from export_portfoli_data import _signed_power  # noqa: E402
except Exception:  # نسخهٔ مستقل — بدون exporter
    def _signed_power(ratio: float | None) -> float | None:
        if ratio is None or ratio <= 0:
            return None
        return ratio if ratio >= 1 else -1.0 / ratio

DB = ROOT / "data" / "raw" / "history.sqlite"
# بانک محاسباتی — جدا از بانک خام؛ میانگین‌ها و شاخص‌های آماده برای گزارش‌ها
COMPUTED_DB = ROOT / "data" / "raw" / "history_computed.sqlite"
COMPUTED_SQL = """
CREATE TABLE IF NOT EXISTS computed_daily (
    symbol TEXT NOT NULL,
    date_jalali TEXT NOT NULL,
    date_greg TEXT NOT NULL,
    pc REAL, pcp REAL, flow_rial REAL,
    flow_avg5_rial REAL, flow_avg10_rial REAL, flow_avg20_rial REAL, flow_avg30_rial REAL,
    tvol REAL, vol_avg5 REAL, vol_avg10 REAL, vol_avg20 REAL, vol_avg30 REAL,
    buy_power REAL, buy_power_avg5 REAL, buy_power_avg10 REAL,
    buy_power_avg20 REAL, buy_power_avg30 REAL,
    bs_count_ratio REAL, real_buy_pct REAL, reaction_pct REAL, money_flow_pct REAL,
    mf5_pct REAL, mf30_pct REAL, vol5_pct REAL, vol30_pct REAL,
    computed_at TEXT,
    PRIMARY KEY (symbol, date_jalali)
) WITHOUT ROWID
"""
COMPUTED_META_SQL = "CREATE TABLE IF NOT EXISTS computed_meta (k TEXT PRIMARY KEY, v TEXT)"
# ستون‌های عبوری از بانک خام با نام TSE — ترجمهٔ UI ↔ بانک
_UI_TO_BANK = {"close_price": "pc", "pct_close": "pcp", "trade_volume": "tvol"}
_BANK_TO_UI = {v: k for k, v in _UI_TO_BANK.items()}  # pc→close_price و…
COMPUTED_COLS = ["symbol", "date_jalali", "date_greg", "pc", "pcp",
                 "flow_rial", "flow_avg5_rial", "flow_avg10_rial", "flow_avg20_rial",
                 "flow_avg30_rial", "tvol", "vol_avg5", "vol_avg10",
                 "vol_avg20", "vol_avg30", "buy_power", "buy_power_avg5",
                 "buy_power_avg10", "buy_power_avg20", "buy_power_avg30",
                 "bs_count_ratio", "real_buy_pct", "reaction_pct", "money_flow_pct",
                 "mf5_pct", "mf30_pct", "vol5_pct", "vol30_pct", "computed_at"]


def _flow(r: dict) -> float | None:
    """ورود پول ریالی روز — ارزش واقعی خرید حقیقی منهای فروش حقیقی (خام TSE)."""
    b, s = r.get("buy_i_value"), r.get("sell_i_value")
    if b is None and s is None:
        return None
    return (b or 0.0) - (s or 0.0)


def _keep_latest(out: dict) -> None:
    """برش درجا به بروزترین سطر هر نماد — نمای پیش‌فرض سبک صفحهٔ سابقه.

    ردیف‌ها در هر دو مسیر (کش و محاسبهٔ زنده) صعودی بر اساس date_greg هستند؛
    max برای اطمینان. متادیتای days/last_collected دست‌نخورده می‌ماند و
    میانگین‌های چندروزه در خود ردیفِ بروز هستند، پس چیزی از دست نمی‌رود.
    """
    for s in out.get("symbols", []):
        rows = s.get("rows") or []
        if rows:
            s["rows"] = [max(rows, key=lambda r: r.get("date_greg") or "")]


def build_history_data(root: Path = ROOT, symbols: list[str] | None = None,
                       use_cache: bool = True, latest_only: bool = False) -> dict:
    """ردیف‌های داشبورد سابقه — اول بانک محاسباتی (سریع)، وگرنه محاسبه از خام.

    مسیر سریع: اگر history_computed.sqlite موجود و هم‌رو با بانک خام بود،
    ردیف‌های آماده از آن بازخوانی می‌شود (برای گزارش‌ها و داشبورد).
    وگرنه از بانک خام محاسبه و نتیجه در بانک محاسباتی ذخیره می‌شود.

    latest_only=True ← فقط بروزترین سطر هر نماد (پیش‌فرض بازشدن صفحهٔ سابقه؛
    چند هزار سطر ← چند سطر). فقط خروجی بریده می‌شود؛ بانک محاسباتی کامل ذخیره
    می‌شود و گزار‌ش‌ها/بایگانی که این تابع را بدون فلگ صدا می‌زنند دست‌نخورده‌اند.
    """
    if use_cache:
        cached = load_computed(root, symbols)
        if cached is not None:
            if latest_only:
                _keep_latest(cached)
            return cached
    db = root / "data" / "raw" / "history.sqlite"
    if not db.exists():
        return {"ok": False, "error": "بانک سابقه پیدا نشد — ابتدا جمع‌آوری را اجرا کنید",
                "generated_at": None, "symbols": []}
    con = sqlite3.connect(str(db))
    con.row_factory = sqlite3.Row
    cols = [r[1] for r in con.execute("PRAGMA table_info(history_daily)")]
    names = [r[0] for r in con.execute("SELECT DISTINCT symbol FROM history_daily ORDER BY symbol")]
    if symbols:
        names = [n for n in names if n in symbols]

    cfg_dir = root / "config"
    out = {"ok": True, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "symbols": []}
    for name in names:
        rows = [dict(r) for r in con.execute(
            "SELECT * FROM history_daily WHERE symbol=? ORDER BY date_greg", (name,))]
        if not rows:
            continue
        # پیش‌محاسبهٔ سری‌ها برای پنجره‌های ۵/۲۰/۳۰ روزه (مطابق _daily_statsِ exporter:
        # پنجره فقط «روزهای قبل» است، امروز داخل میانگین نمی‌آید)
        flows = [_flow(r) for r in rows]
        vols = [r.get("tvol") for r in rows]
        f_abs = [abs(f) if f is not None else None for f in flows]

        def _power_raw(r: dict) -> float | None:
            """نسبت خام قدرت خرید روز (همیشه مثبت) — فرمول dashboard.git:
            (ارزش خرید حقیقی ÷ تعداد خریداران) ÷ (ارزش فروش حقیقی ÷ تعداد فروشندگان)"""
            bv, sv = r.get("buy_i_value"), r.get("sell_i_value")
            bc, sc = r.get("buy_counti"), r.get("sell_counti")
            if not bv or not sv or not bc or not sc:
                return None
            return (bv / bc) / (sv / sc)

        powers_raw = [_power_raw(r) for r in rows]
        # علامت‌دار فقط در نمایش: نسبت ≥ ۱ ← +نسبت، نسبت < ۱ ← −معکوس (۰٫۸۴ ← ‎−۱٫۱۹)
        powers = [_signed_power(x) for x in powers_raw]

        # ── اجزای خام هر روز برای «میانگین وزنی» ──
        # روز معتبر هر متریک = روزی که همهٔ اجزای فرمولش موجود باشد
        def _fday(r):   # ورود پول — خرید/فروش حقیقی
            if r.get("buy_i_value") is None and r.get("sell_i_value") is None:
                return None
            return {"bv": r.get("buy_i_value") or 0, "sv": r.get("sell_i_value") or 0}

        def _vday(r):   # حجم روز
            return {"t": r["tvol"]} if r.get("tvol") is not None else None

        def _pday(r):   # اجزای قدرت خرید
            bv, sv = r.get("buy_i_value"), r.get("sell_i_value")
            bc, sc = r.get("buy_counti"), r.get("sell_counti")
            if not bv or not sv or not bc or not sc:
                return None
            return {"bv": bv, "sv": sv, "bc": bc, "sc": sc}

        def _win_agg(getter, n, i):
            """پنجرهٔ وزنی n روزه — جمعِ تجمیعیِ اجزای روزهای «نزدیک‌ترین به روز i»
            بدون امروز؛ پنجرهٔ ناقص = None. قاعدهٔ انتخاب روز همان _win است
            (روز نامعتبر رد می‌شود و نزدیک‌ترین روزِ معتبرِ قبل جایگزین می‌شود).
            خروجی: (جمع اجزا روی پنجره، تعداد روز) یا None."""
            if i < n:
                return None
            chunk = [g for g in (getter(r) for r in rows[max(0, i - n * 2):i])
                     if g is not None][-n:]
            if len(chunk) < n:
                return None
            keys = chunk[0].keys()
            sums = {k: sum(c[k] or 0 for c in chunk) for k in keys}
            return sums, len(chunk)

        def _win(xs, n, i):
            """میانگین n روزِ دارای دادهٔ «نزدیک‌ترین به روز i» — بدون امروز؛
            پنجرهٔ ناقص = None. روز بدون معامله/داده ناقص رد می‌شود و جای آن
            نزدیک‌ترین روزِ معتبرِ قبل می‌نشیند (سری صعودی ← انتها = نزدیک‌ترین)."""
            if i < n:
                return None
            xs = [x for x in xs[max(0, i - n * 2):i] if x is not None][-n:]
            return sum(xs) / n if len(xs) >= n else None

        computed: list[dict] = []
        for i, r in enumerate(rows):
            close = r.get("pc")
            yest = r.get("py")
            tval = r.get("tval")
            row = {"date_jalali": r.get("date_jalali"), "date_greg": r.get("date_greg"),
                   "close_price": close}
            # ٪ نوسان پایانی — فرمول pct_close (export_portfoli_data)
            row["pct_close"] = round((close - yest) / yest * 100, 2) if (close and yest) else None
            fl = flows[i]
            if fl is None:
                row["money_flow_pct"] = None
            else:
                # ورود پول (٪) — فرمول money_flow_ratio_pct
                row["money_flow_pct"] = round(fl / tval * 100, 2) if tval else None
            # نسبت‌های چندروزه — مخرج = میانگین کامل روزهای قبل (پنجرهٔ کامل مثل مرجع)
            f5, f20, f30 = (_win(f_abs, n, i) for n in (5, 20, 30))
            v5, v20, v30 = (_win(vols, n, i) for n in (5, 20, 30))
            row["mf5_pct"] = round(fl / f5 * 100, 2) if (fl is not None and f5) else None
            row["mf30_pct"] = round(fl / f30 * 100, 2) if (fl is not None and f30) else None
            row["vol5_pct"] = round(vols[i] / v5 * 100, 2) if (vols[i] and v5) else None
            row["vol30_pct"] = round(vols[i] / v30 * 100, 2) if (vols[i] and v30) else None
            # ── میانگین‌های وزنی ۵/۱۰/۲۰/۳۰ روزه — از جمع تجمیعی پنجرهٔ کامل
            # روزهای قبل (نه میانگین سادهٔ نسبت‌های روزانه) ──
            # ورود پول وزنی = (Σ ارزش خرید − Σ ارزش فروش) ÷ تعداد روز
            for n in (5, 10, 20, 30):
                aggf = _win_agg(_fday, n, i)
                row[f"flow_avg{n}_rial"] = (
                    round((aggf[0]["bv"] - aggf[0]["sv"]) / aggf[1]) if aggf else None)
            # حجم وزنی = Σ حجم ÷ تعداد روز
            for n in (5, 10, 20, 30):
                aggv = _win_agg(_vday, n, i)
                row[f"vol_avg{n}"] = round(aggv[0]["t"] / aggv[1]) if aggv else None
            # حجم روز — همان ستون خام qTotTran5J
            row["trade_volume"] = vols[i]
            # قدرت خرید روز (علامت‌دار) + میانگین وزنی ۵/۱۰/۲۰/۳۰ روزه:
            # (Σ ارزش خرید ÷ Σ خریداران) ÷ (Σ ارزش فروش ÷ Σ فروشندگان) — بعد علامت‌دار
            pw = powers[i]
            row["buy_power"] = round(pw, 2) if pw is not None else None
            for n in (5, 10, 20, 30):
                av = None
                aggp = _win_agg(_pday, n, i)
                if aggp:
                    s = aggp[0]
                    if s["bc"] and s["sc"]:
                        per_buy = s["bv"] / s["bc"]      # میانگین وزنی خرید هر خریدار
                        per_sell = s["sv"] / s["sc"]     # میانگین وزنی فروش هر فروشنده
                        av = _signed_power(per_buy / per_sell if per_sell else None)
                row[f"buy_power_avg{n}"] = round(av, 2) if av is not None else None
            # تعداد خریدار به فروشنده — فرمول buyer_seller_count_ratio
            bc, sc = r.get("buy_counti"), r.get("sell_counti")
            row["bs_count_ratio"] = round(bc / sc, 2) if (bc and sc) else None
            # درصد خرید حقیقی از کل معاملات — ارزش واقعی ÷ ارزش کل × ۱۰۰
            rbv = r.get("buy_i_value")
            row["real_buy_pct"] = round(rbv / tval * 100, 2) if (rbv is not None and tval) else None
            # واکنش قیمت — فرمول price_reaction_score با کف/سقف price_range.py
            dp = compute_daily_params(name, float(yest), cfg_dir) if yest else None
            if dp and dp["max_allowed_price"] > dp["min_allowed_price"] and r.get("last_price"):
                row["reaction_pct"] = round(
                    (r["pl"] - dp["min_allowed_price"])
                    / (dp["max_allowed_price"] - dp["min_allowed_price"]) * 100, 1)
            else:
                row["reaction_pct"] = None
            row["flow_rial"] = round(fl) if fl is not None else None
            computed.append(row)
        out["symbols"].append({"name": name, "days": len(computed),
                               # تاریخ آخرین روز جمع‌آوری — آخرین تاریخ شمسیِ بانک خام
                               "last_collected": computed[-1]["date_jalali"],
                               "rows": computed})
    con.close()
    out["source"] = "computed_fresh"
    try:
        save_computed(root, out)  # بانک محاسباتی — خرابی‌اش مانع خروجی نمی‌شود
    except Exception as se:
        out["computed_save_error"] = str(se)
    if latest_only:
        _keep_latest(out)  # بعد از ذخیره — بانک محاسباتی باید کامل بماند
    return out


def load_computed(root: Path = ROOT, symbols: list[str] | None = None) -> dict | None:
    """بازخوانی سریع از بانک محاسباتی history_computed.sqlite.

    خروجی None یعنی بانک غایب، خالی یا کهنه (تعداد ردیفش با بانک خام نمی‌خواند)
    — در این حالت build_history_data از خام بازمحاسبه می‌کند.
    """
    hdb = root / "data" / "raw" / "history.sqlite"
    cdb = root / "data" / "raw" / "history_computed.sqlite"
    if not hdb.exists() or not cdb.exists():
        return None
    try:
        hcon = sqlite3.connect(str(hdb))
        n_raw = hcon.execute("SELECT COUNT(*) FROM history_daily").fetchone()[0]
        hcon.close()
    except sqlite3.Error:
        return None
    con = sqlite3.connect(str(cdb))
    con.row_factory = sqlite3.Row
    try:
        meta = {r["k"]: r["v"] for r in con.execute("SELECT k, v FROM computed_meta")}
        if int(meta.get("source_rows") or -1) != n_raw:
            return None  # بانک خام تغییر کرده — بازمحاسبه لازم
        names = [r[0] for r in con.execute(
            "SELECT DISTINCT symbol FROM computed_daily ORDER BY symbol")]
        if symbols:
            names = [n for n in names if n in symbols]
        out = {"ok": True, "source": "computed_bank",
               "generated_at": meta.get("computed_at"), "symbols": []}
        for name in names:
            rows = [dict(r) for r in con.execute(
                "SELECT * FROM computed_daily WHERE symbol=? ORDER BY date_greg",
                (name,))]
            for row in rows:  # نام بانک (pc/pcp/tvol) → کلید UI
                for ui, bk in _UI_TO_BANK.items():
                    if bk in row:
                        row[ui] = row.pop(bk)
            if not rows:
                continue
            out["symbols"].append({"name": name, "days": len(rows),
                                   "last_collected": rows[-1]["date_jalali"],
                                   "rows": rows})
        return out if out["symbols"] else None
    except sqlite3.Error:
        return None
    finally:
        con.close()


def save_computed(root: Path, data: dict) -> dict:
    """ذخیرهٔ محاسبات در بانک جداگانهٔ history_computed.sqlite (خارج از بانک خام).

    همهٔ ستون‌های محاسبه‌شدهٔ هر (نماد، روز) — میانگین‌های ۵/۱۰/۲۰/۳۰، قدرت
    علامت‌دار، نسبت‌ها — یک‌جا ذخیره می‌شوند تا گزارش‌ها به این بانک ارجاع
    دهند و هر بار محاسبهٔ مجدد انجام نشود.
    """
    cdb = root / "data" / "raw" / "history_computed.sqlite"
    cdb.parent.mkdir(parents=True, exist_ok=True)
    hdb = root / "data" / "raw" / "history.sqlite"
    n_raw = 0
    if hdb.exists():
        hcon = sqlite3.connect(str(hdb))
        n_raw = hcon.execute("SELECT COUNT(*) FROM history_daily").fetchone()[0]
        hcon.close()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    con = sqlite3.connect(str(cdb))
    n = 0
    try:
        con.execute(COMPUTED_SQL)
        con.execute(COMPUTED_META_SQL)
        syms = sorted({s["name"] for s in data.get("symbols", [])})
        cols = ", ".join(COMPUTED_COLS)
        ph = ", ".join("?" for _ in COMPUTED_COLS)
        for sym in syms:
            # ردیف‌های کهنهٔ همین نماد پاک می‌شوند — روزِ حذف‌شده از خام در
            # بانک محاسباتی هم حذف شود (INSERT OR REPLACE تنها پاک نمی‌کند)
            con.execute("DELETE FROM computed_daily WHERE symbol=?", (sym,))
            for s in data.get("symbols", []):
                if s["name"] != sym:
                    continue
                for r in s["rows"]:
                    rec = {"computed_at": now, "symbol": s["name"]}
                    # کلید ردیف = نام بانک؛ مقدار از کلید UI همان فیلد
                    rec.update({k: r.get(_BANK_TO_UI.get(k, k))
                                for k in COMPUTED_COLS
                                if k not in ("computed_at", "symbol")})
                    con.execute(f"INSERT INTO computed_daily ({cols}) VALUES ({ph})",
                                [rec[c] for c in COMPUTED_COLS])
                    n += 1
        # متای تازگی فقط وقتی معتبر است که همهٔ نمادهای بانک خام پوشش داده شده باشند
        all_covered = False
        if hdb.exists():
            hcon = sqlite3.connect(str(hdb))
            hsyms = {r[0] for r in hcon.execute(
                "SELECT DISTINCT symbol FROM history_daily")}
            hcon.close()
            all_covered = hsyms <= set(syms)
        if all_covered:
            con.execute("INSERT OR REPLACE INTO computed_meta (k, v) VALUES ('source_rows', ?)",
                        (str(n_raw),))
            con.execute("INSERT OR REPLACE INTO computed_meta (k, v) VALUES ('computed_at', ?)",
                        (now,))
        con.commit()
    finally:
        con.close()
    return {"ok": True, "rows": n, "db": str(cdb)}


def refresh_computed(root: Path = ROOT) -> dict:
    """بازمحاسبهٔ کامل از بانک خام و ذخیره در بانک محاسباتی.

    history_collector.py پس از پایان جمع‌آوری این را صدا می‌زند تا میانگین‌ها
    «در لحظهٔ جمع‌آوری تاریخچه» یک‌جا محاسبه و ذخیره شوند.
    """
    data = build_history_data(root, use_cache=False)  # محاسبه + ذخیرهٔ خودکار
    return {"ok": data.get("ok"), "symbols": len(data.get("symbols", [])),
            "source": data.get("source"),
            "error": data.get("error") or data.get("computed_save_error")}
# شِمای بایگانی محاسبات — همان بانکی که portfoli_server.save_history می‌سازد
# (UNIQUE(symbol, date_jalali, fetch_hms) → ردیف تکراری ممکن نیست)
PORTFOLI_HISTORY_SQL = """
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


def backfill_portfoli_history(root: Path = ROOT, days: int = 30) -> dict:
    """پر کردن بایگانی portfoli_history.sqlite تا N روز گذشته (پیش‌فرض ۳۰، بیشینه ۹۰).

    داشبورد لایو این بانک را فقط در طول اجرا پر می‌کند؛ این تابع همان ردیف‌های
    محاسبه‌شدهٔ سابقه را از بانک خام history.sqlite به آن اضافه می‌کند تا مرور
    تاریخچه از همان روزِ نصب ممکن باشد. fetch_hms = "hist" نشان می‌دهد ردیف
    از سابقهٔ TSETMC بایگانی شده نه از نمونهٔ لحظه‌ای لایو.
    """
    days = min(max(int(days), 30), 90)  # حداقل ۳۰ روز دیفالت، تا ۹۰ روز
    data = build_history_data(root)
    hist = root / "data" / "raw" / "portfoli_history.sqlite"
    hist.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(hist))
    added = 0
    updated = 0
    last_dates = []
    try:
        con.execute(PORTFOLI_HISTORY_SQL)
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for s in data.get("symbols", []):
            tail = s["rows"][-days:]
            last_dates.append({"symbol": s["name"],
                               "last_collected": s.get("last_collected"),
                               "days": len(tail)})
            for r in tail:
                payload = {"symbol": s["name"], "date_jalali": r["date_jalali"],
                           "fetch_hms": "hist",
                           "source": "history.sqlite (TSETMC سابقهٔ خام)"}
                payload.update(r)
                # اگر ردیف hist قبلاً هست فقط payload تازه می‌شود (فرمول‌های جدید)،
                # وگرنه اضافه می‌شود — در هر دو حالت یک ردیف، بدون تکرار
                has = con.execute(
                    "SELECT 1 FROM computed_samples "
                    "WHERE symbol=? AND date_jalali=? AND fetch_hms='hist'",
                    (s["name"], r["date_jalali"])).fetchone()
                if has:
                    con.execute(
                        "UPDATE computed_samples SET payload=?, saved_at=? "
                        "WHERE symbol=? AND date_jalali=? AND fetch_hms='hist'",
                        (json.dumps(payload, ensure_ascii=False), now,
                         s["name"], r["date_jalali"]))
                    updated += 1
                else:
                    con.execute(
                        "INSERT INTO computed_samples "
                        "(saved_at, date_jalali, fetch_hms, symbol, payload) "
                        "VALUES (?,?,?,?,?)",
                        (now, r["date_jalali"], "hist", s["name"],
                         json.dumps(payload, ensure_ascii=False)))
                    added += 1
        con.commit()
    finally:
        con.close()
    return {"ok": True, "days": days, "added": added, "updated": updated,
            "last_dates": last_dates}


if __name__ == "__main__":
    import json
    data = build_history_data()
    for s in data.get("symbols", []):
        last = s["rows"][-1] if s["rows"] else {}
        print(s["name"], "→", json.dumps(last, ensure_ascii=False))
