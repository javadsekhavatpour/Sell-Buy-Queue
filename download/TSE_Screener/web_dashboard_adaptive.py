"""
web_dashboard_live.py — ⚠ ماژول داخلی (مستقیم اجرا نکنید)
اجرا با: python web_dashboard_adaptive.py  (این ماژول را import می‌کند)

نسخه جدید داشبورد رصد و تایید بصری.
داشبورد وب زنده برای نمایش شش گروه داده تابلو در یک صفحه، شبیه تابلوی TSETMC.

چیدمان صفحه (راست به چپ، مطابق تابلوی معاملاتی):
  سطر اول:  راست = گروه A (اطلاعات پایه و قیمت) | چپ = گروه E (خروجی موتورهای تحلیلی — عرض ۲ ستون)
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
  --interval  فاصله نمونه‌برداری ثانیه  (پیش‌فرض: زنده ۳۰، شبیه‌سازی ۳)
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
    from flask import Flask, jsonify, request
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
from early_warning.price_range import (
    load_range_rules,
    get_symbol_category,
    get_category_percent,
    compute_daily_params,
    to_jalali,
)
from early_warning.isin_checker import (
    parse_range_rules_html,
    get_isin_prefix,
    get_range_percent_by_isin,
    compute_range_from_isin,
)
from early_warning.storage import MarketDataStorage
from early_warning.adaptive_scoring import AdaptiveNormalizer
from early_warning.sell_pressure import SellPressureDetector
from early_warning.smart_accumulation import BuyPressureDetector
from early_warning.alert_engine import AlertEngine, tier, classify
from early_warning.speed_indicators import SpeedIndicatorEngine


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


def load_price_range_live(cfg: dict, symbol: str, ins_code: str,
                          storage: MarketDataStorage | None = None) -> None:
    """
    محاسبه پارامترهای ثابت روز برای داشبورد لایو و تزریق در cfg.

    مراحل:
      ۱. yesterday_price از TSETMC (یا base_price به‌عنوان fallback)
      ۲. ISIN از TSETMC دریافت می‌شود
      ۳. درصد مجاز از config/tse_range_rules.html بر اساس پیشوند ISIN
      ۴. (fallback) اگر ISIN دریافت نشد → از symbol_categories.json
      ۵. min/max = yesterday_price × (1 ± pct/100)
      ۶. تزریق در cfg['test_symbol']['fixed_price_range']
      ۷. ذخیره در جدول daily_params بانک (اگر storage داده شده باشد)
    """
    from datetime import date as _date
    config_dir = ROOT / "config"
    html_path = config_dir / "tse_range_rules.html"
    print("─" * 60)
    print("  محاسبه پارامترهای ثابت روز (داشبورد لایو)")
    print("─" * 60)
    print(f"  ✓ نماد: {symbol}")

    # ── ۱. yesterday_price از TSETMC ──
    yesterday_price = 0.0
    isin = ""
    tmp_collector = None
    if ins_code:
        try:
            tmp_collector = MarketDataCollector(cfg)
            inst = tmp_collector.fetch_intraday(str(ins_code))
            if inst:
                yesterday_price = float(inst.get("yesterday_price", 0) or 0)
        except Exception as e:
            print(f"  ⚠ خطا در دریافت yesterday_price از API: {e}")
    if yesterday_price <= 0:
        base = float(cfg.get("test_symbol", {}).get("base_price", 0) or 0)
        if base > 0:
            yesterday_price = base
            print(f"  ⚠ yesterday_price از API دریافت نشد — base_price: {yesterday_price:,.0f}")
        else:
            print("  [!] قیمت دیروز دریافت نشد — محاسبه کف/سقف ممکن نیست.")
            print("─" * 60)
            return
    else:
        print(f"  ✓ قیمت دیروز: {yesterday_price:,.0f}")

    # ── ۲. ISIN از TSETMC ──
    if tmp_collector and ins_code:
        try:
            isin = tmp_collector.fetch_isin(str(ins_code)) or ""
        except Exception as e:
            print(f"  ⚠ خطا در دریافت ISIN از API: {e}")
    if isin:
        print(f"  ✓ ISIN: {isin}  (پیشوند: {get_isin_prefix(isin)})")

    # ── ۳. درصد مجاز بر اساس ISIN (از HTML کانفیگ) ──
    category = None
    pct = None
    if isin and html_path.exists():
        rules = parse_range_rules_html(html_path)
        result = get_range_percent_by_isin(isin, rules=rules)
        if result:
            category, pct = result
            print(f"  ✓ دسته (از ISIN): {category}")
            print(f"  ✓ درصد مجاز (از HTML): {pct}%")

    # ── ۴. fallback: symbol_categories.json + tse_range_rules.json ──
    if pct is None:
        if isin:
            print(f"  ⚠ پیشوند «{get_isin_prefix(isin)}» در tse_range_rules.html یافت نشد.")
        print(f"  ⚠ fallback → جستجو در symbol_categories.json...")
        category_fb = get_symbol_category(symbol, config_dir)
        if category_fb:
            pct_fb = get_category_percent(category_fb, config_dir)
            if pct_fb is not None:
                category = category_fb
                pct = pct_fb
                print(f"  ✓ دسته (fallback): {category}")
                print(f"  ✓ درصد مجاز (fallback): {pct}%")
        if pct is None:
            print(f"  ⚠ نماد در هیچ منبعی یافت نشد.")
            print(f"    دسته‌های موجود در tse_range_rules.html:")
            if html_path.exists():
                for prefix, (cat, p) in parse_range_rules_html(html_path).items():
                    print(f"      • {prefix} → {cat} ({p}%)")
            print(f"  ⚠ از limit_percent پیش‌فرض (۱۰٪) استفاده می‌شود — کف/سقف اشتباه!")
            print("─" * 60)
            return

    # ── ۵. محاسبه min/max ──
    min_allowed = round(yesterday_price * (1 - pct / 100.0), 0)
    max_allowed = round(yesterday_price * (1 + pct / 100.0), 0)
    print(f"  ✓ کف مجاز: {min_allowed:,.0f}")
    print(f"  ✓ سقف مجاز: {max_allowed:,.0f}")

    # ── ۶. تزریق در config ──
    cfg_sym = cfg.setdefault("test_symbol", {})
    cfg_sym["fixed_price_range"] = {
        "yesterday_price": yesterday_price,
        "min_allowed_price": min_allowed,
        "max_allowed_price": max_allowed,
        "range_percent": pct,
        "category": category or "",
        "isin": isin,
    }
    cfg_sym["limit_percent"] = pct
    cfg_sym["base_price"] = yesterday_price

    # ── ۷. ذخیره در جدول daily_params بانک ──
    if storage is not None:
        try:
            today_j = to_jalali(_date.today())
            daily_record = {
                "date_jalali": today_j,
                "symbol": symbol,
                "ins_code": ins_code or "",
                "category": category or "",
                "range_percent": pct,
                "yesterday_price": yesterday_price,
                "first_price": None,
                "min_allowed_price": min_allowed,
                "max_allowed_price": max_allowed,
                "computed_at": datetime.now().isoformat(timespec="seconds"),
            }
            storage.upsert_daily_params(daily_record)
            print(f"  ✓ ذخیره در daily_params (بانک): {today_j}")
        except Exception as e:
            print(f"  ⚠ خطا در ذخیره daily_params: {e}")

    print("─" * 60)


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
                 max_history: int = 300, normalizer=None, storage=None):
        self.cfg = cfg
        self.mode = mode
        self.normalizer = normalizer
        self.storage = storage  # MarketDataStorage — برای ذخیره snapshot و محاسبه تجمعی از DB
        sym = cfg.get("test_symbol", {})
        self.symbol = symbol or sym.get("name", "ریتون")
        self.ins_code = str(ins_code or sym.get("ins_code", ""))
        self.interval = interval or (30 if mode == "live" else 3)
        self.scenario = scenario
        self.samples = samples
        self.history: deque[MarketSnapshot] = deque(maxlen=max_history)
        self.recent_trades: deque[Trade] = deque(maxlen=15)
        self.last_error: str = ""
        self.last_fetch_time: str = ""
        self._lock = threading.Lock()
        self._db_lock = threading.Lock()  # سریال‌سازی دسترسی به DB بین threadها
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.collector = None
        self._demo_snaps: list[MarketSnapshot] = []
        self._trades_by_time: dict[str, list[Trade]] = {}
        # موتورهای تحلیلی (برای نمایش در گروه E)
        try:
            self.sell_pressure = SellPressureDetector(cfg, normalizer=normalizer)
            self.buy_pressure = BuyPressureDetector(cfg, normalizer=normalizer)
            self.alert_engine = AlertEngine(cfg)
            self.speed_engine = SpeedIndicatorEngine(cfg)
        except Exception as e:
            print(f"  ⚠ موتورهای تحلیلی راه‌اندازی نشدند: {e}")
            self.sell_pressure = None
            self.buy_pressure = None
            self.alert_engine = None
            self.speed_engine = None

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
        # همیشه date_jalali امروز را تنظیم می‌کنیم (حتی در demo که تاریخ ثابت دارد)
        # تا محاسبه‌ی تجمعی «از ابتدای امروز» درست کار کند
        if snap:
            snap.date_jalali = today_jalali_str()
        with self._lock:
            if snap is not None:
                self.history.append(snap)
            for tr in (trades or []):
                self.recent_trades.append(tr)
            self.last_error = (snap.fetch_error if snap else "") or ""
            self.last_fetch_time = datetime.now().isoformat(timespec="seconds")
        # ذخیره snapshot در بانک (مثل run_live.py) برای محاسبه تجمعی از ابتدای روز
        # جلوگیری از درج تکراری با timestamp یکسان (در ری‌استارت داشبورد)
        if snap is not None and self.storage is not None:
            try:
                with self._db_lock:
                    cur = self.storage.conn.cursor()
                    cur.execute("SELECT 1 FROM snapshots WHERE symbol=? AND timestamp=? LIMIT 1",
                                (snap.symbol, snap.timestamp))
                    if cur.fetchone() is None:
                        self.storage.insert_snapshot(snap)
            except Exception as e:
                print(f"  ⚠ خطای ذخیره snapshot در DB: {e}")

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
        # فاصله تا کف/سقف مجاز — نسبت به yesterday_price (قیمت پایه)
        d["dist_to_floor_abs"] = round(s.last_price - s.min_allowed_price, 0) if s.min_allowed_price > 0 else None
        d["dist_to_ceiling_abs"] = round(s.max_allowed_price - s.last_price, 0) if s.max_allowed_price > 0 else None
        d["dist_to_floor_pct"] = (round((s.last_price - s.min_allowed_price) / y * 100, 2)
                                  if y > 0 and s.min_allowed_price > 0 else None)
        d["dist_to_ceiling_pct"] = (round((s.max_allowed_price - s.last_price) / y * 100, 2)
                                    if y > 0 and s.max_allowed_price > 0 else None)
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

    # --- خروجی موتورهای تحلیلی (برای گروه E) ---

    def _engine_output(self, hist: list[MarketSnapshot]) -> dict:
        """اجرای هر دو موتور تحلیلی + ترکیب هشدار روی آخرین نمونه.

        امتیاز تجمعی (مجموع از ابتدا تا الان) از snapshot‌های امروز در بانک محاسبه
        می‌شود — حتی اگر داشبورد ری‌استارت شده باشد. در حالت demo (بدون storage)
        از history درون‌حافظه‌ای استفاده می‌شود.
        """
        out: dict = {"available": False}
        if not hist:
            return out
        try:
            # --- ارزیابی نمونه‌ی جاری (آخرین نمونه‌ی زنده) ---
            s = hist[-1]
            prev = hist[-2] if len(hist) >= 2 else None
            history = hist[:-1]
            sell_res = self.sell_pressure.evaluate(s, prev) if self.sell_pressure else None
            buy_res = self.buy_pressure.evaluate(s, prev, history) if self.buy_pressure else None
            # موتور شاخص‌های سرعتی (نرخ تخلیه تقاضا / رشد عرضه / نسبت جذب)
            speed_res = (self.speed_engine.compute(s, history)
                         if self.speed_engine else None)
            # Phase 2: ثبت raw_valueها برای نرمال‌سازی تطبیقی آینده
            if self.normalizer is not None:
                if sell_res:
                    self.normalizer.record_factors(s.symbol, "sell", sell_res.factors,
                                                  date_jalali=s.date_jalali)
                if buy_res:
                    self.normalizer.record_factors(s.symbol, "buy", buy_res.factors,
                                                  date_jalali=s.date_jalali)
            combined = None
            if sell_res and buy_res and self.alert_engine:
                combined = self.alert_engine.evaluate(sell_res, buy_res)
            # --- محاسبه‌ی امتیاز تجمعی (از بانک یا history) ---
            cum_sell, cum_buy, cum_count = self._cumulative_scores()
            out = {
                "available": True,
                "sell": sell_res.to_dict() if sell_res else None,
                "buy": buy_res.to_dict() if buy_res else None,
                "speed": speed_res.to_dict() if speed_res else None,
                "combined": combined.to_dict() if combined else None,
                "sell_tier": tier(sell_res.total_score) if sell_res else "نامشخص",
                "buy_tier": tier(buy_res.total_score) if buy_res else "نامشخص",
                "classification": classify(
                    sell_res.total_score if sell_res else None,
                    buy_res.total_score if buy_res else None,
                ),
                # امتیاز تجمعی: مجموع همه امتیازها از ابتدا تا الان
                "cumulative_sell_score": round(cum_sell, 1),
                "cumulative_buy_score": round(cum_buy, 1),
                "cumulative_samples": cum_count,
            }
        except Exception as e:
            out = {"available": False, "error": str(e)}
        return out

    def _cumulative_scores(self) -> tuple[float, float, int]:
        """محاسبه‌ی امتیاز تجمعی (مجموع همه امتیازها از ابتدای روز تا الان).

        منبع: snapshot‌های امروز در بانک (اگر storage موجود باشد) — حتی اگر
        داشبورد ری‌استارت شده باشد، نمونه‌های قبلی امروز در بانک باقی‌مانده‌اند.
        در حالت demo (بدون storage) یا خطای DB: از history درون‌حافظه‌ای.

        برمی‌گرداند: (cum_sell, cum_buy, count)
        """
        # اولویت: snapshot‌های امروز از بانک
        if self.storage is not None:
            try:
                today_dash = today_jalali_str()           # "1405-08-27" (web dashboard)
                today_slash = today_dash.replace("-", "/") # "1405/08/27" (run_live.py / collector)
                with self._db_lock:
                    cur = self.storage.conn.cursor()
                    # هر دو فرمت تاریخ را پوشش می‌دهیم: run_live.py از to_jalali
                    # (با اسلش) و داشبورد از today_jalali_str (با خط تیره) استفاده
                    # می‌کند. بدون این، نمونه‌های run_live.py پیدا نمی‌شدند.
                    cur.execute(
                        "SELECT * FROM snapshots WHERE symbol=? AND date_jalali IN (?, ?) "
                        "ORDER BY timestamp ASC",
                        (self.symbol, today_dash, today_slash))
                    rows = [dict(r) for r in cur.fetchall()]
                if rows:
                    snaps = [MarketSnapshot.from_flat_dict(r) for r in rows]
                    cum_s = 0.0
                    cum_b = 0.0
                    for idx, s_i in enumerate(snaps):
                        prev_i = snaps[idx - 1] if idx >= 1 else None
                        hist_i = snaps[:idx]
                        sr = self.sell_pressure.evaluate(s_i, prev_i) if self.sell_pressure else None
                        br = self.buy_pressure.evaluate(s_i, prev_i, hist_i) if self.buy_pressure else None
                        if sr:
                            cum_s += sr.total_score
                        if br:
                            cum_b += br.total_score
                    return cum_s, cum_b, len(snaps)
            except Exception as e:
                print(f"  ⚠ خطای خواندن تجمعی از DB: {e}")
        # fallback: history درون‌حافظه‌ای (حالت demo یا خطای DB)
        cum_s = 0.0
        cum_b = 0.0
        with self._lock:
            hist = list(self.history)
        for idx, s_i in enumerate(hist):
            prev_i = hist[idx - 1] if idx >= 1 else None
            hist_i = hist[:idx]
            sr = self.sell_pressure.evaluate(s_i, prev_i) if self.sell_pressure else None
            br = self.buy_pressure.evaluate(s_i, prev_i, hist_i) if self.buy_pressure else None
            if sr:
                cum_s += sr.total_score
            if br:
                cum_b += br.total_score
        return cum_s, cum_b, len(hist)

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
        range_ok, out_of_range = s.validate_bid_ask_range()
        base.update({
            "ok": True,
            "samples": len(hist),
            "snapshot": s.to_dict(),
            "range_validation": {
                "ok": range_ok,
                "out_of_range": out_of_range,
            },
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
            "engines": self._engine_output(hist),
            "history": {
                "time": [h.tehran_time for h in hist],
                "last": [h.last_price for h in hist],
                "close": [h.close_price for h in hist],
                "interval_volume": [h.interval_volume for h in hist],
            },
            "collector": {"last_fetch": last_fetch, "last_error": last_error},
        })
        return base


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
/* نوار امتیاز سرعتی */
.sbar{direction:ltr;position:relative;height:22px;background:#eceff3;border-radius:5px;overflow:hidden;min-width:120px}
.sbar-fill{position:absolute;top:0;left:0;bottom:0;border-radius:5px;transition:width 0.4s}
.sbar-fill.down{background:var(--down-bg,#ffd0d0)}
.sbar-fill.mid{background:#ffe9c4}
.sbar-fill.up{background:var(--up-bg,#d0f5d0)}
.sbar-txt{position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#333;font-variant-numeric:tabular-nums}
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
/* خروجی موتور گروه E */
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
    <section class="panel" style="grid-column: span 2">
      <h2><span class="gnum">E</span> خروجی موتورهای تحلیلی</h2>
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

  <!-- سطر سوم: شاخص‌های سرعتی نردبان سفارش‌ها -->
  <section class="panel">
    <h2><span class="gnum">G</span> شاخص‌های سرعتی نردبان سفارش‌ها</h2>
    <div class="body" id="p-g"><div class="wait">در انتظار داده...</div></div>
  </section>

  <!-- سطر چهارم: نمودار روند قیمت -->
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
  const el = document.getElementById("p-c");
  if (!el) return;  // پنل C حذف شده — تابع بدون‌عمل
  const s = d.snapshot, der = d.derived;
  const vb = der.volume_vs_base_pct;
  const w = Math.min(100, vb||0);
  el.innerHTML = `
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

/* ---------- گروه E: خروجی موتورهای تحلیلی (فروش + خرید + classify) ---------- */
function renderE(d) {
  const el = document.getElementById("p-e");
  const eng = d.engines || {};
  if (!eng.available) {
    el.innerHTML = `<div class="wait">${eng.error ? "خطای موتور: " + eng.error : "در حال اجرای موتورهای تحلیلی..."}</div>`;
    return;
  }
  const sell = eng.sell || {};
  const buy = eng.buy || {};
  const comb = eng.combined || {};

  // رنگ بر اساس امتیاز
  const scoreColor = v => (v >= 65 ? "#c62828" : v >= 35 ? "#f9a825" : "#2e7d32");
  const sellS = sell.total_score || 0;
  const buyS = buy.total_score || 0;
  const sellPct = Math.min(100, sellS);
  const buyPct = Math.min(100, buyS);

  // بنر طبقه‌بندی
  const cls = eng.classification || "—";
  const clsColor = cls.includes("تقابل") ? "#6a1b9a"
    : cls.includes("فشار فروش") ? "#c62828"
    : cls.includes("فشار خرید") ? "#2e7d32"
    : cls.includes("هشدار") ? "#f9a825"
    : cls.includes("مراقبت") ? "#fb8c00"
    : "#5a6b7f";

  // ردیف‌های شاخص‌ها (هر دو موتور در یک جدول)
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
  }

  el.innerHTML = `
    <div style="padding:6px 8px;background:${clsColor};color:#fff;text-align:center;font-weight:bold;font-size:12px;border-radius:4px;margin-bottom:6px">
      ${cls}
    </div>
    <div style="display:flex;gap:6px;margin-bottom:6px">
      <div style="flex:1;padding:6px;border:1px solid #eee;border-radius:6px;text-align:center">
        <div style="font-size:11px;color:#888">موتور فروش</div>
        <div style="font-size:22px;font-weight:bold;color:${scoreColor(sellS)}">${N(sellS, 1)}</div>
        <div style="height:8px;background:#f0f0f0;border-radius:4px;overflow:hidden;margin:4px 0">
          <div style="height:100%;width:${sellPct}%;background:${scoreColor(sellS)}"></div>
        </div>
        <div style="font-size:10px">${eng.sell_tier || '—'} ${sell.engine_status === 'warming_up' ? '⚠ گرم‌شدن' : ''}</div>
      </div>
      <div style="flex:1;padding:6px;border:1px solid #eee;border-radius:6px;text-align:center">
        <div style="font-size:11px;color:#888">موتور خرید</div>
        <div style="font-size:22px;font-weight:bold;color:${scoreColor(buyS)}">${N(buyS, 1)}</div>
        <div style="height:8px;background:#f0f0f0;border-radius:4px;overflow:hidden;margin:4px 0">
          <div style="height:100%;width:${buyPct}%;background:${scoreColor(buyS)}"></div>
        </div>
        <div style="font-size:10px">${eng.buy_tier || '—'} ${buy.engine_status === 'warming_up' ? '⚠ گرم‌شدن' : ''}</div>
      </div>
    </div>
    <div style="display:flex;gap:6px;margin-bottom:6px;padding:6px;background:#f8f9fa;border-radius:6px;border:1px dashed #bbb">
      <div style="flex:1;text-align:center">
        <div style="font-size:10px;color:#666">مجموع امتیاز فروش (از ابتدای روز)</div>
        <div style="font-size:18px;font-weight:bold;color:${scoreColor(eng.cumulative_sell_score||0)}">${N(eng.cumulative_sell_score,1)}</div>
      </div>
      <div style="flex:1;text-align:center">
        <div style="font-size:10px;color:#666">مجموع امتیاز خرید (از ابتدای روز)</div>
        <div style="font-size:18px;font-weight:bold;color:${scoreColor(eng.cumulative_buy_score||0)}">${N(eng.cumulative_buy_score,1)}</div>
      </div>
      <div style="flex:0 0 auto;text-align:center;align-self:center">
        <div style="font-size:10px;color:#666">تعداد نمونه</div>
        <div style="font-size:16px;font-weight:bold;color:#333">${eng.cumulative_samples||0}</div>
      </div>
    </div>
    <table class="ttable" style="font-size:10px">
      <thead><tr>
        <th colspan="4" style="background:#fdecea;color:#c62828">شاخص‌های فروش</th>
        <th colspan="4" style="background:#e8f5e9;color:#2e7d32">شاخص‌های خرید</th>
      </tr><tr>
        <th>شاخص</th><th>امتیاز</th><th>نرمال</th><th>خام/وضع</th>
        <th>شاخص</th><th>امتیاز</th><th>نرمال</th><th>خام/وضع</th>
      </tr></thead>
      <tbody>${factorRows}</tbody>
    </table>
    ${(sell.data_quality_warning || buy.data_quality_warning) ? `<div class="hint" style="color:#c62828">⚠ ${sell.data_quality_warning || buy.data_quality_warning}</div>` : ""}
    <div class="hint">۱۲ شاخص مستقل — فروش (قرمز) و خرید (سبز). نرمال‌سازی آستانه ثابت (Phase 1).</div>`;
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

/* ---------- پنل G: شاخص‌های سرعتی ---------- */
function renderSpeed(d) {
  const el = document.getElementById("p-g");
  if (!el) return;
  const sp = (d.engines && d.engines.speed) || null;
  if (!sp || !sp.is_available) {
    el.innerHTML = '<div class="wait">' + (sp ? (sp.notes||[]).join(" — ") || "در انتظار پنجره نمونه کامل..." : "در انتظار داده...") + '</div>';
    return;
  }
  // نوار امتیاز (۰–۱۰۰)
  function bar(score) {
    if (score == null) return "—";
    const v = Math.max(0, Math.min(100, score));
    const cls = v >= 67 ? "down" : v >= 34 ? "mid" : "up";
    return `<div class="sbar"><div class="sbar-fill ${cls}" style="width:${v}%"></div><span class="sbar-txt">${N(v,1)}</span></div>`;
  }
  const notesHtml = (sp.notes && sp.notes.length)
    ? '<div class="hint">' + sp.notes.join(" — ") + '</div>' : "";
  el.innerHTML = `
    <table class="kv">
      ${kv("امتیاز فشار سرعتی (فروش)", bar(sp.speed_pressure_score))}
      ${kv("امتیاز جذب سرعتی (خرید)", bar(sp.speed_absorption_score))}
      ${kv("نرخ تخلیه تقاضا", sp.demand_depletion_rate != null ? N(sp.demand_depletion_rate,4) : "—")}
      ${kv("نرخ رشد عرضه", sp.supply_growth_rate != null ? N(sp.supply_growth_rate,4) : "—")}
      ${kv("نسبت جذب", sp.absorption_ratio != null ? N(sp.absorption_ratio,4) : "—")}
      ${kv("نرمال تخلیه تقاضا", sp.demand_depletion_norm != null ? N(sp.demand_depletion_norm*100,1)+"٪" : "—")}
      ${kv("نرمال رشد عرضه", sp.supply_growth_norm != null ? N(sp.supply_growth_norm*100,1)+"٪" : "—")}
      ${kv("نرمال جذب", sp.absorption_norm != null ? N(sp.absorption_norm*100,1)+"٪" : "—")}
      ${kv("حجم نردبان خرید (ابتدا→اکنون)", N(sp.buy_ladder_start) + " → " + N(sp.buy_ladder_now))}
      ${kv("حجم نردبان فروش (ابتدا→اکنون)", N(sp.sell_ladder_start) + " → " + N(sp.sell_ladder_now))}
      ${kv("حجم معاملات پنجره", N(sp.executed_volume_window))}
      ${kv("تعداد نمونه پنجره", N(sp.window_samples))}
    </table>
    ${notesHtml}`;
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
    renderE(d);
    renderB(d);
    renderD(d);
    renderF(d);
    renderSpeed(d);
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


# ======================================================================
# داشبورد واحد: سه حالت live / db / sim (ادغام‌شده)
# ======================================================================

import argparse
import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_file

# مؤلفه‌های نسخه اصلی — web_dashboard_live.py در ریشه (داخلی، مستقیم اجرا نمی‌شود)
from early_warning import (
    MarketDataCollector,
    MarketDataStorage,
    AdaptiveNormalizer,
    MarketSnapshot,
    Trade,
    SellPressureDetector,
    BuyPressureDetector,
    AlertEngine,
    SpeedIndicatorEngine,
    ExcelReportGenerator,
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
  <button onclick="simDownloadReport()" title="دانلود ریپورت Excel این شبیه‌سازی" style="background:rgba(76,175,80,0.85);border:none;color:#fff;padding:7px 14px;border-radius:6px;cursor:pointer;font-weight:700;font-size:14px">📊 دانلود ریپورت</button>
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
function simDownloadReport() {
  // دانلود ریپورت Excel از شبیه‌سازی جاری (نماد + تاریخ فعلی)
  // سرور فایل را با Content-Disposition: attachment برمی‌گرداند
  window.location.href = '/sim/report';
}
setInterval(checkSim, 1000);
checkSim();"""


def _build_adaptive_html() -> str:
    """ساخت HTML تطبیقی با جایگزینی بخش‌های HTML_PAGE اصلی."""
    html = HTML_PAGE
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
        self._sim_results: list = []       # (sell_res, buy_res, combined, speed_res)
        self._sim_trades_by_time: dict[str, list[Trade]] = {}
        self._sim_alert_eng: AlertEngine | None = None  # برای تولید ریپورت
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
        speed_det = SpeedIndicatorEngine(self.cfg)
        prev = None
        hist: list[MarketSnapshot] = []
        for snap in snaps:
            sp = sp_det.evaluate(snap, prev)
            buy = buy_det.evaluate(snap, prev, hist)
            combined = alert_eng.evaluate(sp, buy) if (sp and buy) else None
            speed_res = speed_det.compute(snap, hist)
            self._sim_results.append((sp, buy, combined, speed_res))
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

        # نگهداری AlertEngine برای تولید ریپورت Sim (get_all_events)
        self._sim_alert_eng = alert_eng

        print(f"  شبیه‌سازی: {len(snaps)} نمونه برای «{self.symbol}» در تاریخ {self._sim_date}")

        # انتشار اولین نمونه برای نمایش فوری
        if snaps:
            self._publish_sim_rebuild()

    def generate_sim_report(self) -> Path | None:
        """تولید ریپورت Excel از داده‌های شبیه‌سازی جاری.

        از همان نماد و تاریخی که شبیه‌سازی روی آن اجرا شده استفاده می‌کند.
        فایل خروجی: reports/sim_report_{نماد}_{تاریخ}.xlsx
        در شیت Metadata، فیلد «نوع گزارش» = «شبیه‌سازی (Sim)» درج می‌شود.
        """
        if not self._sim_snaps:
            return None

        # جمع‌آوری داده‌ها از pre-compute
        snapshots = self._sim_snaps
        sp_results = [r[0] for r in self._sim_results if r[0]]
        acc_results = [r[1] for r in self._sim_results if r[1]]
        combined_states = [r[2] for r in self._sim_results if r[2]]
        alert_events = (self._sim_alert_eng.get_all_events()
                        if self._sim_alert_eng else [])

        # جمع‌آوری همه‌ی معاملات (از دیکشنری زمان→معاملات)
        trades: list[Trade] = []
        for tlist in self._sim_trades_by_time.values():
            trades.extend(tlist)

        # مسیر خروجی — شامل نماد، تاریخ و علامت Sim
        safe_sym = self.symbol.replace("/", "_").replace("\\", "_").replace(" ", "_")
        safe_date = self._sim_date.replace("/", "-")
        out_path = Path("reports") / f"sim_report_{safe_sym}_{safe_date}.xlsx"

        # تولید گزارش با نشانگر Sim
        gen = ExcelReportGenerator(self.cfg)
        gen.generate(
            symbol=self.symbol,
            snapshots=snapshots,
            sp_results=sp_results,
            acc_results=acc_results,
            combined_states=combined_states,
            alert_events=alert_events,
            output_path=out_path,
            trades=trades if trades else None,
            source="شبیه‌سازی (Sim)",
        )
        print(f"  📊 ریپورت Sim تولید شد: {out_path} ({len(snapshots)} نمونه)")
        return out_path

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
        sp, buy, combined, speed_res = self._sim_results[idx]
        # امتیاز تجمعی = مجموع امتیازها تا این موقعیت
        cum_sell = sum(r[0].total_score for r in self._sim_results[:idx + 1] if r[0])
        cum_buy = sum(r[1].total_score for r in self._sim_results[:idx + 1] if r[1])
        return {
            "available": True,
            "sell": sp.to_dict() if sp else None,
            "buy": buy.to_dict() if buy else None,
            "speed": speed_res.to_dict() if speed_res else None,
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

    اگر date_jalali داده شود، فقط آخرین snapshot آن تاریخ معاملاتی خوانده
    می‌شود (مرور یک روز خاص).
    """

    def __init__(self, cfg, symbol, interval=5, normalizer=None, storage=None,
                 date_jalali: str | None = None):
        super().__init__(cfg, mode="db", symbol=symbol,
                        interval=interval, normalizer=normalizer, storage=storage)
        self._db_date = date_jalali or ""

    def start(self):
        self._thread = threading.Thread(target=self._loop_db, daemon=True,
                                         name="db-monitor")
        self._thread.start()

    def _loop_db(self):
        """خواندن آخرین snapshot از بانک هر interval ثانیه.

        snapshot تکراری (همان timestamp) رد می‌شود تا delta بین نمونه‌ها
        همیشه واقعی باشد و فاکتورها (گستردگی، پول حقیقی و...) ثابت نمانند.
        """
        while not self._stop.is_set():
            try:
                if self.storage:
                    if self._db_date:
                        # آخرین snapshot یک تاریخ خاص
                        row = self.storage.conn.execute(
                            "SELECT * FROM snapshots WHERE symbol=? AND date_jalali=? "
                            "ORDER BY timestamp DESC LIMIT 1",
                            (self.symbol, self._db_date)).fetchone()
                        row = dict(row) if row else None
                    else:
                        row = self.storage.get_last_snapshot(self.symbol)
                    if row:
                        snap = MarketSnapshot.from_flat_dict(row)
                        # رد کردن snapshot تکراری — جلوگیری از delta=0
                        with self._lock:
                            last_ts = (self.history[-1].timestamp
                                       if self.history else "")
                        if snap.timestamp == last_ts:
                            self._stop.wait(self.interval)
                            continue
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
        # اگر همین حالت + نماد فعالی است، نیاز به تعویض نیست
        # (مگر sim یا db با تاریخ متفاوت)
        if (_current_mode == mode and _current_symbol == symbol and MONITOR is not None
                and not ((mode == "sim" or mode == "db") and date)):
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
                    normalizer=normalizer, storage=storage,
                    date_jalali=date)
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
  .hint {{ font-size: 12px; color: #666; margin: -8px 0 18px; padding: 8px 12px;
           background: #f0f4ff; border-radius: 8px; border-right: 3px solid #1565c0; }}
  .hint b {{ color: #1565c0; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>📊 داشبورد TSE Early Warning</h1>
  <div class="sub">یک سرور، سه حالت — حالت را از مسیر انتخاب کنید.</div>
  <div class="card">
    <label>نماد</label>
    <select id="symbol" onchange="loadDates()">
      <option value="{cur}" selected>— پیش‌فرض: {cur} —</option>
      {opts}
    </select>
    <label>تاریخ معاملاتی</label>
    <select id="date" onchange="updateLinks()">
      <option value="" selected>— آخرین (پیش‌فرض) —</option>
    </select>
    <p class="hint">📅 تاریخ فقط برای حالت <b>DB</b> و <b>Sim</b> اعمال می‌شود (Live همیشه زنده است).</p>
    <div class="modes">
      <a class="mode live" id="btn-live" href="/live">
        <span class="ico">📡</span> Live
        <span class="dsc">TSETMC زنده → نمایش + بانک</span>
      </a>
      <a class="mode db" id="btn-db" href="/db">
        <span class="ico">💾</span> DB
        <span class="dsc">آخرین داده از بانک (یا تاریخ انتخابی)</span>
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
function loadDates() {{
  const s = document.getElementById('symbol').value;
  const sel = document.getElementById('date');
  sel.innerHTML = '<option value="" selected>— آخرین (پیش‌فرض) —</option>';
  fetch('/api/sim/dates?symbol=' + encodeURIComponent(s))
    .then(r => r.json())
    .then(dates => {{
      if (Array.isArray(dates) && dates.length) {{
        dates.forEach(d => {{
          const o = document.createElement('option');
          o.value = d; o.textContent = d;
          sel.appendChild(o);
        }});
      }} else {{
        const o = document.createElement('option');
        o.value = ''; o.textContent = '— داده‌ای در بانک نیست —';
        o.disabled = true;
        sel.appendChild(o);
      }}
      updateLinks();
    }})
    .catch(() => {{ updateLinks(); }});
}}
function updateLinks() {{
  const s = document.getElementById('symbol').value;
  const d = document.getElementById('date').value;
  const dp = d ? '&date=' + encodeURIComponent(d) : '';
  document.getElementById('btn-live').href = '/live?symbol=' + encodeURIComponent(s);
  document.getElementById('btn-db').href   = '/db?symbol='   + encodeURIComponent(s) + dp;
  document.getElementById('btn-sim').href  = '/sim?symbol='  + encodeURIComponent(s) + dp;
}}
loadDates();
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
    """حالت بانک: خواندن لحظه‌ای آخرین داده از بانک.

    ?date=Y (اختیاری) → آخرین snapshot آن تاریخ معاملاتی.
    بدون date → آخرین snapshot کلی.
    """
    symbol = request.args.get("symbol") or _default_symbol()
    date = request.args.get("date") or ""
    res = switch_mode("db", symbol, date=date or None)
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
    """صفحه ویرایش درصد نوسان مجاز — سرو مستقیم فایل HTML کانفیگ."""
    html_path = ROOT / "config" / "tse_range_rules.html"
    if not html_path.exists():
        return ("فایل config/tse_range_rules.html وجود ندارد.", 404)
    return html_path.read_text(encoding="utf-8")

@app.route("/range-rules/save", methods=["POST"])
def range_rules_save():
    """ذخیره درصد نوسان مجاز ویرایش‌شده در فایل HTML."""
    from early_warning.isin_checker import parse_range_rules_html
    html_path = ROOT / "config" / "tse_range_rules.html"
    old_rules = parse_range_rules_html(html_path)

    # خواندن مقادیر جدید از فرم
    updated = {}
    for prefix in old_rules.keys():
        cat = request.form.get(f"cat_{prefix}", old_rules[prefix][0])
        pct_str = request.form.get(f"pct_{prefix}", str(old_rules[prefix][1]))
        try:
            pct = float(pct_str)
        except ValueError:
            return jsonify({"ok": False, "message": f"درصد نامعتبر برای {prefix}: {pct_str}"}), 400
        updated[prefix] = (cat, pct)

    # بازنویسی فایل HTML با مقادیر جدید (فرمت ویرایشگر با input fieldها)
    try:
        new_html = _build_range_rules_html(updated)
        html_path.write_text(new_html, encoding="utf-8")
        return jsonify({"ok": True, "message": "تغییرات ذخیره شد", "updated": len(updated)})
    except Exception as e:
        return jsonify({"ok": False, "message": f"خطا در ذخیره: {e}"}), 500

def _build_range_rules_html(rules: dict) -> str:
    """ساخت محتوای فایل HTML ویرایشگر از دیکشنری قوانین (با input fieldها)."""
    rows = []
    for prefix in sorted(rules.keys()):
        cat, pct = rules[prefix]
        rows.append(
            f'<tr>\n'
            f'  <td class="prefix">{prefix}</td>\n'
            f'  <td class="cat-cell"><input type="text" name="cat_{prefix}" value="{cat}" class="cat-input"></td>\n'
            f'  <td class="pct-cell"><input type="number" name="pct_{prefix}" value="{pct:g}" step="0.5" min="0" max="100" class="pct-input" data-prefix="{prefix}"> ٪</td>\n'
            f'</tr>'
        )
    rows_html = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="UTF-8">
<title>درصد نوسان مجاز بر اساس ISIN — ویرایشگر</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/rastikerdar/vazirmatn@v33.003/Vazirmatn-font-face.css">
<style>
body{{font-family:Vazirmatn,Tahoma,Arial,sans-serif;margin:30px;background:#f5f5f5}}
h1{{color:#1a5276;font-size:20px}}
form{{max-width:850px;margin:0 auto}}
table{{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1)}}
th,td{{border:1px solid #ddd;padding:10px 14px;text-align:center}}
th{{background:#1a5276;color:#fff;font-weight:bold}}
td.prefix{{font-family:monospace;font-weight:bold;color:#1a5276;font-size:15px}}
td.cat-cell{{text-align:right}}
td.pct-cell{{white-space:nowrap}}
.cat-input{{width:100%;padding:6px 8px;border:1px solid #ccc;border-radius:3px;font-family:inherit;font-size:14px}}
.pct-input{{width:70px;padding:6px 8px;border:1px solid #ccc;border-radius:3px;font-family:inherit;text-align:center;font-weight:bold;color:#c0392b;font-size:15px}}
tr:nth-child(even){{background:#f9f9f9}}
button{{background:#1a5276;color:#fff;border:none;padding:12px 35px;font-size:16px;border-radius:5px;cursor:pointer;font-family:inherit;margin:15px 0}}
button:hover{{background:#21618c}}
.note{{background:#fef9e7;border:1px solid #f9e79f;padding:12px 16px;margin:15px 0;border-radius:4px;font-size:13px;max-width:850px}}
.msg{{padding:10px 16px;margin:10px 0;border-radius:4px;max-width:850px}}
.msg.ok{{background:#e6f5ec;color:#0a8f3c}}
.msg.err{{background:#fdeaea;color:#c62828}}
</style>
</head>
<body>

<h1>ویرایشگر درصد نوسان مجاز — بر اساس پیشوند ISIN</h1>

<div class="note">
  برای تغییر درصد نوسان مجاز، فقط عدد درصد را در فیلد مربوطه ویرایش کنید
  و دکمه «ذخیره تغییرات» را بزنید.<br>
  تغییرات در همین فایل ذخیره می‌شوند و در اجرای بعدی برنامه اعمال می‌گردند.
</div>

<div id="msg" class="msg" style="display:none;"></div>

<form id="range-form" method="post" action="/range-rules/save">
<table>
<thead>
<tr><th>پیشوند ISIN</th><th>دسته نماد</th><th>نوسان مجاز</th></tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
<button type="submit">ذخیره تغییرات</button>
</form>

<script>
document.getElementById('range-form').addEventListener('submit', async function(e) {{
  e.preventDefault();
  const formData = new FormData(this);
  const msg = document.getElementById('msg');
  msg.style.display = 'none';
  try {{
    const resp = await fetch('/range-rules/save', {{method: 'POST', body: formData}});
    const data = await resp.json();
    if (data.ok) {{
      msg.className = 'msg ok';
      msg.textContent = '✓ ' + data.message + ' (' + data.updated + ' قانون)';
    }} else {{
      msg.className = 'msg err';
      msg.textContent = '⚠ ' + data.message;
    }}
    msg.style.display = 'block';
  }} catch(err) {{
    msg.className = 'msg err';
    msg.textContent = '⚠ خطا در ارتباط: ' + err;
    msg.style.display = 'block';
  }}
}});
</script>

</body>
</html>"""


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
/* نوار امتیاز سرعتی */
.sbar{direction:ltr;position:relative;height:22px;background:#eceff3;border-radius:5px;overflow:hidden;min-width:120px}
.sbar-fill{position:absolute;top:0;left:0;bottom:0;border-radius:5px;transition:width 0.4s}
.sbar-fill.down{background:var(--down-bg,#ffd0d0)}
.sbar-fill.mid{background:#ffe9c4}
.sbar-fill.up{background:var(--up-bg,#d0f5d0)}
.sbar-txt{position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#333;font-variant-numeric:tabular-nums}
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
/* خروجی موتور گروه E */
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
    <section class="panel" style="grid-column: span 2">
      <h2><span class="gnum">E</span> خروجی موتورهای تحلیلی</h2>
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

  <!-- سطر سوم: شاخص‌های سرعتی نردبان سفارش‌ها -->
  <section class="panel">
    <h2><span class="gnum">G</span> شاخص‌های سرعتی نردبان سفارش‌ها</h2>
    <div class="body" id="p-g"><div class="wait">در انتظار داده...</div></div>
  </section>

  <!-- سطر چهارم: نمودار روند قیمت -->
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
  const el = document.getElementById("p-c");
  if (!el) return;  // پنل C حذف شده — تابع بدون‌عمل
  const s = d.snapshot, der = d.derived;
  const vb = der.volume_vs_base_pct;
  const w = Math.min(100, vb||0);
  el.innerHTML = `
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

/* ---------- گروه E: خروجی موتورهای تحلیلی (فروش + خرید + classify) ---------- */
function renderE(d) {
  const el = document.getElementById("p-e");
  const eng = d.engines || {};
  if (!eng.available) {
    el.innerHTML = `<div class="wait">${eng.error ? "خطای موتور: " + eng.error : "در حال اجرای موتورهای تحلیلی..."}</div>`;
    return;
  }
  const sell = eng.sell || {};
  const buy = eng.buy || {};
  const comb = eng.combined || {};

  // رنگ بر اساس امتیاز
  const scoreColor = v => (v >= 65 ? "#c62828" : v >= 35 ? "#f9a825" : "#2e7d32");
  const sellS = sell.total_score || 0;
  const buyS = buy.total_score || 0;
  const sellPct = Math.min(100, sellS);
  const buyPct = Math.min(100, buyS);

  // بنر طبقه‌بندی
  const cls = eng.classification || "—";
  const clsColor = cls.includes("تقابل") ? "#6a1b9a"
    : cls.includes("فشار فروش") ? "#c62828"
    : cls.includes("فشار خرید") ? "#2e7d32"
    : cls.includes("هشدار") ? "#f9a825"
    : cls.includes("مراقبت") ? "#fb8c00"
    : "#5a6b7f";

  // ردیف‌های شاخص‌ها (هر دو موتور در یک جدول)
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
  }

  el.innerHTML = `
    <div style="padding:6px 8px;background:${clsColor};color:#fff;text-align:center;font-weight:bold;font-size:12px;border-radius:4px;margin-bottom:6px">
      ${cls}
    </div>
    <div style="display:flex;gap:6px;margin-bottom:6px">
      <div style="flex:1;padding:6px;border:1px solid #eee;border-radius:6px;text-align:center">
        <div style="font-size:11px;color:#888">موتور فروش</div>
        <div style="font-size:22px;font-weight:bold;color:${scoreColor(sellS)}">${N(sellS, 1)}</div>
        <div style="height:8px;background:#f0f0f0;border-radius:4px;overflow:hidden;margin:4px 0">
          <div style="height:100%;width:${sellPct}%;background:${scoreColor(sellS)}"></div>
        </div>
        <div style="font-size:10px">${eng.sell_tier || '—'} ${sell.engine_status === 'warming_up' ? '⚠ گرم‌شدن' : ''}</div>
      </div>
      <div style="flex:1;padding:6px;border:1px solid #eee;border-radius:6px;text-align:center">
        <div style="font-size:11px;color:#888">موتور خرید</div>
        <div style="font-size:22px;font-weight:bold;color:${scoreColor(buyS)}">${N(buyS, 1)}</div>
        <div style="height:8px;background:#f0f0f0;border-radius:4px;overflow:hidden;margin:4px 0">
          <div style="height:100%;width:${buyPct}%;background:${scoreColor(buyS)}"></div>
        </div>
        <div style="font-size:10px">${eng.buy_tier || '—'} ${buy.engine_status === 'warming_up' ? '⚠ گرم‌شدن' : ''}</div>
      </div>
    </div>
    <div style="display:flex;gap:6px;margin-bottom:6px;padding:6px;background:#f8f9fa;border-radius:6px;border:1px dashed #bbb">
      <div style="flex:1;text-align:center">
        <div style="font-size:10px;color:#666">مجموع امتیاز فروش (از ابتدای روز)</div>
        <div style="font-size:18px;font-weight:bold;color:${scoreColor(eng.cumulative_sell_score||0)}">${N(eng.cumulative_sell_score,1)}</div>
      </div>
      <div style="flex:1;text-align:center">
        <div style="font-size:10px;color:#666">مجموع امتیاز خرید (از ابتدای روز)</div>
        <div style="font-size:18px;font-weight:bold;color:${scoreColor(eng.cumulative_buy_score||0)}">${N(eng.cumulative_buy_score,1)}</div>
      </div>
      <div style="flex:0 0 auto;text-align:center;align-self:center">
        <div style="font-size:10px;color:#666">تعداد نمونه</div>
        <div style="font-size:16px;font-weight:bold;color:#333">${eng.cumulative_samples||0}</div>
      </div>
    </div>
    <table class="ttable" style="font-size:10px">
      <thead><tr>
        <th colspan="4" style="background:#fdecea;color:#c62828">شاخص‌های فروش</th>
        <th colspan="4" style="background:#e8f5e9;color:#2e7d32">شاخص‌های خرید</th>
      </tr><tr>
        <th>شاخص</th><th>امتیاز</th><th>نرمال</th><th>خام/وضع</th>
        <th>شاخص</th><th>امتیاز</th><th>نرمال</th><th>خام/وضع</th>
      </tr></thead>
      <tbody>${factorRows}</tbody>
    </table>
    ${(sell.data_quality_warning || buy.data_quality_warning) ? `<div class="hint" style="color:#c62828">⚠ ${sell.data_quality_warning || buy.data_quality_warning}</div>` : ""}
    <div class="hint">۱۲ شاخص مستقل — فروش (قرمز) و خرید (سبز). نرمال‌سازی آستانه ثابت (Phase 1).</div>`;
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

/* ---------- پنل G: شاخص‌های سرعتی ---------- */
function renderSpeed(d) {
  const el = document.getElementById("p-g");
  if (!el) return;
  const sp = (d.engines && d.engines.speed) || null;
  if (!sp || !sp.is_available) {
    el.innerHTML = '<div class="wait">' + (sp ? (sp.notes||[]).join(" — ") || "در انتظار پنجره نمونه کامل..." : "در انتظار داده...") + '</div>';
    return;
  }
  // نوار امتیاز (۰–۱۰۰)
  function bar(score) {
    if (score == null) return "—";
    const v = Math.max(0, Math.min(100, score));
    const cls = v >= 67 ? "down" : v >= 34 ? "mid" : "up";
    return `<div class="sbar"><div class="sbar-fill ${cls}" style="width:${v}%"></div><span class="sbar-txt">${N(v,1)}</span></div>`;
  }
  const notesHtml = (sp.notes && sp.notes.length)
    ? '<div class="hint">' + sp.notes.join(" — ") + '</div>' : "";
  el.innerHTML = `
    <table class="kv">
      ${kv("امتیاز فشار سرعتی (فروش)", bar(sp.speed_pressure_score))}
      ${kv("امتیاز جذب سرعتی (خرید)", bar(sp.speed_absorption_score))}
      ${kv("نرخ تخلیه تقاضا", sp.demand_depletion_rate != null ? N(sp.demand_depletion_rate,4) : "—")}
      ${kv("نرخ رشد عرضه", sp.supply_growth_rate != null ? N(sp.supply_growth_rate,4) : "—")}
      ${kv("نسبت جذب", sp.absorption_ratio != null ? N(sp.absorption_ratio,4) : "—")}
      ${kv("نرمال تخلیه تقاضا", sp.demand_depletion_norm != null ? N(sp.demand_depletion_norm*100,1)+"٪" : "—")}
      ${kv("نرمال رشد عرضه", sp.supply_growth_norm != null ? N(sp.supply_growth_norm*100,1)+"٪" : "—")}
      ${kv("نرمال جذب", sp.absorption_norm != null ? N(sp.absorption_norm*100,1)+"٪" : "—")}
      ${kv("حجم نردبان خرید (ابتدا→اکنون)", N(sp.buy_ladder_start) + " → " + N(sp.buy_ladder_now))}
      ${kv("حجم نردبان فروش (ابتدا→اکنون)", N(sp.sell_ladder_start) + " → " + N(sp.sell_ladder_now))}
      ${kv("حجم معاملات پنجره", N(sp.executed_volume_window))}
      ${kv("تعداد نمونه پنجره", N(sp.window_samples))}
    </table>
    ${notesHtml}`;
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
    renderE(d);
    renderB(d);
    renderD(d);
    renderF(d);
    renderSpeed(d);
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


@app.route("/sim/report")
def sim_report_route():
    """تولید و دانلود ریپورت Excel از شبیه‌سازی جاری.

    از نماد و تاریخی که شبیه‌سازی روی آن اجرا شده استفاده می‌کند.
    فایل خروجی: sim_report_{نماد}_{تاریخ}.xlsx
    """
    if not MONITOR or not isinstance(MONITOR, SimulationAdaptiveMonitor):
        return jsonify({"error": "شبیه‌سازی فعال نیست. ابتدا یک نماد و تاریخ انتخاب کنید."}), 400
    try:
        path = MONITOR.generate_sim_report()
        if path is None:
            return jsonify({"error": "داده‌ای برای تولید گزارش وجود ندارد."}), 400
        return send_file(
            str(path),
            as_attachment=True,
            download_name=path.name,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"خطا در تولید گزارش: {e}"}), 500


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
