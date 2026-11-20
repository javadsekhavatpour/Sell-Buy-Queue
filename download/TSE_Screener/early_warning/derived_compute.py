"""لایهٔ محاسبهٔ مقادیر مشتق (رفع مغایرت) روی دادهٔ خام — بدون تغییر در بانک اصلی.

بانک اصلی فقط دادهٔ خام را نگه می‌دارد: آنچه از TSE دریافت می‌شود
(قیمت‌ها، سفارش‌ها، total_volume/value/trade_count، شمارنده‌های تجمعی ClientType
مثل real_buy_volume/real_buy_count/real_sell_*/legal_*، و معاملات).

این ماژول مقادیر مشتق و تصحیح‌شده را محاسبه می‌کند:
  - در حافظه (enrich_series/enrich_snapshot): برای نویسندهٔ بانک پردازش‌شده.
  - ماندگار در جدول derived_samples (نوشته‌شده توسط run_live/_publish).
  - خوانده‌شده توسط داشبوردها از بانک (load_enriched_series) — بدون محاسبهٔ مجدد.

قلب رفع مغایرت: فشار حقیقیِ بازه از **معاملات واقعی (aggressor side)** و حجم کل
محاسبه می‌شود، نه از دلتای تجمعیِ ClientType که نسبت به ClosingPrice تأخیر دارد.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from .data_collector import MarketSnapshot, MarketDataCollector, Trade


# فیلدهای مشتق که در derived_samples ذخیره و بازخوانی می‌شوند.
_DERIVED_FIELDS = [
    "ask5_volume", "bid5_volume",
    "interval_volume", "interval_value", "interval_trade_count",
    "interval_real_buy_volume", "interval_real_sell_volume",
    "interval_real_buy_value", "interval_real_sell_value",
    "interval_real_buy_count", "interval_real_sell_count",
    "interval_buy_volume", "interval_sell_volume",
    "clienttype_stale", "clienttype_lag_shares", "last_fresh_real_frac",
    "buyer_power", "per_capita_buy_real", "per_capita_sell_real",
    "real_money_flow", "real_money_flow_ratio",
    "data_complete", "missing_fields",
]


def _apply_derived_row(snap: MarketSnapshot, row: Dict) -> None:
    """اعمال فیلدهای مشتق از یک ردیف derived_samples روی snapshot خام (درجا).

    row: dict از جدول derived_samples (با کلیدهای هم‌نام فیلدهای مشتق).
    پس از این، snap به‌عنوان enriched علامت‌گذاری می‌شود (_enriched=True).
    """
    for f in _DERIVED_FIELDS:
        if f in row and row[f] is not None:
            setattr(snap, f, row[f])
    snap._enriched = True
    snap._composite_score = row.get("composite_score")
    snap._alarm_level = row.get("alarm_level")


def _trades_in_window(all_trades_sorted: List[Trade], t0: str, t1: str) -> List[Trade]:
    """معاملاتی که trade_time آن‌ها در بازهٔ [t0, t1] باشد (مقایسهٔ رشته‌ای HH:MM:SS)."""
    return [t for t in all_trades_sorted
            if t0 <= str(getattr(t, "trade_time", "")) <= t1]


def enrich_snapshot(snap: MarketSnapshot,
                    prev: Optional[MarketSnapshot],
                    trades_window: List[Trade]) -> MarketSnapshot:
    """محاسبهٔ مشتق روی یک snapshot خام درجا (در حافظه).

    prev باید snapshotِ قبلیِ ازپیش-enrichedشده باشد (برای carried last_fresh_real_frac).
    trades_window: معاملات بازهٔ [prev.tehran_time, snap.tehran_time].
    snapshot از پیش enrich شده باشد (پرچم _enriched) → بدون تغییر برمی‌گردد.
    """
    if snap is None or getattr(snap, "_enriched", False):
        return snap
    # حجم ۵ ردیف عرضه/تقاضا (برای موتورهای فروش/خرید)
    snap.ask5_volume = float(sum(r.volume for r in (snap.sell_rows or [])[:5]))
    snap.bid5_volume = float(sum(r.volume for r in (snap.buy_rows or [])[:5]))
    # مقادیر بازه‌ای + رفع مغایرت (از معاملات واقعی، نه دلتای تجمعی ClientType)
    if prev is not None:
        snap.last_fresh_real_frac = prev.last_fresh_real_frac
        snap.interval_volume = max(0, snap.total_volume - prev.total_volume)
        snap.interval_value = max(0, snap.total_value - prev.total_value)
        snap.interval_trade_count = max(0, snap.total_trade_count - prev.total_trade_count)
        MarketDataCollector._classify_interval_real(snap, prev, trades_window or [])
    # شاخص‌های مشتقِ نمایشی (سرانه، قدرت خریدار، ارزش تجمعی تقریبی) + کامل‌بودن
    MarketDataCollector._compute_derived(snap)
    MarketDataCollector._mark_completeness(snap)
    snap._enriched = True
    return snap


def enrich_series(raw_snaps: List[MarketSnapshot],
                  trades_by_time: Optional[Dict[str, List[Trade]]] = None
                  ) -> List[MarketSnapshot]:
    """محاسبهٔ مشتق روی یک سری snapshot خام، درجا (در حافظه).

    ورودی: raw_snaps (snapshotهای خام با مقادیر تجمعی)،
           trades_by_time (dict: trade_time → list[Trade]) اختیاری.
    خروجی: همان snapshotها به‌ترتیب زمانی، با فیلدهای مشتق پر شده.
    هیچ نوشتن روی بانک انجام نمی‌شود.
    """
    snaps = sorted([s for s in raw_snaps if s is not None], key=lambda s: s.timestamp)
    all_trades: List[Trade] = []
    if trades_by_time:
        all_trades = sorted(
            (t for tlist in trades_by_time.values() for t in tlist),
            key=lambda t: getattr(t, "trade_time", ""))
    for i, snap in enumerate(snaps):
        if getattr(snap, "_enriched", False):
            continue
        prev = snaps[i - 1] if i >= 1 else None
        if prev is not None:
            t0, t1 = str(prev.tehran_time), str(snap.tehran_time)
            win = _trades_in_window(all_trades, t0, t1)
        else:
            win = []
        enrich_snapshot(snap, prev, win)
    return snaps


def load_enriched_series(storage, symbol: str,
                         date_jalali: Optional[str] = None) -> List[MarketSnapshot]:
    """خواندن snapshotهای خام + ادغام factors پردازش‌شده از بانک (derived_samples).

    منبعِ factors: جدول derived_samples (بانک پردازش‌شده) — نه محاسبهٔ مجدد در
    حافظه. هر ردیف derived_samples متناظر با یک snapshot خام (با timestamp یکسان)
    است و فیلدهای مشتق (buyer_power، interval_real_*، real_money_flow و ...) را
    روی شیء خام اعمال می‌کند و آن را enriched علامت‌گذاری می‌کند.

    اگر derived_samples برای نماد خالی باشد (بانک قدیمی، قبل از پیاده‌سازی بانک
    پردازش‌شده)، به enrich_series در حافظه fallback می‌کند تا کارایی حفظ شود.

    date_jalali: هر دو فرمت slash/dash پشتیبانی می‌شود (مطابق snapshots).
    """
    # ۱) خواندن snapshotهای خام
    rows = storage.get_snapshots_for_symbol(symbol)
    if date_jalali:
        dates = {date_jalali, date_jalali.replace("/", "-"), date_jalali.replace("-", "/")}
        rows = [r for r in rows if r.get("date_jalali") in dates]
    snaps = [MarketSnapshot.from_flat_dict(r) for r in rows]
    snaps.sort(key=lambda s: s.timestamp)

    # ۲) خواندن derived_samples و ادغام
    derived = storage.get_derived_samples_for_symbol(symbol)
    if derived:
        if date_jalali:
            derived = [d for d in derived if d.get("date_jalali") in dates]
        dmap = {d.get("timestamp"): d for d in derived}
        merged = 0
        for s in snaps:
            d = dmap.get(s.timestamp)
            if d:
                _apply_derived_row(s, d)
                merged += 1
        if merged == 0:
            # timestampها هم‌خوان نبودند → fallback محاسبه در حافظه
            enrich_series(snaps)
    else:
        # بانک قدیمی بدون derived_samples → fallback
        enrich_series(snaps)
    return snaps


def _bucket_start(tehran_time: str, bucket_seconds: int) -> str:
    """کفِ بازهٔ HH:MM:SS بر اساس bucket_seconds (مثلاً ۳۰۰ = ۵دقیقه)."""
    t = str(tehran_time or "").strip()
    parts = t.split(":")
    if len(parts) < 2:
        return t or "00:00:00"
    try:
        hh = int(parts[0]); mm = int(parts[1]); ss = int(parts[2]) if len(parts) > 2 else 0
    except ValueError:
        return t
    total = hh * 3600 + mm * 60 + ss
    floored = (total // bucket_seconds) * bucket_seconds
    return f"{floored // 3600:02d}:{(floored % 3600) // 60:02d}:{floored % 60:02d}"


def aggregate_interval(snaps_enriched: List[MarketSnapshot],
                       bucket_seconds: int,
                       symbol: str,
                       date_jalali: str = "") -> List[Dict]:
    """تجمیع snapshotهای enriched در بازه‌های bucket_seconds (۳۰۰ یا ۹۰۰).

    خروجی: لیست ردیف‌های تجمیعی (dict) به ترتیب bucket_start، مناسب درج در
    aggregate_5min / aggregate_15min. هر بازه شامل OHLC، مجموع حجم/ارزش/تعداد و
    معاملات بازه‌ای حقیقی، و آخرین مقدار شاخص‌های نمایشی (buyer_power و ...) است.
    """
    out: List[Dict] = []
    buckets: Dict[str, List[MarketSnapshot]] = {}
    for s in snaps_enriched:
        if s is None:
            continue
        b = _bucket_start(getattr(s, "tehran_time", ""), bucket_seconds)
        buckets.setdefault(b, []).append(s)
    for b, group in sorted(buckets.items()):
        group.sort(key=lambda x: str(getattr(x, "tehran_time", "")))
        last = group[-1]
        prices = [float(getattr(s, "last_price", 0) or 0) for s in group
                  if getattr(s, "last_price", None)]
        open_price = float(getattr(group[0], "last_price", 0) or 0)
        close_price = float(getattr(last, "last_price", 0) or 0)
        high_price = max(prices) if prices else close_price
        low_price = min(prices) if prices else close_price
        row = {
            "date_jalali": date_jalali or getattr(last, "date_jalali", ""),
            "symbol": symbol or getattr(last, "symbol", ""),
            "bucket_start": b,
            "bucket_end": str(getattr(last, "tehran_time", "")),
            "sample_count": len(group),
            "open_price": open_price,
            "close_price": close_price,
            "high_price": high_price,
            "low_price": low_price,
            "total_volume": int(sum(int(getattr(s, "interval_volume", 0) or 0) for s in group)),
            "total_value": float(sum(float(getattr(s, "interval_value", 0) or 0) for s in group)),
            "total_trade_count": int(sum(int(getattr(s, "interval_trade_count", 0) or 0) for s in group)),
            "interval_real_buy_volume": int(sum(int(getattr(s, "interval_real_buy_volume", 0) or 0) for s in group)),
            "interval_real_sell_volume": int(sum(int(getattr(s, "interval_real_sell_volume", 0) or 0) for s in group)),
            "interval_real_buy_value": float(sum(float(getattr(s, "interval_real_buy_value", 0) or 0) for s in group)),
            "interval_real_sell_value": float(sum(float(getattr(s, "interval_real_sell_value", 0) or 0) for s in group)),
            "buyer_power": float(getattr(last, "buyer_power", 0) or 0),
            "real_money_flow": float(getattr(last, "real_money_flow", 0) or 0),
            "real_money_flow_ratio": float(getattr(last, "real_money_flow_ratio", 0) or 0),
            "per_capita_buy_real": float(getattr(last, "per_capita_buy_real", 0) or 0),
            "per_capita_sell_real": float(getattr(last, "per_capita_sell_real", 0) or 0),
            "composite_score": float(getattr(last, "_composite_score", 0) or 0) if getattr(last, "_composite_score", None) is not None else None,
            "alarm_level": getattr(last, "_alarm_level", None),
        }
        out.append(row)
    return out

