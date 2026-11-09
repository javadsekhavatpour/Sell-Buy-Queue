"""
sell_pressure.py
موتور تشخیص فشار فروش و پیش‌بینی احتمال تشکیل صف فروش (۰-۱۰۰).

شش شاخص مستقل (مجموع امتیاز = ۱۰۰):
  1. ضعف قدرت خریدار حقیقی              - 20
  2. خروج پول حقیقی                     - 20
  3. برتری سرانه فروش به خرید           - 15
  4. فاصله منفی آخرین قیمت از پایانی      - 15
  5. افزایش سرعت عرضه در بهترین قیمت      - 15
  6. تخلیه تقاضا و نزدیک شدن به کف روز    - 15

نکته فنی: شاخص‌ها به‌صورت مستقل محاسبه می‌شوند؛ صرفاً منفی بودن قیمت
نباید باعث امتیاز کامل فشار فروش شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from .data_collector import MarketSnapshot


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """محدود کردن مقدار بین [lo, hi]."""
    return max(lo, min(hi, v))


@dataclass
class SellPressureFactorResult:
    """نتیجه یک شاخص."""
    name: str
    label: str               # برچسب فارسی
    max_points: float        # حداکثر امتیاز ممکن
    raw_value: float         # مقدار خام شاخص
    raw_unit: str            # واحد مقدار خام
    normalized: float        # مقدار نرمال شده ۰-۱
    score: float             # امتیاز نهایی
    description: str         # توضیح محاسبه

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "label": self.label,
            "max_points": self.max_points,
            "raw_value": round(self.raw_value, 4),
            "raw_unit": self.raw_unit,
            "normalized": round(self.normalized, 4),
            "score": round(self.score, 2),
            "description": self.description,
        }


@dataclass
class SellPressureResult:
    """خروجی کامل موتور فشار فروش."""
    total_score: float
    level: str                       # برچسب سطح
    action: str                      # اقدام پیشنهادی
    factors: List[SellPressureFactorResult]
    independent_signals_count: int   # تعداد شاخص‌های با امتیاز >= ۵۰٪
    is_critical: bool               # آیا در منطقه خطر است
    snapshot_time: str
    data_quality_warning: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "total_score": round(self.total_score, 2),
            "level": self.level,
            "action": self.action,
            "factors": [f.to_dict() for f in self.factors],
            "independent_signals_count": self.independent_signals_count,
            "is_critical": self.is_critical,
            "snapshot_time": self.snapshot_time,
            "data_quality_warning": self.data_quality_warning,
        }


class SellPressureDetector:
    """موتور امتیازدهی فشار فروش."""

    def __init__(self, config: Dict):
        sp_cfg = config["sell_pressure"]
        self.weights = sp_cfg["weights"]
        self.levels = sp_cfg["levels"]
        self.thresholds = sp_cfg["thresholds"]
        self.operational_threshold = sp_cfg["operational_threshold"]
        # ضریب نرمال‌سازی: مقداری که امتیاز کامل می‌دهد
        self.norm = {
            "buyer_power_weakness":     {"full_at": 0.5},   # قدرت < 0.5 → ۲۰ امتیاز
            "real_money_outflow":       {"full_at": 0.05},  # خروج ۵٪ ارزش معاملات → ۲۰ امتیاز
            "sell_per_capita_superiority": {"full_at": 0.5}, # سرانه فروش ۱.۵ برابر خرید → ۱۵ امتیاز
            "negative_gap_last_vs_close": {"full_at": 0.02},# فاصله -۲٪ → ۱۵ امتیاز
            "supply_growth_rate":      {"full_at": 0.5},   # افزایش ۵۰٪ عرضه → ۱۵ امتیاز
            "demand_depletion_near_low": {"full_at": 1.0},  # تخلیه کامل + رسیدن به کف → ۱۵ امتیاز
        }

    # -------------------------------------------------------------------
    # شاخص ۱: ضعف قدرت خریدار حقیقی (۲۰ امتیاز)
    # -------------------------------------------------------------------
    def _factor_buyer_power_weakness(self, snap: MarketSnapshot) -> SellPressureFactorResult:
        buyer_power = snap.buyer_power  # = per_capita_buy / per_capita_sell
        # اگر قدرت < 1: خریدار ضعیف‌تر. کلید: 1 - ratio، نرمال‌سازی با 0.5
        # قدرت = 1 → 0 امتیاز، قدرت = 0.5 → کامل
        norm = _clamp((1.0 - buyer_power) / 0.5)
        score = norm * self.weights["buyer_power_weakness"]
        desc = (
            f"قدرت خریدار حقیقی = {buyer_power:.2f}. "
            f"اگر < ۱ باشد، خریدار ضعیف‌تر از فروشنده است."
        )
        return SellPressureFactorResult(
            name="buyer_power_weakness",
            label="ضعف قدرت خریدار حقیقی",
            max_points=self.weights["buyer_power_weakness"],
            raw_value=buyer_power,
            raw_unit="نسبت",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۲: خروج پول حقیقی (۲۰ امتیاز)
    # -------------------------------------------------------------------
    def _factor_real_money_outflow(self, snap: MarketSnapshot) -> SellPressureFactorResult:
        # real_money_flow_ratio = ورود/خروج نسبی به ارزش معاملات
        # اگر منفی (خروج)، نرمال‌سازی با 5٪
        ratio = snap.real_money_flow_ratio
        outflow_ratio = -ratio  # مثبت = مقدار خروج
        norm = _clamp(outflow_ratio / 0.05)
        score = norm * self.weights["real_money_outflow"]
        desc = (
            f"نسبت خروج پول حقیقی به ارزش معاملات = {outflow_ratio*100:.2f}٪. "
            f"خروج بیش از ۵٪ → امتیاز کامل."
        )
        return SellPressureFactorResult(
            name="real_money_outflow",
            label="خروج پول حقیقی",
            max_points=self.weights["real_money_outflow"],
            raw_value=outflow_ratio,
            raw_unit="٪ ارزش معاملات",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۳: برتری سرانه فروش به خرید (۱۵ امتیاز)
    # -------------------------------------------------------------------
    def _factor_sell_per_capita_superiority(self, snap: MarketSnapshot) -> SellPressureFactorResult:
        # ratio = per_capita_sell / per_capita_buy
        if snap.per_capita_buy_real > 0:
            ratio = snap.per_capita_sell_real / snap.per_capita_buy_real
        else:
            ratio = 10.0  # خرید حقیقی صفر = فروشندگان مسلط
        # اگر ratio > 1: فروشندگان هرکدام حجم بیشتری می‌فروشند
        # نرمال‌سازی: (ratio - 1) / 0.5 → full_at 1.5
        norm = _clamp((ratio - 1.0) / 0.5)
        score = norm * self.weights["sell_per_capita_superiority"]
        desc = (
            f"سرانه فروش حقیقی {ratio:.2f} برابر سرانه خرید است. "
            f"اگر > ۱.۵، فروشندگان حجمی قوی‌ترند."
        )
        return SellPressureFactorResult(
            name="sell_per_capita_superiority",
            label="برتری سرانه فروش به خرید",
            max_points=self.weights["sell_per_capita_superiority"],
            raw_value=ratio,
            raw_unit="نسبت",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۴: فاصله منفی آخرین قیمت از پایانی (۱۵ امتیاز)
    # -------------------------------------------------------------------
    def _factor_negative_gap_last_vs_close(self, snap: MarketSnapshot) -> SellPressureFactorResult:
        if snap.close_price > 0:
            gap = (snap.last_price - snap.close_price) / snap.close_price
        else:
            gap = 0.0
        # gap < 0 یعنی آخرین پایین‌تر از پایانی (فشار فروش)
        # نرمال‌سازی: -gap / 0.02 → full_at -2%
        norm = _clamp(-gap / 0.02)
        score = norm * self.weights["negative_gap_last_vs_close"]
        desc = (
            f"آخرین قیمت {gap*100:+.2f}٪ نسبت به پایانی است. "
            f"فاصله منفی بیش از -۲٪ → امتیاز کامل."
        )
        return SellPressureFactorResult(
            name="negative_gap_last_vs_close",
            label="فاصله منفی آخرین قیمت از پایانی",
            max_points=self.weights["negative_gap_last_vs_close"],
            raw_value=gap,
            raw_unit="٪",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۵: افزایش سرعت عرضه در بهترین قیمت (۱۵ امتیاز)
    # -------------------------------------------------------------------
    def _factor_supply_growth_rate(self, snap: MarketSnapshot,
                                   prev_snap: Optional[MarketSnapshot]) -> SellPressureFactorResult:
        if prev_snap is None or prev_snap.best_sell_volume > 0:
            if prev_snap is None:
                growth = 0.0
            else:
                growth = (snap.best_sell_volume - prev_snap.best_sell_volume) / max(prev_snap.best_sell_volume, 1)
        else:
            growth = 0.0
        # نرمال‌سازی: growth / 0.5 → full_at 50% increase
        norm = _clamp(growth / 0.5)
        score = norm * self.weights["supply_growth_rate"]
        desc = (
            f"حجم عرضه در بهترین قیمت فروش {growth*100:+.1f}٪ نسبت به نمونه قبلی. "
            f"افزایش ۵۰٪+ → امتیاز کامل."
        )
        return SellPressureFactorResult(
            name="supply_growth_rate",
            label="افزایش سرعت عرضه در بهترین قیمت",
            max_points=self.weights["supply_growth_rate"],
            raw_value=growth,
            raw_unit="٪",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۶: تخلیه تقاضا و نزدیک شدن به کف روز (۱۵ امتیاز)
    # -------------------------------------------------------------------
    def _factor_demand_depletion_near_low(self, snap: MarketSnapshot,
                                           prev_snap: Optional[MarketSnapshot]) -> SellPressureFactorResult:
        # الف) تخلیه تقاضا: کاهش حجم بهترین خرید نسبت به نمونه قبلی
        if prev_snap and prev_snap.best_buy_volume > 0:
            depletion = (prev_snap.best_buy_volume - snap.best_buy_volume) / prev_snap.best_buy_volume
        else:
            depletion = 0.0
        depletion_norm = _clamp(depletion / 0.5)  # کاهش 50٪ → 1

        # ب) نزدیک شدن به کف روز
        if snap.daily_high > snap.daily_low:
            price_position = (snap.last_price - snap.daily_low) / (snap.daily_high - snap.daily_low)
            # نزدیک به کف یعنی position نزدیک 0 → near_low = 1 - position
            near_low = _clamp(1.0 - price_position)
        else:
            near_low = 0.0

        # ترکیب: 60٪ تخلیه + 40٪ نزدیک به کف
        norm = _clamp(0.6 * depletion_norm + 0.4 * near_low)
        score = norm * self.weights["demand_depletion_near_low"]
        desc = (
            f"تخلیه تقاضا: {depletion*100:.1f}٪، "
            f"موقعیت قیمت نسبت به کف: {(1 - near_low)*100:.0f}٪. "
            f"ترکیب دو شاخص: {norm*100:.0f}٪."
        )
        return SellPressureFactorResult(
            name="demand_depletion_near_low",
            label="تخلیه تقاضا و نزدیک شدن به کف روز",
            max_points=self.weights["demand_depletion_near_low"],
            raw_value=norm,
            raw_unit="شاخص ترکیبی ۰-۱",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # محاسبه نهایی
    # -------------------------------------------------------------------
    def evaluate(self, snap: MarketSnapshot,
                 prev_snap: Optional[MarketSnapshot] = None) -> SellPressureResult:
        """محاسبه امتیاز فشار فروش برای یک نمونه."""
        # اگر داده ناقص باشد، هشدار ثبت ولی محاسبه تا حد ممکن انجام می‌شود
        data_warning = None
        if not snap.data_complete:
            data_warning = (
                f"داده‌های ناقص: {', '.join(snap.missing_fields)}"
            )

        factors = [
            self._factor_buyer_power_weakness(snap),
            self._factor_real_money_outflow(snap),
            self._factor_sell_per_capita_superiority(snap),
            self._factor_negative_gap_last_vs_close(snap),
            self._factor_supply_growth_rate(snap, prev_snap),
            self._factor_demand_depletion_near_low(snap, prev_snap),
        ]

        total = sum(f.score for f in factors)
        # شمارش شاخص‌های با امتیاز >= 50٪ (برای تایید هشدار قرمز)
        independent_signals = sum(1 for f in factors if f.normalized >= 0.5)

        # تعیین سطح
        level, action = self._determine_level(total)
        is_critical = total >= 65

        return SellPressureResult(
            total_score=total,
            level=level,
            action=action,
            factors=factors,
            independent_signals_count=independent_signals,
            is_critical=is_critical,
            snapshot_time=snap.tehran_time,
            data_quality_warning=data_warning,
        )

    def _determine_level(self, score: float) -> tuple:
        """تعیین سطح و اقدام پیشنهادی بر اساس امتیاز."""
        if score <= 24:
            return self.levels["0-24"]["label"], self.levels["0-24"]["action"]
        elif score <= 34:
            return self.levels["25-34"]["label"], self.levels["25-34"]["action"]
        elif score <= 49:
            return self.levels["35-49"]["label"], self.levels["35-49"]["action"]
        elif score <= 64:
            return self.levels["50-64"]["label"], self.levels["50-64"]["action"]
        elif score <= 79:
            return self.levels["65-79"]["label"], self.levels["65-79"]["action"]
        else:
            return self.levels["80-100"]["label"], self.levels["80-100"]["action"]
