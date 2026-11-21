"""
run_live.py — ⚠ ماژول داخلی (مستقیم اجرا نکنید)
اجرا با: python run_multi.py  (این فایل را به‌صورت subprocess فراخوانی می‌کند)

اجرای ماژول هشدار زودهنگام با داده واقعی TSETMC در بازار زنده.

این نسخه به جای تولید گزارش در پایان، داده‌ها را زنده در SQLite
ذخیره می‌کند و هر نمونه را هم‌زمان تحلیل می‌کند.

نحوه اجرا (Windows 10):
    cd C:\\TSE_Screener
    python run_live.py

نمونه‌برداری و تحلیل (نسخه ۱.۲):
  - تابلو هر `sampling.interval_seconds` ثانیه (پیش‌فرض ۵ ثانیه) جمع‌آوری
    و در SQLite ذخیره می‌شود (برای داشبورد زنده و گروه E)
  - موتورهای تحلیلی با گام `sampling.analysis_interval_seconds`
    (پیش‌فرض ۶۰ ثانیه) اجرا می‌شوند تا کالیبراسیون آستانه‌ها که برای
    نمونه‌های ۶۰ ثانیه‌ای تنظیم شده حفظ شود
  - حداکثر نمونه‌ها به‌صورت خودکار پوشش کامل جلسه (08:45 تا 12:30) است

زمان‌بندی پیشنهادی:
    08:45-09:00  پیش‌گشایش (دریافت و ذخیره، بدون موتورها)
    09:00-12:30  معاملات پیوسته (دریافت + ذخیره + موتورها + هشدار)
    12:30+       ذخیره نهایی، کنترل نقص‌ها، تولید گزارش
"""

from __future__ import annotations

import sys
import json
import time
import sqlite3
import argparse
import signal
from datetime import datetime, date
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import (
    DataValidator,
    SellPressureDetector,
    BuyPressureDetector,
    AlertEngine,
    SpeedIndicatorEngine,
    ExcelReportGenerator,
    MarketDataStorage,
    AdaptiveNormalizer,
    MarketPhase,
    MarketSnapshot,
    Trade,
    load_range_rules,
    get_symbol_category,
    get_category_percent,
    compute_daily_params,
    to_jalali,
)
from early_warning.data_collector import BestLimitRow
from early_warning.derived_compute import (
    enrich_series, enrich_snapshot, aggregate_interval, _bucket_start,
)
from early_warning.market_detector import in_trading_window, tehran_now


# ---------------------------------------------------------------------------
# بانک پردازش‌شده: نویسندهٔ derived_samples / aggregate_5min / aggregate_15min
# و تولید ریپورت Excel (فقط در پایان جلسه).
#
#   - هر ۳۰ث (interval): یک ردیف derived_samples از snapshotِ enriched نوشته می‌شود.
#   - در مرز ۵د/۱۵د: فقط ردیف aggregate_* برای بازهٔ تکمیل‌شده نوشته می‌شود
#     (سریع، دستور DB). ساخت اکسل درون‌حلقه‌ای کنسل شد چون باعث تأخیر fetch
#     می‌شد؛ ریپورت اکسل فقط در پایان جلسه تولید می‌شود.
#   - پایان جلسه: ریپورت نهایی (پیش‌فرض) — تنها زمان ساخت اکسل.
#   - درخواستی (triggers/report_{نماد}): فعلاً غیرفعال؛ برای فعال‌سازی بلوک
#     مربوطه در گام ۳.۸ را از کامنت خارج کنید.
# ---------------------------------------------------------------------------

# فاصله‌های تجمیعی (ثانیه)
AGG_5MIN = 300
AGG_15MIN = 900


def _composite_from_combined(combined) -> tuple[float | None, str | None]:
    """استخراج امتیاز ترکیبی و سطح آلارم از CombinedState موتور."""
    if combined is None:
        return None, None
    try:
        score = max(float(getattr(combined, "sell_score", 0) or 0),
                    float(getattr(combined, "buy_score", 0) or 0))
    except Exception:
        score = None
    alert = getattr(combined, "alert", None)
    level = None
    if alert is not None:
        level = getattr(getattr(alert, "level", None), "value", None)
    if level is None:
        level = getattr(combined, "classification", None)
    return score, level


def _generate_excel_from_bank(storage, config, symbol, normalizer, out_path) -> Path:
    """تولید ریپورت Excel از بانک (خام + enriched در حافظه) — بدون نیاز به وب.

    بازخوانی همهٔ snapshotها و معاملات از بانک خام، enrich در حافظه، اجرای مجدد
    موتورها و ساخت Excel. برای ریپورت‌های دوره‌ای، درخواستی و پایان جلسه به‌کار
    می‌رود. بانک خام دست‌نخورده می‌ماند.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    db_rows = storage.get_snapshots_for_symbol(symbol)
    db_snaps = [MarketSnapshot.from_flat_dict(r) for r in db_rows]
    db_trade_rows = storage.get_trades_for_symbol(symbol)
    db_trades = [
        Trade(
            trade_time=t.get("trade_time", ""),
            trade_price=float(t.get("trade_price") or 0),
            trade_volume=int(t.get("trade_volume") or 0),
            trade_id=t.get("trade_id"),
            aggressor_side=t.get("aggressor_side"),
        )
        for t in db_trade_rows
    ]
    db_trades_by_time: dict[str, list[Trade]] = {}
    for tr in db_trades:
        if tr.trade_time:
            db_trades_by_time.setdefault(tr.trade_time, []).append(tr)
    enrich_series(db_snaps, db_trades_by_time)

    if not db_snaps:
        return out_path  # بانک خالی → چیزی برای گزارش نیست

    replay_sp = SellPressureDetector(config, normalizer=normalizer)
    replay_buy = BuyPressureDetector(config, normalizer=normalizer)
    replay_alert = AlertEngine(config)
    excel_sp, excel_buy, excel_combined = [], [], []
    prev = None
    hist: list = []
    for snap in db_snaps:
        sp = replay_sp.evaluate(snap, prev)
        buy = replay_buy.evaluate(snap, prev, hist)
        excel_sp.append(sp)
        excel_buy.append(buy)
        excel_combined.append(replay_alert.evaluate(sp, buy))
        prev = snap
        hist.append(snap)
        hist = hist[-36:]

    gen = ExcelReportGenerator(config)
    gen.generate(
        symbol=symbol,
        snapshots=db_snaps,
        sp_results=excel_sp,
        acc_results=excel_buy,
        combined_states=excel_combined,
        alert_events=replay_alert.get_all_events(),
        output_path=out_path,
        trades=db_trades,
    )
    return out_path


def _flush_aggregate(storage, enriched_snaps, symbol, date_jalali,
                     bucket_seconds, table, bucket_start) -> None:
    """تجمیع enriched_snaps متعلق به bucket_start و درج در جدول aggregate_*.

    enriched_snaps باید از پیش enrich شده باشند (فیلدهای مشتق پر شده).
    """
    group = [s for s in enriched_snaps
             if _bucket_start(getattr(s, "tehran_time", ""), bucket_seconds) == bucket_start]
    if not group:
        return
    rows = aggregate_interval(group, bucket_seconds, symbol, date_jalali)
    for r in rows:
        if r.get("bucket_start") == bucket_start:
            storage.insert_aggregate(table, r)


def _check_report_trigger(symbol) -> bool:
    """اگر فایل triggers/report_{نماد} وجود داشت، آن را مصرف (حذف) و True برگردان."""
    trig = ROOT / "triggers" / f"report_{symbol}"
    if trig.exists():
        try:
            trig.unlink()
        except OSError:
            pass
        return True
    return False


def _report_path(symbol, tag: str) -> Path:
    """مسیر ریپورت Excel با تگ (5min/15min/final/snapshot)."""
    date_jalali = to_jalali(date.today())
    safe_tag = tag or "report"
    return ROOT / "reports" / f"early_warning_report_{symbol}_{date_jalali}_{safe_tag}.xlsx"


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    print(f"📂 فایل پیکربندی: {cfg_path}")
    print(f"   وجود دارد: {cfg_path.exists()}")
    if not cfg_path.exists():
        print(f"❌ فایل پیکربندی پیدا نشد!")
        sys.exit(1)
    with open(cfg_path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    print(f"   نماد در پیکربندی: {cfg['test_symbol']['name']} (کد: {cfg['test_symbol']['ins_code']})")
    return cfg


def parse_args():
    p = argparse.ArgumentParser(description="TSE Early Warning - Live Mode (SQLite)")
    p.add_argument("--symbol", default=None, help="نام نماد (اگر ندهید، از پیکربندی استفاده می‌شود)")
    p.add_argument("--ins-code", default=None, help="کد TSETMC (اگر ندهید، از پیکربندی استفاده می‌شود)")
    p.add_argument("--interval", type=int, default=None,
                   help="فاصله نمونه‌برداری (ثانیه) - پیش‌فرض: sampling.interval_seconds پیکربندی (۵)")
    p.add_argument("--analysis-interval", type=int, default=None,
                   help="فاصله اجرای موتورهای تحلیلی (ثانیه) - پیش‌فرض: sampling.analysis_interval_seconds پیکربندی (۶۰)")
    p.add_argument("--max-samples", type=int, default=None,
                   help="حداکثر تعداد نمونه - پیش‌فرض: پوشش کامل جلسه معاملاتی")
    p.add_argument("--db", default="data/early_warning_live.sqlite", help="مسیر فایل SQLite")
    p.add_argument("--output", default="reports/early_warning_report_live.xlsx")
    p.add_argument("--source", default="raw", choices=["raw"],
                   help="منبع داده: raw (پیش‌فرض) — بانک‌های خام raw_collector؛ اتصال لایو TSETMC از این برنامه حذف شده است")
    p.add_argument("--replay", action="store_true",
                   help="از اولین ردیف امروز در بانک خام شروع کن (بازسازی بانک قدیمی از خام؛ برای جلوگیری از ردیف تکراری در بانکِ با سابقه، دیتابیس تازه بده)")
    p.add_argument("--prompt", action="store_true",
                   help="از کاربر بپرسد کدام نماد (پیش‌فرض: بدون پرسش از پیکربندی)")
    return p.parse_args()


def load_config_with_prompt(args) -> dict:
    """
    بارگذاری پیکربندی و انتخاب نماد.

    رفتار:
      - پیش‌فرض: از نماد فعلی پیکربندی استفاده می‌کند (بدون پرسش)
      - با --prompt: از کاربر می‌پرسد
      - با --symbol X: جستجوی X و استفاده از آن
      - با --symbol X --ins-code Y: مستقیم
    """
    config = load_config()

    # حالت ۱: نماد و کد داده شده → مستقیم
    if args.symbol and args.ins_code:
        return config

    # حالت ۲: فقط symbol داده شده → کد از config/symbols.json (منبع خام، بدون API)
    if args.symbol and not args.ins_code:
        entry = _symbols_config().get(args.symbol)
        if entry and entry.get("ins_code"):
            args.ins_code = str(entry["ins_code"])
            print(f"✓ کد از config/symbols.json: {args.ins_code}")
        else:
            print(f"❌ نماد '{args.symbol}' در config/symbols.json نیست!")
            print("   منبع داده خام است؛ نماد را با raw_collector به کانفیگ اضافه کنید.")
            sys.exit(1)
        return config

    # حالت ۳: --prompt داده شده → منوی تعاملی
    if args.prompt:
        return interactive_symbol_selection(args, config)

    # حالت ۴ (پیش‌فرض): بدون پرسش، از پیکربندی استفاده کن
    args.symbol = config["test_symbol"]["name"]
    args.ins_code = config["test_symbol"]["ins_code"]
    print(f"📋 نماد از پیکربندی: {args.symbol} (کد: {args.ins_code})")
    print(f"💡 برای تغییر: در مرورگر داشبورد نماد جدید را انتخاب کنید")
    print(f"   یا از پارامتر --symbol استفاده کنید")
    return config


def interactive_symbol_selection(args, config) -> dict:
    """منوی تعاملی انتخاب نماد (فقط با --prompt)."""
    current_symbol = config["test_symbol"]["name"]
    current_code = config["test_symbol"]["ins_code"]

    print("=" * 70)
    print("  انتخاب نماد برای پایش زنده")
    print("=" * 70)
    print(f"\n📝 نماد فعلی: {current_symbol} (کد: {current_code})")
    print()
    print("گزینه‌ها:")
    print(f"  1) استفاده از نماد فعلی ({current_symbol})")
    print(f"  2) وارد کردن نماد جدید")
    print(f"  3) خروج")
    print()

    while True:
        try:
            choice = input("انتخاب شما (1/2/3): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nخروج...")
            sys.exit(0)

        if choice == "1":
            args.symbol = current_symbol
            args.ins_code = current_code
            print(f"\n✓ نماد: {args.symbol}")
            break
        elif choice == "2":
            try:
                new_symbol = input("نام نماد جدید (مثلا ریتون، دابور، فملی): ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nخروج...")
                sys.exit(0)
            if not new_symbol:
                print("⚠ نام نماد خالی است!")
                continue

            entry = _symbols_config().get(new_symbol)
            if not (entry and entry.get("ins_code")):
                print(f"❌ نماد '{new_symbol}' در config/symbols.json نیست!")
                print("   منبع داده خام است؛ نماد را با raw_collector به کانفیگ اضافه کنید.")
                continue

            args.symbol = new_symbol
            args.ins_code = str(entry["ins_code"])
            print(f"\n✓ نماد انتخاب شده: {new_symbol} (کد از symbols.json: {args.ins_code})")
            save_symbol_to_config(config, new_symbol, args.ins_code)
            break
        elif choice == "3":
            print("خروج...")
            sys.exit(0)
        else:
            print("⚠ انتخاب نامعتبر! 1، 2 یا 3 وارد کنید.")

    return config


def save_symbol_to_config(config: dict, symbol: str, ins_code: str):
    """ذخیره نماد انتخاب‌شده در فایل پیکربندی."""
    try:
        config["test_symbol"]["name"] = symbol
        config["test_symbol"]["ticker"] = symbol
        config["test_symbol"]["ins_code"] = str(ins_code)
        # اگر قیمت پایه تغییر نکرده، همان بماند
        cfg_path = ROOT / "config" / "warning_thresholds.json"
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print(f"✓ نماد '{symbol}' در پیکربندی ذخیره شد (برای دفعات بعد)")
    except Exception as e:
        print(f"⚠ خطا در ذخیره پیکربندی: {e}")


# ---------------------------------------------------------------------------
# منبع دادهٔ خام — بانک‌های raw_*.sqlite نوشته‌شده توسط raw_collector.py
# (raw_collector تنها مصرف‌کنندهٔ API لایو است؛ این برنامه دیگر به TSETMC
# وصل نمی‌شود. نقشهٔ فیلدها ۱:۱ با ساختار MarketSnapshot قدیم است تا
# اعتبارسنجی، موتورها، ذخیره و وب‌ها بدون تغییر کار کنند.)
# ---------------------------------------------------------------------------

def _symbols_config() -> dict:
    """بارگذاری config/symbols.json (نام → رکورد کامل با تایم‌کاری و کد)."""
    path = ROOT / "config" / "symbols.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {s["name"]: s for s in data.get("symbols", [])}


def _raw_yesterday_price(symbol: str) -> float:
    """آخرین yesterday_price غیرصفر از بانک خام نماد (برای پارامترهای ثابت روز)."""
    raw_db = ROOT / "data" / "raw" / f"raw_{symbol}.sqlite"
    if not raw_db.exists():
        return 0.0
    con = sqlite3.connect(str(raw_db))
    try:
        r = con.execute(
            "SELECT yesterday_price FROM raw_snapshots "
            "WHERE yesterday_price IS NOT NULL AND yesterday_price > 0 "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        con.close()
    return float(r[0]) if r else 0.0


def _raw_pos_path(symbol: str) -> Path:
    return ROOT / "data" / "raw" / f".pos_{symbol}.json"


def _init_raw_position(symbol: str, replay: bool = False) -> int:
    """
    مقداردهی نشانگرِ خواندن بانک خام.
    - فایل وضعیت (.pos_{نماد}.json) متعلق به امروز → ادامه از آخرین ردیف
      مصرف‌شده (ری‌استارت پل، ردیف‌های امروز را دوباره پردازش نمی‌کند).
    - روز جدید یا بدون وضعیت → از اولین ردیف امروز شروع می‌شود.
    - --replay → وضعیت نادیده گرفته می‌شود و از اولین ردیف امروز بازسازی می‌کند.
    """
    today = to_jalali(date.today())
    path = _raw_pos_path(symbol)
    if not replay and path.exists():
        try:
            st = json.loads(path.read_text(encoding="utf-8"))
            if st.get("date") == today:
                return int(st.get("last_id", 0))
        except Exception:
            pass
    raw_db = ROOT / "data" / "raw" / f"raw_{symbol}.sqlite"
    if not raw_db.exists():
        return 0
    con = sqlite3.connect(str(raw_db))
    try:
        r = con.execute(
            "SELECT COALESCE(MAX(id), 0) FROM raw_snapshots WHERE date_jalali < ?",
            (today,)
        ).fetchone()
    finally:
        con.close()
    return int(r[0]) if r else 0


def _save_raw_position(symbol: str, last_id: int):
    try:
        _raw_pos_path(symbol).write_text(json.dumps({
            "date": to_jalali(date.today()),
            "last_id": int(last_id),
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _raw_pending(symbol: str, last_id: int) -> int:
    """تعداد ردیف‌های تازهٔ امروزِ بانک خام که هنوز مصرف نشده‌اند."""
    raw_db = ROOT / "data" / "raw" / f"raw_{symbol}.sqlite"
    if not raw_db.exists():
        return 0
    today = to_jalali(date.today())
    con = sqlite3.connect(str(raw_db))
    try:
        r = con.execute(
            "SELECT COUNT(*) FROM raw_snapshots WHERE id > ? AND date_jalali = ?",
            (last_id, today)
        ).fetchone()
    finally:
        con.close()
    return int(r[0]) if r else 0


def _raw_phase(trading_hours: dict) -> str:
    """فاز بازار از ساعت تهران — همان معنای _detect_market_phase قدیم."""
    hm = tehran_now().strftime("%H:%M")
    for key, val in (("pre_open", MarketPhase.PRE_OPEN.value),
                     ("continuous", MarketPhase.CONTINUOUS.value)):
        w = (trading_hours or {}).get(key) or []
        if len(w) == 2 and w[0] <= hm <= w[1]:
            return val
    return MarketPhase.CLOSED.value


def fetch_from_raw(symbol: str, prev_snap, fixed_range: dict,
                   trading_hours: dict, last_id: int):
    """
    منبع دادهٔ خام: خواندن نزدیک‌ترین ردیفِ تازهٔ امروز از بانک خام نماد و
    تبدیل ۱:۱ به MarketSnapshot — دقیقاً همان نقشی که collector.collect در
    حالت لایو داشت. بقیهٔ حلقه (اعتبارسنجی، موتورها، ذخیره، لایهٔ derived)
    دست‌نخورده می‌ماند؛ محاسبات مشتق همان‌طور که قبل بود در derived_compute
    روی همین snapshot انجام می‌شود.

    - معاملات ریز (trades) در بانک خام نیست → همیشه لیست خالی (تصمیم کاربر).
    - data_status همان قاعدهٔ قدیم: ok / partial / stale (پاسخ تکراری CDN).
    - نشانگر خواندن در data/raw/.pos_{نماد}.json ذخیره می‌شود.

    بازگرداندن: (snap یا None، []، آخرین id مصرف‌شده)
    """
    raw_db = ROOT / "data" / "raw" / f"raw_{symbol}.sqlite"
    if not raw_db.exists():
        return None, [], last_id
    today = to_jalali(date.today())
    con = sqlite3.connect(str(raw_db))
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            "SELECT * FROM raw_snapshots WHERE id > ? AND date_jalali = ? "
            "ORDER BY id LIMIT 1",
            (last_id, today)
        ).fetchone()
        if row is None:
            return None, [], last_id
        rid = int(row["id"])

        def g(key, default=0):
            v = row[key]
            return default if v is None else v

        yp = float(g("yesterday_price") or 0)
        last_p = float(g("last_price") or 0)
        close_p = float(g("close_price") or 0)
        open_p = float(g("open_price") or 0)
        buy_rows, sell_rows = [], []
        for i in range(1, 6):
            bp = float(g(f"buy_price_{i}") or 0)
            if bp > 0:
                buy_rows.append(BestLimitRow(
                    price=bp, volume=int(g(f"buy_volume_{i}")),
                    order_count=max(1, int(g(f"buy_orders_{i}")))))
            sp = float(g(f"sell_price_{i}") or 0)
            if sp > 0:
                sell_rows.append(BestLimitRow(
                    price=sp, volume=int(g(f"sell_volume_{i}")),
                    order_count=max(1, int(g(f"sell_orders_{i}")))))
        snap = MarketSnapshot(
            date_jalali=row["date_jalali"] or "",
            timestamp=row["fetch_time"] or "",
            tehran_time=row["fetch_hms"] or "",
            symbol=symbol,
            ins_code=str(row["ins_code"] or ""),
            market_phase=_raw_phase(trading_hours),
            symbol_status=row["api_symbol_status"] or "allowed",
            source_update_time=row["fetch_time"] or "",
            data_status="ok" if last_p > 0 else "partial",
            # همان زنجیرهٔ fallback حالت لایو (collect): last → close → دیروز
            last_price=last_p or close_p or yp,
            close_price=close_p or yp,
            open_price=open_p or yp,
            yesterday_price=yp,
            daily_high=float(g("daily_high") or 0),
            daily_low=float(g("daily_low") or 0),
            min_allowed_price=float((fixed_range or {}).get("min_allowed_price", 0) or 0),
            max_allowed_price=float((fixed_range or {}).get("max_allowed_price", 0) or 0),
            base_volume=0,  # حجم مبنا در بانک خام نیست (هیچ موتوری از آن استفاده نمی‌کند)
            best_buy_price=float(g("buy_price_1") or 0),
            best_buy_volume=int(g("buy_volume_1") or 0),
            best_sell_price=float(g("sell_price_1") or 0),
            best_sell_volume=int(g("sell_volume_1") or 0),
            buy_rows=buy_rows,
            sell_rows=sell_rows,
            buy_order_count=sum(r.order_count for r in buy_rows),
            sell_order_count=sum(r.order_count for r in sell_rows),
            total_volume=int(g("trade_volume") or 0),
            total_value=float(g("trade_value") or 0) or (last_p * int(g("trade_volume") or 0)),
            total_trade_count=int(g("trade_count") or 0),
            real_buy_volume=int(g("ct_real_buy_volume") or 0),
            real_sell_volume=int(g("ct_real_sell_volume") or 0),
            legal_buy_volume=int(g("ct_legal_buy_volume") or 0),
            legal_sell_volume=int(g("ct_legal_sell_volume") or 0),
            real_buy_count=int(g("ct_real_buy_count") or 0),
            real_sell_count=int(g("ct_real_sell_count") or 0),
            legal_buy_count=int(g("ct_legal_buy_count") or 0),
            legal_sell_count=int(g("ct_legal_sell_count") or 0),
        )
        # تشخیص پاسخ تکراری CDN — همان قاعدهٔ حالت لایو
        if (prev_snap is not None
                and snap.market_phase == MarketPhase.CONTINUOUS.value
                and snap.total_volume == prev_snap.total_volume
                and snap.total_trade_count == prev_snap.total_trade_count
                and snap.last_price == prev_snap.last_price
                and snap.total_volume > 0):
            snap.data_status = "stale"
        _save_raw_position(symbol, rid)
        return snap, [], rid
    finally:
        con.close()


def load_price_range(args, config: dict, storage):
    """
    محاسبه، ذخیره و بارگذاری پارامترهای ثابت روز — یک بار در ابتدای اجرا.

    مراحل:
      ۱. دسته نماد از config/symbol_categories.json (نگاشت دستی) خوانده می‌شود
      ۲. درصد مجاز از config/tse_range_rules.json خوانده می‌شود
      ۳. yesterday_price از آخرین ردیف بانک خام نماد خوانده می‌شود
      ۴. min/max_allowed_price = yesterday_price × (1 ± pct/100) محاسبه می‌شود
      ۵. مقادیر در جدول daily_params بانک ذخیره می‌شوند (یک ردیف در روز)
      ۶. مقادیر ثابت در config['test_symbol']['fixed_price_range'] تزریق می‌شوند

    این مقادیر در طول روز ثابت می‌مانند و در هر رکورد snapshot تکرار نمی‌شوند.
    data_collector در هر نمونه فقط fixed_price_range را از پیکربندی می‌خواند.

    fallback: اگر دسته نماد در symbol_categories.json نبود، هشدار می‌دهد و
    از limit_percent پیکربندی استفاده می‌کند.
    """
    symbol = args.symbol or config.get("test_symbol", {}).get("name", "")
    ins_code = args.ins_code or config.get("test_symbol", {}).get("ins_code", "")
    config_dir = ROOT / "config"
    if not symbol:
        return

    print("─" * 60)
    print("  محاسبه پارامترهای ثابت روز (یک بار، ثابت برای کل جلسه)")
    print("─" * 60)

    # ── ۱. دسته نماد از symbol_categories.json (دستی) ──
    category = get_symbol_category(symbol, config_dir)
    if not category:
        print(f"  ⚠ نماد «{symbol}» در config/symbol_categories.json یافت نشد.")
        print(f"    لطفاً دسته این نماد را در فایل اضافه کنید.")
        print(f"    دسته‌های موجود در tse_range_rules.json:")
        for r in load_range_rules(config_dir):
            print(f"      • {r['cat']} ({r['pct']}%)")
        print(f"  ⚠ از limit_percent پیکربندی استفاده می‌شود.")
        print("─" * 60)
        return

    # ── ۲. درصد مجاز از tse_range_rules.json ──
    pct = get_category_percent(category, config_dir)
    if pct is None:
        print(f"  ⚠ دسته «{category}» در tse_range_rules.json یافت نشد.")
        print(f"  ⚠ از limit_percent پیکربندی استفاده می‌شود.")
        print("─" * 60)
        return

    print(f"  ✓ نماد: {symbol}")
    print(f"  ✓ دسته (از symbol_categories.json): {category}")
    print(f"  ✓ درصد مجاز (از tse_range_rules.json): {pct}%")

    # ── ۳. yesterday_price از بانک خام (منبع داده = raw_collector، بدون API) ──
    yesterday_price = _raw_yesterday_price(symbol) if ins_code else 0.0
    if yesterday_price <= 0:
        base = float(config.get("test_symbol", {}).get("base_price", 0) or 0)
        if base > 0:
            yesterday_price = base
            print(f"  ⚠ yesterday_price از بانک خام دریافت نشد — استفاده از base_price: {yesterday_price:,.0f}")
        else:
            print("  [!] قیمت دیروز دریافت نشد — محاسبه کف/سقف ممکن نیست.")
            print("─" * 60)
            return
    else:
        print(f"  ✓ قیمت دیروز (yesterday_price): {yesterday_price:,.0f}")

    # ── ۴. محاسبه min/max ──
    params = compute_daily_params(symbol, yesterday_price, config_dir)
    if not params:
        print("  [!] محاسبه پارامترها ناموفق بود.")
        print("─" * 60)
        return

    print(f"  ✓ کف مجاز: {params['min_allowed_price']:,.0f}")
    print(f"  ✓ سقف مجاز: {params['max_allowed_price']:,.0f}")

    # ── ۵. ذخیره در جدول daily_params (یک ردیف در روز) ──
    date_jalali = to_jalali(date.today())
    daily_record = {
        "date_jalali": date_jalali,
        "symbol": symbol,
        "ins_code": str(ins_code),
        "category": params["category"],
        "range_percent": params["range_percent"],
        "yesterday_price": params["yesterday_price"],
        "first_price": None,  # بعداً از اولین معامله پر می‌شود
        "min_allowed_price": params["min_allowed_price"],
        "max_allowed_price": params["max_allowed_price"],
        "computed_at": datetime.now().isoformat(),
    }
    storage.upsert_daily_params(daily_record)
    print(f"  ✓ در جدول daily_params بانک ذخیره شد (یک ردیف برای امروز).")

    # ── ۶. تزریق مقادیر ثابت در پیکربندی نماد ──
    cfg_sym = config.setdefault("test_symbol", {})
    cfg_sym["fixed_price_range"] = {
        "yesterday_price": params["yesterday_price"],
        "min_allowed_price": params["min_allowed_price"],
        "max_allowed_price": params["max_allowed_price"],
        "range_percent": params["range_percent"],
        "category": params["category"],
    }
    cfg_sym["limit_percent"] = params["range_percent"]
    cfg_sym["base_price"] = params["yesterday_price"]

    print("─" * 60)


def main():
    args = parse_args()
    config = load_config_with_prompt(args)

    # ----- حل پارامترهای زمان‌بندی (CLI > پیکربندی > مقدار پیش‌فرض) -----
    sampling = config.get("sampling", {})
    interval = args.interval if args.interval else int(sampling.get("interval_seconds", 60))
    analysis_interval = (args.analysis_interval if args.analysis_interval
                         else int(sampling.get("analysis_interval_seconds", 60)))

    db_path = ROOT / args.db
    storage = MarketDataStorage(db_path)

    # ----- نوع بازار و ساعت معاملات از config/symbols.json (بدون API) -----
    sym_entry = _symbols_config().get(args.symbol) or {}
    if sym_entry.get("trading_hours"):
        mh = sym_entry["trading_hours"]
        market_info = {
            "ok": True,
            "market_label": sym_entry.get("market_label", ""),
            "instrument_type": sym_entry.get("instrument_type", ""),
            "trading_hours": mh,
            "days": sym_entry.get("days", ""),
        }
        print(f"  بازار: {market_info['market_label']}")
        print(f"  نوع سازمت: {market_info['instrument_type']}")
        print(f"  ساعت معاملات: پیش‌گشایش {mh['pre_open'][0]}-{mh['pre_open'][1]} | "
              f"پیوسته {mh['continuous'][0]}-{mh['continuous'][1]}")
        print(f"  روزها: {market_info['days']}")
        print("=" * 70)
    else:
        print(f"  ⚠ نماد '{args.symbol}' در config/symbols.json نیست — ساعت پیش‌فرض و بدون گیت جلسه")
        market_info = {
            "ok": False,
            "market_label": "", "instrument_type": "", "days": "",
            "trading_hours": {"pre_open": ["08:45", "09:00"],
                              "continuous": ["09:00", "12:30"]},
        }
        print("=" * 70)

    # پوشش کامل جلسهٔ نماد (از پیش‌گشایش تا پایان پیوسته) + حاشیهٔ تخلیهٔ بانک خام.
    # قبلاً بودجهٔ ثابت ۱۳۵۰۰ث (جلسهٔ 08:45-12:30 سهام) بود؛ اگر run_multi بعد از
    # شروع جلسه بالا می‌آمد، این بودجه در میانهٔ جلسهٔ نمادهای با جلسهٔ طولانی‌تر
    # (مثل ریتون ۱۲:۰۰-۱۸:۰۰) تمام می‌شد و پل وسط راه قطع می‌شد.
    def _hm_sec(hm: str) -> int:
        h, m = str(hm).split(":")
        return int(h) * 3600 + int(m) * 60
    window_sec = 13500  # پیش‌فرض: جلسهٔ 08:45 تا 12:30
    th = (sym_entry or {}).get("trading_hours") or {}
    if th.get("pre_open") and th.get("continuous"):
        try:
            window_sec = max(13500, _hm_sec(th["continuous"][1]) - _hm_sec(th["pre_open"][0]))
        except Exception:
            pass
    max_samples = args.max_samples if args.max_samples else int((window_sec / interval) * 2) + 120

    print()
    print("=" * 70)
    print(f"  TSE Early Warning Engine - منبع دادهٔ خام (نسخه ۲.۰)")
    print(f"  نماد: {args.symbol}  |  کد: {args.ins_code}")
    print(f"  فاصله نمونه‌برداری: {interval} ثانیه")
    print(f"  گام تحلیل موتورها: {analysis_interval} ثانیه")
    print(f"  حداکثر نمونه: {max_samples} (پنجرهٔ جلسه: {window_sec//60} دقیقه)")
    print(f"  پایگاه داده: {args.db}")
    print("=" * 70)
    # Phase 2: نرمال‌سازی تطبیقی (اگر adaptive.enabled=true در کانفیگ)
    normalizer = AdaptiveNormalizer(storage, config)

    # ----- محاسبه پارامترهای ثابت روز (یک بار، ثابت برای کل جلسه) -----
    # ابتدا collector و storage ساخته می‌شوند چون load_price_range از collector
    # برای دریافت yesterday_price و از storage برای ذخیره در daily_params
    # استفاده می‌کند. مقادیر محاسبه‌شده در config تزریق می‌شود و چون collector
    # به همان reference نگه‌داری می‌کند، در تمام نمونه‌های بعدی از
    # fixed_price_range ثابت استفاده می‌کند.
    load_price_range(args, config, storage)

    validator = DataValidator()
    sp_detector = SellPressureDetector(config, normalizer=normalizer)
    buy_detector = BuyPressureDetector(config, normalizer=normalizer)
    alert_engine = AlertEngine(config)
    speed_engine = SpeedIndicatorEngine(config)

    snapshots = []            # همه نمونه‌ها (هر interval ثانیه) - برای بانک و CSV
    engine_snapshots = []     # نمونه‌های لحظه اجرای موتورها (هر analysis_interval ثانیه)
    engine_prev = None        # نمونه قبلی از دید موتورها (گام تحلیل)
    prev_enriched = None      # نمونهٔ قبلیِ enriched برای لایهٔ derived (هر interval)
    engine_history = []       # تاریخچه پیوسته برای موتور جمع‌آوری و شاخص‌های سرعتی
    last_engine_eval = 0.0
    sp_results = []
    buy_results = []
    combined_states = []
    all_trades = []

    # ----- منبع دادهٔ خام: نشانگر خواندن (ادامه از ردیف بعدی؛ --replay = بازسازی امروز) -----
    raw_pos = _init_raw_position(args.symbol, args.replay)
    print(f"  منبع داده: data/raw/raw_{args.symbol}.sqlite  (شروع از ردیف بعد از id={raw_pos})")

    # ردیابی مرزهای تجمیعی برای بانک پردازش‌شده و ریپورت دوره‌ای
    last_5min_bucket: str | None = None     # آخرین بازهٔ ۵دقیقه‌ای تکمیل‌شده
    last_15min_bucket: str | None = None    # آخرین بازهٔ ۱۵دقیقه‌ای تکمیل‌شده
    cur_5min_bucket: str | None = None      # بازهٔ جاری ۵دقیقه‌ای
    cur_15min_bucket: str | None = None     # بازهٔ جاری ۱۵دقیقه‌ای

    # توقف نرم: Ctrl+C (SIGINT) یا SIGTERM از run_multi → flag تنظیم می‌شود
    # تا حلقه در ابتدای تکرار بعدی break کند و گزارش Excel (گام ۷-۸) تولید شود.
    # بدون این، Ctrl+C یا kill کردن پروسه‌ی run_live از run_multi باعث می‌شد
    # گزارش Excel هرگز تولید نشود.
    _stop = False
    def _on_stop(signum, frame):
        nonlocal _stop
        _stop = True
    signal.signal(signal.SIGINT, _on_stop)
    signal.signal(signal.SIGTERM, _on_stop)

    for i in range(max_samples):
        if _stop:
            print("\n  ⏹ توقف دریافت شد — در حال تولید خروجی‌ها...")
            break
        now = tehran_now()  # زمان تهران (UTC+3:30) — نه زمان سیستم
        print(f"\n[نمونه {i+1}/{max_samples}] {now.strftime('%H:%M:%S')}")

        # ۰) بررسی ساعت معاملات — خارج از جلسه، ردیف تازهٔ خام مصرف نکن
        if market_info.get("ok"):
            now_hhmm = now.strftime("%H:%M")
            in_session, status = in_trading_window(market_info["trading_hours"], now_hhmm)
            if not in_session:
                sess_end = (market_info["trading_hours"].get("continuous") or ["", ""])[1]
                past_end = bool(sess_end) and now_hhmm > sess_end
                if past_end and _raw_pending(args.symbol, raw_pos) == 0:
                    # شانس آخر برای ردیف مرزی raw_collector (چرخهٔ آخر جلسه)
                    time.sleep(interval)
                    if _raw_pending(args.symbol, raw_pos) == 0:
                        print("  ⏹ جلسه پایان یافته و بانک خام تخلیه شد — پایان کار و تولید گزارش")
                        break
                if not past_end:
                    print(f"  ⏸ خارج از جلسه ({status}) — در انتظار باز شدن بازار")
                    time.sleep(interval)
                    continue
                # پایان جلسه ولی ردیف باقی‌مانده → تخلیهٔ پسماند و بعد پایان
                print(f"  ⏳ پس از پایان جلسه — تخلیهٔ {_raw_pending(args.symbol, raw_pos)} ردیف باقی‌ماندهٔ خام")
            else:
                print(f"  ✓ {status}")

        # ۱) دریافت داده از بانک خام (معاملات ریز در بانک خام نیست → لیست خالی)
        prev_snap = snapshots[-1] if snapshots else None
        snap, trades, raw_pos = fetch_from_raw(
            args.symbol, prev_snap,
            config.get("test_symbol", {}).get("fixed_price_range") or {},
            market_info.get("trading_hours") or {},
            raw_pos,
        )
        if snap is None:
            print("  ⚠ ردیف تازه‌ای در بانک خام نیست - در دوره بعد بررسی می‌شود")
            time.sleep(interval)
            continue

        # ۲) اعتبارسنجی
        q = validator.validate(snap)
        print(f"  فاز: {snap.market_phase}  |  کمال: {q.completeness_pct:.0f}%  |  معتبر: {q.is_valid}")

        # ۲.۵) اعتبارسنجی رنج قیمت — bid/ask باید در [min, max] باشند
        range_ok, out_of_range = snap.validate_bid_ask_range()
        if not range_ok:
            print(f"  ⚠ قیمت‌های bid/ask خارج از رنج مجاز — ذخیره در بانک رد شد")
            for o in out_of_range:
                print(f"    {o['side']}_{o['level']}: {o['price']:,.0f}  (مجاز: {o['min']:,.0f}–{o['max']:,.0f})")
            snapshots.append(snap)  # در حافظه نگه می‌داریم برای موتورها
            time.sleep(interval)
            continue

        # ۲.۶) ردیف error (fetch از TSETMC شکست خورد) هرگز در بانک نوشته
        # نمی‌شود — فقط در حافظه برای پیوستگی موتورها نگه داشته می‌شود و
        # در دورهٔ بعد دوباره fetch تلاش می‌شود. (قبلاً این ردیف‌ها با
        # قیمت‌های صفر وارد بانک می‌شدند و داده را خراب می‌کردند.)
        if snap.data_status == "error":
            print(f"  ⚠ fetch ناموفق — نمونه در بانک ذخیره نشد (تلاش مجدد در دورهٔ بعد)")
            snapshots.append(snap)
            time.sleep(interval)
            continue

        # ۳) ذخیره در SQLite (همه نمونه‌های با دادهٔ واقعی ذخیره می‌شوند - داشبورد از همین می‌خواند)
        snap_id = storage.insert_snapshot(snap)
        if trades:
            storage.insert_trades(trades, symbol=args.symbol,
                                   snapshot_time=snap.tehran_time)
        snap.snapshot_id = snap_id

        # ۳.۵) لایهٔ derived: مشتق و رفع مغایرت فقط در حافظه (بانک اصلی خام ماند).
        # موتورهای inline و نرمال‌ساز مقادیر enriched را می‌بینند.
        try:
            enrich_snapshot(snap, prev_enriched, trades or [])
            prev_enriched = snap
        except Exception as e:
            print(f"  ⚠ خطای enrich در حافظه: {e}")

        # ۴) اجرای موتورها - فقط در فاز پیوسته و با گام تحلیل
        # تابلو هر interval ثانیه جمع می‌شود ولی موتورهای تحلیلی با گام
        # analysis_interval (پیش‌فرض ۶۰ ثانیه) اجرا می‌شوند تا کالیبراسیون
        # آستانه‌ها (که برای نمونه‌های ۶۰ ثانیه‌ای تنظیم شده) حفظ شود.
        if snap.market_phase == MarketPhase.CONTINUOUS.value:
            now_ts = time.time()
            due = (last_engine_eval == 0.0 or
                   (now_ts - last_engine_eval) >= analysis_interval)
            if due:
                sp = sp_detector.evaluate(snap, engine_prev)
                buy = buy_detector.evaluate(snap, engine_prev, engine_history)
                # Phase 2: ثبت raw_valueها برای نرمال‌سازی تطبیقی آینده
                normalizer.record_factors(snap.symbol, "sell", sp.factors,
                                          date_jalali=snap.date_jalali)
                normalizer.record_factors(snap.symbol, "buy", buy.factors,
                                          date_jalali=snap.date_jalali)
                # شاخص‌های سرعتی نردبان (فقط برای نمایش؛ در v2 جزو alert_engine نیست)
                speed = speed_engine.compute(snap, engine_history)
                combined = alert_engine.evaluate(sp, buy)

                engine_prev = snap
                engine_history.append(snap)
                engine_history = engine_history[-36:]   # buy_support به ۳۶ نمونه نیاز دارد
                engine_snapshots.append(snap)
                last_engine_eval = now_ts

                sp_results.append(sp)
                buy_results.append(buy)
                combined_states.append(combined)

                print(f"  Sell Pressure : {sp.total_score:5.1f}/100  - {sp.level}")
                print(f"  Buy Pressure  : {buy.total_score:5.1f}/100  - {buy.level}")
                if speed.speed_pressure_score is not None:
                    print(f"  Speed Pressure: {speed.speed_pressure_score:5.1f}/100  "
                          f"({speed.data_status})")
                else:
                    print(f"  Speed Pressure:     —/100  ({speed.data_status})")
                print(f"  طبقه‌بندی    : {combined.classification}")
                print(f"  وضعیت ترکیب  : {combined.combination_label}")
                if combined.alert and combined.alert.level.value != "بدون هشدار":
                    print(f"  🚨 {combined.alert.level.value}")
                    print(f"     {combined.alert.message}")

        snapshots.append(snap)
        all_trades.extend(trades)

        # ۳.۶) بانک پردازش‌شده: درج derived_samples برای این نمونهٔ enriched.
        # composite_score/alarm از آخرین ارزیابی موتور (اگر در این گام اجرا شده).
        combined_now = combined_states[-1] if combined_states else None
        comp_score, comp_level = _composite_from_combined(combined_now)
        try:
            storage.insert_derived_sample(
                snap, snapshot_id=snap.snapshot_id,
                composite_score=comp_score, alarm_level=comp_level)
        except Exception as e:
            print(f"  ⚠ خطای درج derived_sample: {e}")

        # ۳.۷) مرزهای تجمیعی ۵د/۱۵د → درج aggregate + ریپورت دوره‌ای Excel.
        date_jalali = snap.date_jalali or to_jalali(date.today())
        prev5 = cur_5min_bucket
        prev15 = cur_15min_bucket
        cur_5min_bucket = _bucket_start(snap.tehran_time, AGG_5MIN)
        cur_15min_bucket = _bucket_start(snap.tehran_time, AGG_15MIN)
        # مرز ۵دقیقه‌ای تکمیل شد (بازه قبلی بسته شد)
        if prev5 is not None and cur_5min_bucket != prev5 and last_5min_bucket != prev5:
            try:
                _flush_aggregate(storage, snapshots, args.symbol, date_jalali,
                                 AGG_5MIN, "aggregate_5min", prev5)
                # ساخت اکسل ۵دقیقه‌ای درون‌حلقه‌ای کنسل شد — باعث تأخیر در fetch
                # می‌شد. ریپورت اکسل فقط در پایان جلسه (گام ۸) تولید می‌شود.
            except Exception as e:
                print(f"  ⚠ خطای aggregate ۵د: {e}")
            last_5min_bucket = prev5
        # مرز ۱۵دقیقه‌ای تکمیل شد (بازه قبلی بسته شد)
        if prev15 is not None and cur_15min_bucket != prev15 and last_15min_bucket != prev15:
            try:
                _flush_aggregate(storage, snapshots, args.symbol, date_jalali,
                                 AGG_15MIN, "aggregate_15min", prev15)
                # ساخت اکسل ۱۵دقیقه‌ای درون‌حلقه‌ای کنسل شد — فقط پایان جلسه.
            except Exception as e:
                print(f"  ⚠ خطای aggregate ۱۵د: {e}")
            last_15min_bucket = prev15

        # ۳.۸) ریپورت درخواستی در طول جلسه — فعلاً کنسل شد.
        # ساخت اکسل (حتی درخواستی) درون‌حلقه‌ای باعث تأخیر fetch می‌شد؛
        # همهٔ ریپورت‌های اکسل فقط در پایان جلسه (گام ۸) تولید می‌شوند.
        # برای فعال‌سازی دوباره، بلوک زیر را از کامنت خارج کنید:
        # if _check_report_trigger(args.symbol):
        #     try:
        #         psnap = _report_path(args.symbol, "snapshot")
        #         _generate_excel_from_bank(storage, config, args.symbol, normalizer, psnap)
        #         print(f"  📄 ریپورت درخواستی: {psnap.name}")
        #     except Exception as e:
        #         print(f"  ⚠ خطای ریپورت درخواستی: {e}")

        # ۵) انتظار تا نمونه بعدی
        if i < max_samples - 1:
            time.sleep(interval)

    # ۶) ثبت metadata
    if snapshots:
        first = snapshots[0]
        last = snapshots[-1]
        phases = {}
        for s in snapshots:
            phases[s.market_phase] = phases.get(s.market_phase, 0) + 1
        phase_summary = "؛ ".join(f"{p}: {n}" for p, n in phases.items())
        storage.insert_metadata({
            "date_jalali": first.date_jalali or datetime.now().strftime("%Y-%m-%d"),
            "symbol": args.symbol,
            "ins_code": args.ins_code,
            "open_time": first.tehran_time,
            "close_time": last.tehran_time,
            "last_update": last.tehran_time,
            "price_unit": "تومان",
            "volume_unit": "سهم",
            "data_source": "بانک خام raw_collector",
            "market_phase_summary": phase_summary,
            "total_snapshots": len(snapshots),
            "total_trades": len(all_trades),
            "notes": "جلسه زنده",
        })

    # ۷) خروجی CSV
    storage.export_snapshots_csv(
        ROOT / "data" / f"snapshots_live_{args.symbol}.csv",
        symbol=args.symbol,
    )
    storage.export_trades_csv(
        ROOT / "data" / f"trades_live_{args.symbol}.csv",
        symbol=args.symbol,
    )

    # ۸) تولید گزارش Excel نهایی (پیش‌فرض در پایان جلسه)
    # داده‌ها از بانک بازخوانی می‌شوند تا اکسل همه‌ی نمونه‌های امروز را شامل شود،
    # حتی اگر توسط داشبورد adaptive یا session قبلی run_live جمع‌آوری شده باشند.
    print("\n" + "=" * 70)
    print("  تولید گزارش Excel نهایی...")

    # ۸.۱) flush آخرین بازه‌های ناتمام ۵د/۱۵د (بازهٔ جاری که مرز را قطع نکرد)
    if snapshots:
        last_snap = snapshots[-1]
        date_jalali = last_snap.date_jalali or to_jalali(date.today())
        final5 = _bucket_start(last_snap.tehran_time, AGG_5MIN)
        final15 = _bucket_start(last_snap.tehran_time, AGG_15MIN)
        try:
            if last_5min_bucket != final5:
                _flush_aggregate(storage, snapshots, args.symbol, date_jalali,
                                 AGG_5MIN, "aggregate_5min", final5)
            if last_15min_bucket != final15:
                _flush_aggregate(storage, snapshots, args.symbol, date_jalali,
                                 AGG_15MIN, "aggregate_15min", final15)
        except Exception as e:
            print(f"  ⚠ خطای flush نهایی aggregate: {e}")

    # ۸.۲) ریپورت نهایی از بانک (خام + enriched در حافظه)
    out_path = ROOT / args.output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _generate_excel_from_bank(storage, config, args.symbol, normalizer, out_path)
        print(f"  گزارش: {out_path}")
    except Exception as e:
        print(f"  ⚠ خطای تولید گزارش نهایی: {e}")
    print(f"  پایگاه داده: {db_path}")
    ds = storage.count_derived_samples(args.symbol)
    print(f"  ردیف‌های پردازش‌شده (derived_samples): {ds}")
    storage.close()
    print("=" * 70)


if __name__ == "__main__":
    main()
