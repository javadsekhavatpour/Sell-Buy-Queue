"""لایهٔ محاسبهٔ مقادیر مشتق (رفع مغایرت) روی دادهٔ خام — بدون تغییر در بانک اصلی.

بانک اصلی فقط دادهٔ خام را نگه می‌دارد: آنچه از TSE دریافت می‌شود
(قیمت‌ها، سفارش‌ها، total_volume/value/trade_count، شمارنده‌های تجمعی ClientType
مثل real_buy_volume/real_buy_count/real_sell_*/legal_*، و معاملات).

این ماژول مقادیر مشتق و تصحیح‌شده را در **حافظه** محاسبه می‌کند و در اختیار
موتورهای آلارم/گزارش/داشبورد قرار می‌دهد — بدون آنکه چیزی در بانک اصلی بنویسد.
قلب رفع مغایرت: فشار حقیقیِ بازه از **معاملات واقعی (aggressor side)** و حجم کل
محاسبه می‌شود، نه از دلتای تجمعیِ ClientType که نسبت به ClosingPrice تأخیر دارد.

دو نقطهٔ ورودی:
  - enrich_series(raw_snaps, trades_by_time): حالت دسته‌ای (sim، گزارش، بازپخش).
  - enrich_snapshot(snap, prev, trades_window): حالت تک‌نمونه‌ای (مانیتور لایو).

هر دو فقط شیء snapshot را درجا به‌روز می‌کنند؛ خروجی فایل/بانک ندارند.
"""
from __future__ import annotations
from typing import Dict, List, Optional

from .data_collector import MarketSnapshot, MarketDataCollector, Trade


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
