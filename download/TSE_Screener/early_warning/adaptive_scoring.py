"""
adaptive_scoring.py
نرمال‌سازی تطبیقی شاخص‌های فشار فروش/خرید بر اساس صدک تاریخچه.

مرحله ۱ (فعلی): نرمال‌سازی با آستانه ثابت full_at (یک مقدار برای همه نمادها).
  norm = clamp(raw / full_at, 0, 1)

مرحله ۲ (این ماژول): آستانه پویا = صدک ۹۰ مقادیر خام تاریخی هر (نماد، شاخص).
  - نماد آرام (دلتاهای کوچک) → آستانه پایین → حرکت‌های کوچک‌اش معنی‌دار
  - نماد پرنوسان (دلتاهای بزرگ) → آستانه بالا → فقط حرکت‌های استثنایی full

روند کار:
  ۱. record(...) — پس از محاسبه هر فاکتور، raw_value در score_history ذخیره می‌شود.
  ۲. get_threshold(symbol, factor, fallback) — صدک P از تاریخچه؛
     اگر کمتر از min_samples نمونه بود، fallback (full_at ثابت) برمی‌گردد.
  ۳. کش در حافظه با TTL تا هر ۳۰ثانیه SQLite پرس‌وجو نشود.

پیکربندی (از warning_thresholds.json → "adaptive"):
  enabled: true/false        — فعال/غیرفعال (غیرفعال = رفتار مرحله ۱)
  min_samples: 50            — حداقل مشاهدات قبل از روشن شدن تطبیقی
  percentile: 90             — صدک آستانه (۹۰ = ۱۰٪ بالا = full)
  window_samples: 500        — استفاده از ۵۰۰ مشاهده اخیر
  cache_ttl_seconds: 300     — نوسازی کش هر ۵ دقیقه
  floor_ratio: 0.1           — آستانه تطبیقی ≥ ۱۰٪ fallback (جلوگیری از صفر)
"""

from __future__ import annotations

import math
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from .data_collector import to_jalali
from datetime import date


# ---------------------------------------------------------------------------
# محاسبه صدک بدون numpy (خالص Python)
# ---------------------------------------------------------------------------

def _percentile(values: List[float], pct: float) -> float:
    """
    صدک pct از لیست values (مرتب‌سازی + درون‌یابی خطی).

    مثال: _percentile([1,2,3,4,5,6,7,8,9,10], 90) → 9.1
    """
    if not values:
        return float("nan")
    s = sorted(values)
    n = len(s)
    if n == 1:
        return s[0]
    # روش R-7 (همان numpy.percentile پیش‌فرض)
    rank = (pct / 100.0) * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return s[lo]
    frac = rank - lo
    return s[lo] + (s[hi] - s[lo]) * frac


# ---------------------------------------------------------------------------
# کلاس اصلی نرمال‌سازی تطبیقی
# ---------------------------------------------------------------------------

class AdaptiveNormalizer:
    """
    نرمال‌سازی تطبیقی بر اساس صدک تاریخچه score_history.

    استفاده:
        norm = AdaptiveNormalizer(storage, config)
        # در موتورها:
        threshold = norm.get_threshold("سرود", "sell_breadth", fallback=0.3)
        norm.record("سرود", "sell", "sell_breadth", raw_value=0.45, ...)
    """

    def __init__(self, storage, config: Optional[Dict] = None):
        self.storage = storage
        cfg = config or {}
        adaptive_cfg = cfg.get("adaptive", {}) if isinstance(cfg, dict) else {}

        self.enabled: bool = bool(adaptive_cfg.get("enabled", False))
        self.min_samples: int = int(adaptive_cfg.get("min_samples", 50))
        self.percentile: float = float(adaptive_cfg.get("percentile", 90))
        self.window_samples: int = int(adaptive_cfg.get("window_samples", 500))
        self.cache_ttl: float = float(adaptive_cfg.get("cache_ttl_seconds", 300))
        self.floor_ratio: float = float(adaptive_cfg.get("floor_ratio", 0.1))

        # کش در حافظه: {(symbol, factor): (threshold, timestamp)}
        self._cache: Dict[Tuple[str, str], Tuple[float, float]] = {}

    # -------------------------------------------------------------------
    # آستانه تطبیقی
    # -------------------------------------------------------------------
    def get_threshold(self, symbol: str, factor: str,
                      fallback_full_at: float) -> float:
        """
        آستانه نرمال‌سازی برای (نماد، شاخص).

        - اگر adaptive غیرفعال است → fallback_full_at (رفتار مرحله ۱).
        - اگر تاریخچه < min_samples است → fallback_full_at.
        - در غیر این صورت → صدک self.percentile از |raw| تاریخچه.

        حداقل آستانه = fallback_full_at * floor_ratio (جلوگیری از صفر).
        """
        if not self.enabled:
            return fallback_full_at

        if fallback_full_at <= 0 or math.isnan(fallback_full_at):
            return fallback_full_at

        key = (symbol, factor)
        now = time.time()
        cached = self._cache.get(key)
        if cached is not None and (now - cached[1]) < self.cache_ttl:
            return cached[0]

        threshold = self._compute_threshold(symbol, factor, fallback_full_at)
        self._cache[key] = (threshold, now)
        return threshold

    def _compute_threshold(self, symbol: str, factor: str,
                           fallback_full_at: float) -> float:
        """محاسبه واقعی آستانه از SQLite."""
        try:
            values = self.storage.get_score_history_raw(
                symbol, factor, limit=self.window_samples)
        except Exception:
            return fallback_full_at

        if len(values) < self.min_samples:
            return fallback_full_at

        # استفاده از قدرمطلق: آستانه نشان‌دهنده «مقدار حرکت استثنایی» است.
        abs_values = [abs(v) for v in values]
        pct_val = _percentile(abs_values, self.percentile)

        if math.isnan(pct_val) or pct_val <= 0:
            return fallback_full_at

        # حداقل = floor_ratio × fallback (جلوگیری از آستانه بیش‌از حد کوچک)
        floor = fallback_full_at * self.floor_ratio
        threshold = max(pct_val, floor)

        # ثبت آستانه تطبیقی برای شفافیت (اختیاری)
        return threshold

    # -------------------------------------------------------------------
    # ثبت مشاهده
    # -------------------------------------------------------------------
    def record(self, symbol: str, engine: str, factor: str,
               raw_value: float, normalized: float, score: float,
               status: str, date_jalali: Optional[str] = None) -> None:
        """
        ثبت یک مشاهده شاخص در score_history.

        فقط اگر adaptive فعال است و raw_value عددی (نه NaN) است ثبت می‌شود.
        NaN و None نادیده گرفته می‌شوند (داده مفقود را ثبت نمی‌کنیم).
        """
        if not self.enabled:
            return
        # NaN را ثبت نکن (داده مفقود)
        if raw_value is None:
            return
        if isinstance(raw_value, float) and math.isnan(raw_value):
            return

        try:
            row = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "date_jalali": date_jalali or to_jalali(date.today()),
                "symbol": symbol,
                "engine": engine,
                "factor": factor,
                "raw_value": float(raw_value),
                "normalized": float(normalized) if normalized is not None else None,
                "score": float(score) if score is not None else None,
                "status": status or "ok",
            }
            self.storage.insert_score_history(row)
            # ابطال کش این (symbol, factor) تا آستانه با داده جدید به‌روز شود
            self._cache.pop((symbol, factor), None)
        except Exception:
            # خطای ثبت نباید موتورها را متوقف کند
            pass

    def record_factors(self, symbol: str, engine: str,
                       factors: List, date_jalali: Optional[str] = None) -> None:
        """
        ثبت گروهی همه فاکتورهای یک ارزیابی.

        factors: لیستی از SellPressureFactorResult / BuyPressureFactorResult.
        """
        if not self.enabled or not factors:
            return
        rows = []
        ts = datetime.now().isoformat(timespec="seconds")
        dj = date_jalali or to_jalali(date.today())
        for f in factors:
            rv = getattr(f, "raw_value", None)
            if rv is None or (isinstance(rv, float) and math.isnan(rv)):
                continue  # داده مفقود را ثبت نکن
            rows.append({
                "timestamp": ts,
                "date_jalali": dj,
                "symbol": symbol,
                "engine": engine,
                "factor": getattr(f, "name", ""),
                "raw_value": float(rv),
                "normalized": getattr(f, "normalized", None),
                "score": getattr(f, "score", None),
                "status": getattr(f, "status", "ok"),
            })
        if rows:
            try:
                self.storage.insert_score_history_bulk(rows)
                # ابطال کش برای فاکتورهای ثبت‌شده
                for r in rows:
                    self._cache.pop((symbol, r["factor"]), None)
            except Exception:
                pass

    # -------------------------------------------------------------------
    # گزارش / دیباگ
    # -------------------------------------------------------------------
    def get_thresholds_report(self, symbol: str,
                              fallbacks: Dict[str, float]) -> Dict:
        """
        گزارش آستانه‌های تطبیقی برای همه شاخص‌های یک نماد.

        fallbacks: {"sell_breadth": 0.3, "sell_flow": 0.1, ...}
        خروجی: {"sell_breadth": {"threshold": 0.45, "samples": 120, "adaptive": true}, ...}
        """
        report = {}
        for factor, fb in fallbacks.items():
            count = 0
            try:
                count = self.storage.get_score_history_count(symbol, factor)
            except Exception:
                pass
            threshold = self.get_threshold(symbol, factor, fb)
            report[factor] = {
                "threshold": round(threshold, 4),
                "fallback": fb,
                "samples": count,
                "min_samples": self.min_samples,
                "adaptive": count >= self.min_samples and self.enabled,
            }
        return report

    def invalidate_cache(self, symbol: Optional[str] = None) -> None:
        """ابطال کش (برای تست یا اجبار به‌روزرسانی)."""
        if symbol is None:
            self._cache.clear()
        else:
            keys_to_remove = [k for k in self._cache if k[0] == symbol]
            for k in keys_to_remove:
                self._cache.pop(k)
