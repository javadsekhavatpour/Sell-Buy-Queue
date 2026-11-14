"""
speed_indicators.py
موتور شاخص‌های سرعتی پیشرفته (بعد سوم تحلیل، مستقل از دو موتور اصلی).

در حالی که موتورهای اصلی وضعیت «لحظه‌ای» تابلو را می‌سنجند، این ماژول
«سرعت تغییر» نردبان سفارش‌ها را در یک پنجره زمانی اندازه می‌گیرد.
نردبان سفارش‌ها معمولا چند دقیقه قبل از قیمت و جریان پول واکنش نشان
می‌دهد؛ به همین دلیل این شاخص‌ها نقش تایید یا ارتقای زودهنگام هشدار
را دارند.

سه شاخص مستقل:
  1. Demand Depletion Rate  - نرخ تهی شدن تقاضا
     تخلیه حجم نردبان خرید (مجموع پنج ردیف خرید) در پنجره زمانی.
     نردبان خرید که سریع آب می‌رود ولی با سفارش جدید پر نمی‌شود،
     نشانه زودهنگام فشار فروش است.

  2. Supply Growth Rate     - نرخ رشد عرضه
     انباشت حجم نردبان فروش (مجموع پنج ردیف فروش) در پنجره زمانی.
     رشد سریع عرضه روی تابلو یعنی فروشندگان در حال صف بستن هستند.

  3. Absorption Ratio       - نسبت جذب عرضه
     سهم عرضه‌ای که واقعا معامله شده نسبت به کل عرضه جدید
     (معامله‌شده + مانده روی نردبان). جذب بالا یعنی خریداران
     عرضه را می‌بلعند؛ جذب پایین یعنی عرضه انباشته می‌شود.

دو امتیاز ترکیبی:
  - speed_pressure_score  (۰-۱۰۰): فشار فروش در حال شتاب‌گیری
    (تهی شدن تقاضا + رشد عرضه + جذب پایین)
  - speed_absorption_score (۰-۱۰۰): شواهد جذب عرضه از نگاه نردبان

اصل معماری (مطابق بقیه ماژول‌ها):
  - اگر پنجره کامل نباشد یا فیلد پایه در دسترس نباشد، هیچ مقداری
    حدس زده نمی‌شود؛ شاخص مربوطه None می‌شود و وضعیت داده ثبت می‌گردد.
  - هیچ نمونه قبلی بازنویسی نمی‌شود؛ فقط خواندنی اند.
  - واحد حجم: سهم؛ واحد قیمت: تومان.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from .data_collector import MarketSnapshot


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """محدود کردن مقدار بین [lo, hi]."""
    return max(lo, min(hi, v))


@dataclass
class SpeedIndicatorsResult:
    """خروجی موتور شاخص‌های سرعتی برای یک نمونه."""

    snapshot_time: str
    window_samples: int              # تعداد نمونه‌های پیوسته استفاده‌شده در پنجره
    is_available: bool               # آیا پنجره کافی برای محاسبه وجود داشت؟

    # شاخص‌های خام (None یعنی قابل محاسبه نبود)
    demand_depletion_rate: Optional[float] = None   # ۰-۱+ نسبت تهی شدن نردبان خرید
    supply_growth_rate: Optional[float] = None      # ۰-۱+ نسبت رشد نردبان فروش
    absorption_ratio: Optional[float] = None        # ۰-۱ سهم عرضه معامله‌شده

    # مقادیر نرمال شده (۰-۱)
    demand_depletion_norm: Optional[float] = None
    supply_growth_norm: Optional[float] = None
    absorption_norm: Optional[float] = None

    # امتیازهای ترکیبی (None یعنی ناموجود)
    speed_pressure_score: Optional[float] = None    # ۰-۱۰۰ فشار سرعتی
    speed_absorption_score: Optional[float] = None  # ۰-۱۰۰ شواهد جذب نردبانی

    # حجم‌های نردبان در ابتدا و انتهای پنجره (برای شفافیت و دیباگ)
    buy_ladder_start: Optional[int] = None
    buy_ladder_now: Optional[int] = None
    sell_ladder_start: Optional[int] = None
    sell_ladder_now: Optional[int] = None
    executed_volume_window: Optional[int] = None    # حجم معامله‌شده در پنجره

    data_status: str = "ok"          # ok / partial / unavailable
    notes: List[str] = field(default_factory=list)

    @property
    def is_confirmed_pressure(self) -> bool:
        """آیا فشار سرعتی در سطح تایید (به‌کاررفته در ارتقای هشدار) است؟"""
        if self.speed_pressure_score is None:
            return False
        return self.speed_pressure_score >= 60

    @property
    def is_confirmed_absorption(self) -> bool:
        """آیا شواهد جذب نردبانی در سطح تایید است؟"""
        if self.speed_absorption_score is None:
            return False
        return self.speed_absorption_score >= 60

    def to_dict(self) -> Dict:
        return {
            "snapshot_time": self.snapshot_time,
            "window_samples": self.window_samples,
            "is_available": self.is_available,
            "demand_depletion_rate": (
                round(self.demand_depletion_rate, 4)
                if self.demand_depletion_rate is not None else None
            ),
            "supply_growth_rate": (
                round(self.supply_growth_rate, 4)
                if self.supply_growth_rate is not None else None
            ),
            "absorption_ratio": (
                round(self.absorption_ratio, 4)
                if self.absorption_ratio is not None else None
            ),
            "demand_depletion_norm": (
                round(self.demand_depletion_norm, 4)
                if self.demand_depletion_norm is not None else None
            ),
            "supply_growth_norm": (
                round(self.supply_growth_norm, 4)
                if self.supply_growth_norm is not None else None
            ),
            "absorption_norm": (
                round(self.absorption_norm, 4)
                if self.absorption_norm is not None else None
            ),
            "speed_pressure_score": (
                round(self.speed_pressure_score, 2)
                if self.speed_pressure_score is not None else None
            ),
            "speed_absorption_score": (
                round(self.speed_absorption_score, 2)
                if self.speed_absorption_score is not None else None
            ),
            "buy_ladder_start": self.buy_ladder_start,
            "buy_ladder_now": self.buy_ladder_now,
            "sell_ladder_start": self.sell_ladder_start,
            "sell_ladder_now": self.sell_ladder_now,
            "executed_volume_window": self.executed_volume_window,
            "data_status": self.data_status,
            "notes": list(self.notes),
        }


class SpeedIndicatorEngine:
    """محاسبه شاخص‌های سرعتی نردبان سفارش‌ها روی پنجره زمانی."""

    def __init__(self, config: Dict):
        cfg = config.get("speed_indicators", {})
        self.window_samples = int(cfg.get("window_samples", 3))
        self.min_history_samples = int(cfg.get("min_history_samples", 2))

        # نقطه امتیاز کامل هر شاخص
        self.depletion_full_at = float(cfg.get("depletion_full_at", 0.5))
        self.supply_growth_full_at = float(cfg.get("supply_growth_full_at", 0.5))
        self.absorption_full_at = float(cfg.get("absorption_full_at", 0.6))

        # وزن ترکیب امتیاز فشار سرعتی (مجموع باید ۱ باشد)
        bw = cfg.get("blend_weights", {})
        self.w_depletion = float(bw.get("demand_depletion", 0.40))
        self.w_supply = float(bw.get("supply_growth", 0.35))
        self.w_absorption_inverse = float(bw.get("absorption_inverse", 0.25))

    # -----------------------------------------------------------------
    # ابزار: حجم نردبان یک سمت
    # -----------------------------------------------------------------
    @staticmethod
    def _ladder_volume(snap: MarketSnapshot, side: str) -> Optional[int]:
        """
        مجموع حجم نردبان یک سمت (buy / sell).

        اگر پنج ردیف کامل موجود باشد مجموع آن‌ها؛ در غیر این صورت
        حجم بهترین قیمت (در صورت > 0). اگر هیچ‌کدام نبود None تا
        هیچ مقداری حدس زده نشود.
        """
        rows = snap.buy_rows if side == "buy" else snap.sell_rows
        valid_rows = [r for r in rows if r.volume > 0]
        if valid_rows:
            return int(sum(r.volume for r in valid_rows))
        best = snap.best_buy_volume if side == "buy" else snap.best_sell_volume
        if best > 0:
            return int(best)
        return None

    # -----------------------------------------------------------------
    # محاسبه اصلی
    # -----------------------------------------------------------------
    def compute(
        self,
        snap: MarketSnapshot,
        history: List[MarketSnapshot],
    ) -> SpeedIndicatorsResult:
        """
        محاسبه شاخص‌های سرعتی برای نمونه فعلی.

        history فقط نمونه‌های فاز پیوسته قبل از snap است
        (قدیمی به جدید، بدون خود snap). پنجره شامل
        window_samples نمونه است: نمونه قدیمی ابتدای پنجره + نمونه‌های
        میانی + snap به‌عنوان انتهای پنجره.
        """
        # پنجره: آخرین (window_samples - 1) نمونه قبل + نمونه فعلی
        window_prev = history[-(self.window_samples - 1):]
        window = list(window_prev) + [snap]

        if len(window) < max(self.min_history_samples, 2):
            return SpeedIndicatorsResult(
                snapshot_time=snap.tehran_time,
                window_samples=len(window),
                is_available=False,
                data_status="unavailable",
                notes=["پنجره نمونه پیوسته هنوز کامل نیست؛ شاخص سرعتی غیرفعال"],
            )

        start = window[0]
        notes: List[str] = []

        # ----- حجم نردبان‌ها در ابتدا و انتهای پنجره -----
        buy_start = self._ladder_volume(start, "buy")
        buy_now = self._ladder_volume(snap, "buy")
        sell_start = self._ladder_volume(start, "sell")
        sell_now = self._ladder_volume(snap, "sell")

        if buy_start is None or buy_now is None:
            notes.append("نردبان خرید در ابتدا یا انتهای پنجره موجود نیست")
        if sell_start is None or sell_now is None:
            notes.append("نردبان فروش در ابتدا یا انتهای پنجره موجود نیست")

        # ----- حجم معامله‌شده در پنجره (از تجمعی گروه C - قابل اتکا) -----
        if start.total_volume > 0 or snap.total_volume > 0:
            executed = max(snap.total_volume - start.total_volume, 0)
        else:
            executed = None
            notes.append("حجم تجمعی در ابتدا یا انتهای پنجره موجود نیست")

        # ----- شاخص ۱: نرخ تهی شدن تقاضا -----
        depletion_rate = None
        depletion_norm = None
        if buy_start is not None and buy_now is not None and buy_start > 0:
            depletion_rate = max((buy_start - buy_now) / buy_start, 0.0)
            depletion_norm = _clamp(depletion_rate / self.depletion_full_at)
        elif buy_start == 0 and buy_now == 0:
            notes.append("نردبان خرید در کل پنجره خالی است؛ نرخ تهی شدن محاسبه نشد")

        # ----- شاخص ۲: نرخ رشد عرضه -----
        supply_rate = None
        supply_norm = None
        if sell_start is not None and sell_now is not None and sell_start > 0:
            supply_rate = max((sell_now - sell_start) / sell_start, 0.0)
            supply_norm = _clamp(supply_rate / self.supply_growth_full_at)
        elif sell_start == 0:
            # نردبان فروش صفر بوده؛ هر عرضه جدید معنادار است ولی مبنای
            # نسبتی نداریم - حدس نمی‌زنیم
            notes.append("نردبان فروش در ابتدای پنجره صفر بوده؛ مبنای نسبتی موجود نیست")

        # ----- شاخص ۳: نسبت جذب عرضه -----
        absorption = None
        absorption_norm = None
        if executed is not None and sell_start is not None and sell_now is not None:
            new_supply = max(sell_now - sell_start, 0)
            denominator = executed + new_supply
            if denominator > 0:
                absorption = executed / denominator
                absorption_norm = _clamp(absorption / self.absorption_full_at)
            else:
                # نه معامله، نه عرضه جدید: بازار راکد - جذب را خنثی (None) می‌گذاریم
                notes.append("در پنجره نه معامله‌ای رخ داده و نه عرضه جدید آمده")

        # ----- امتیازهای ترکیبی -----
        pressure_score = None
        if depletion_norm is not None and supply_norm is not None and absorption_norm is not None:
            pressure_score = (
                self.w_depletion * depletion_norm +
                self.w_supply * supply_norm +
                self.w_absorption_inverse * (1.0 - absorption_norm)
            ) * 100.0

        absorption_score = None
        if absorption_norm is not None:
            absorption_score = absorption_norm * 100.0

        # ----- وضعیت داده -----
        available_indicators = sum(
            1 for v in (depletion_norm, supply_norm, absorption_norm) if v is not None
        )
        if available_indicators == 0:
            data_status = "unavailable"
        elif available_indicators < 3:
            data_status = "partial"
        else:
            data_status = "ok"

        return SpeedIndicatorsResult(
            snapshot_time=snap.tehran_time,
            window_samples=len(window),
            is_available=data_status != "unavailable",
            demand_depletion_rate=depletion_rate,
            supply_growth_rate=supply_rate,
            absorption_ratio=absorption,
            demand_depletion_norm=depletion_norm,
            supply_growth_norm=supply_norm,
            absorption_norm=absorption_norm,
            speed_pressure_score=pressure_score,
            speed_absorption_score=absorption_score,
            buy_ladder_start=buy_start,
            buy_ladder_now=buy_now,
            sell_ladder_start=sell_start,
            sell_ladder_now=sell_now,
            executed_volume_window=executed,
            data_status=data_status,
            notes=notes,
        )
