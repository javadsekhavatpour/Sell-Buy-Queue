"""
smart_accumulation.py
موتور تشخیص جمع‌آوری سهم توسط خریداران قدرتمند (۰-۱۰۰).

شش شاخص مستقل (مجموع امتیاز = ۱۰۰):
  1. قدرت خرید حقیقی                    - 20
  2. ورود پول حقیقی                     - 20
  3. برتری تعداد خریداران حقیقی         - 10
  4. جذب عرضه و ماندگاری تقاضا          - 20
  5. مقاومت قیمت در برابر فشار فروش    - 20
  6. تداوم رفتار خرید در چند بازه زمانی - 10

نکته: اگر خریداران فقط در یک لحظه وارد شوند، نباید آن را
      جمع‌آوری معتبر تلقی کنیم. باید تداوم رفتار آن‌ها را در چند
      بازه متوالی بررسی کنیم.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from .data_collector import MarketSnapshot


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class AccumulationFactorResult:
    name: str
    label: str
    max_points: float
    raw_value: float
    raw_unit: str
    normalized: float
    score: float
    description: str

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
class AccumulationResult:
    total_score: float
    level: str
    factors: List[AccumulationFactorResult]
    is_strong: bool                  # آیا جمع‌آوری قابل اعتماد است
    snapshot_time: str
    absorption_evidence: bool        # شواهد جذب عرضه
    data_quality_warning: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "total_score": round(self.total_score, 2),
            "level": self.level,
            "factors": [f.to_dict() for f in self.factors],
            "is_strong": self.is_strong,
            "snapshot_time": self.snapshot_time,
            "absorption_evidence": self.absorption_evidence,
            "data_quality_warning": self.data_quality_warning,
        }


class SmartAccumulationDetector:
    """موتور امتیازدهی جمع‌آوری سهم."""

    def __init__(self, config: Dict):
        acc_cfg = config["accumulation"]
        self.weights = acc_cfg["weights"]
        self.levels = acc_cfg["levels"]
        self.thresholds = acc_cfg["thresholds"]
        self.identification_threshold = acc_cfg["identification_threshold"]
        self.history_required = config.get("history_required_samples", 5)

    # -------------------------------------------------------------------
    # شاخص ۱: قدرت خرید حقیقی (۲۰ امتیاز)
    # -------------------------------------------------------------------
    def _factor_real_buyer_power(self, snap: MarketSnapshot) -> AccumulationFactorResult:
        buyer_power = snap.buyer_power  # per_capita_buy / per_capita_sell
        # اگر > 1: خریدار قوی. نرمال‌سازی با 1.5 → امتیاز کامل
        norm = _clamp((buyer_power - 1.0) / 0.5)
        score = norm * self.weights["real_buyer_power"]
        desc = (
            f"قدرت خریدار حقیقی = {buyer_power:.2f}. "
            f"اگر > ۱.۵، خریداران حجمی قوی‌ترند."
        )
        return AccumulationFactorResult(
            name="real_buyer_power",
            label="قدرت خرید حقیقی",
            max_points=self.weights["real_buyer_power"],
            raw_value=buyer_power,
            raw_unit="نسبت",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۲: ورود پول حقیقی (۲۰ امتیاز)
    # -------------------------------------------------------------------
    def _factor_real_money_inflow(self, snap: MarketSnapshot) -> AccumulationFactorResult:
        inflow_ratio = snap.real_money_flow_ratio  # مثبت = ورود
        # نرمال‌سازی با 5٪ ورود → امتیاز کامل
        norm = _clamp(inflow_ratio / 0.05)
        score = norm * self.weights["real_money_inflow"]
        desc = (
            f"ورود پول حقیقی = {inflow_ratio*100:+.2f}٪ ارزش معاملات. "
            f"ورود > ۵٪ → امتیاز کامل."
        )
        return AccumulationFactorResult(
            name="real_money_inflow",
            label="ورود پول حقیقی",
            max_points=self.weights["real_money_inflow"],
            raw_value=inflow_ratio,
            raw_unit="٪ ارزش معاملات",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۳: برتری تعداد خریداران حقیقی (۱۰ امتیاز)
    # -------------------------------------------------------------------
    def _factor_real_buyer_count_superiority(self, snap: MarketSnapshot) -> AccumulationFactorResult:
        if snap.real_sell_count > 0:
            ratio = snap.real_buy_count / snap.real_sell_count
        else:
            ratio = 1.0
        # اگر > 1.5 → تعداد خریداران بیشتر → امتیاز کامل
        norm = _clamp((ratio - 1.0) / 0.5)
        score = norm * self.weights["real_buyer_count_superiority"]
        desc = (
            f"تعداد خریداران حقیقی {ratio:.2f} برابر فروشندگان است. "
            f"اگر > ۱.۵، تعداد خریداران برتری دارد."
        )
        return AccumulationFactorResult(
            name="real_buyer_count_superiority",
            label="برتری تعداد خریداران حقیقی",
            max_points=self.weights["real_buyer_count_superiority"],
            raw_value=ratio,
            raw_unit="نسبت",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۴: جذب عرضه و ماندگاری تقاضا (۲۰ امتیاز)
    # -------------------------------------------------------------------
    def _factor_supply_absorption_persistence(
        self, snap: MarketSnapshot,
        prev_snap: Optional[MarketSnapshot]
    ) -> AccumulationFactorResult:
        # الف) جذب عرضه:
        # Absorption = حجم معاملات انجام‌شده / حجم عرضه موجود در بهترین قیمت
        # اگر عرضه زیاد بوده ولی معامله زیادی انجام شده، جذب رخ داده
        if snap.best_sell_volume > 0:
            # حجم معاملات این بازه (تقریبی: کل حجم امروز - دیروز)
            # برای نمونه لحظه‌ای: نسبتی از تجمعی
            executed = snap.total_volume
            absorption = _clamp(executed / max(snap.best_sell_volume * 10, 1))
        else:
            absorption = 0.0

        # ب) ماندگاری تقاضا:
        # اگر حجم بهترین خرید نسبت به نمونه قبلی افزایش یا ثابت مانده
        if prev_snap and prev_snap.best_buy_volume > 0:
            persistence = _clamp(snap.best_buy_volume / prev_snap.best_buy_volume - 0.8)
        else:
            persistence = 0.5  # نامشخص

        # ترکیب: 60٪ جذب + 40٪ ماندگاری
        norm = _clamp(0.6 * absorption + 0.4 * persistence)
        score = norm * self.weights["supply_absorption_persistence"]
        desc = (
            f"جذب عرضه: {absorption:.2f}، ماندگاری تقاضا: {persistence:.2f}. "
            f"اگر عرضه زیاد فروخته شده ولی قیمت نیفتاده، جذب قوی است."
        )
        return AccumulationFactorResult(
            name="supply_absorption_persistence",
            label="جذب عرضه و ماندگاری تقاضا",
            max_points=self.weights["supply_absorption_persistence"],
            raw_value=norm,
            raw_unit="شاخص ترکیبی ۰-۱",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۵: مقاومت قیمت در برابر فشار فروش (۲۰ امتیاز)
    # -------------------------------------------------------------------
    def _factor_price_resistance(self, snap: MarketSnapshot) -> AccumulationFactorResult:
        # اگر حجم معامله زیاد ولی قیمت نزدیک پایانی یا بالاتر
        # price_hold = 1 - max(0, (close - last) / (close * 0.02))
        # آخرین >= پایانی → 1, آخرین = پایانی - 2٪ → 0
        if snap.close_price > 0:
            gap = (snap.last_price - snap.close_price) / snap.close_price
            price_hold = _clamp((gap + 0.02) / 0.02)  # gap=-2%→0, gap=0→1, gap=+2%→1
        else:
            gap = 0.0
            price_hold = 0.0

        # وزن‌دهی با حجم معاملات (اگر حجم کم است، مقاومت قابل اعتماد نیست)
        # نرمال‌سازی حجم به‌طور کلی به 0-1 با آستانه ۱۰ میلیون سهم
        vol_norm = _clamp(snap.total_volume / 10_000_000)
        # مقاومت = قیمت مقاوم × نشانه حجم
        norm = _clamp(price_hold * (0.5 + 0.5 * vol_norm))
        score = norm * self.weights["price_resistance"]
        desc = (
            f"موقعیت قیمت نسبت به پایانی: {gap*100:+.2f}٪. "
            f"اگر با وجود فشار فروش، قیمت مقاومت کند، نشانه خریدار قوی است."
        )
        return AccumulationFactorResult(
            name="price_resistance",
            label="مقاومت قیمت در برابر فشار فروش",
            max_points=self.weights["price_resistance"],
            raw_value=price_hold,
            raw_unit="شاخص ۰-۱",
            normalized=norm,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # شاخص ۶: تداوم رفتار خرید در چند بازه زمانی (۱۰ امتیاز)
    # -------------------------------------------------------------------
    def _factor_buying_continuity(
        self, snap: MarketSnapshot,
        history: List[MarketSnapshot]
    ) -> AccumulationFactorResult:
        # بررسی ۵ نمونه قبلی: چند نمونه ورود پول مثبت داشته‌ایم؟
        if len(history) < self.history_required:
            recent = history[-len(history):]
        else:
            recent = history[-self.history_required:]

        if not recent:
            continuity = 0.0
        else:
            positive_count = sum(1 for h in recent if h.real_money_flow_ratio > 0)
            strong_count = sum(1 for h in recent if h.buyer_power > 1.2)
            # تداوم = میانگین دو شاخص
            continuity = _clamp(
                0.5 * (positive_count / len(recent)) +
                0.5 * (strong_count / len(recent))
            )
        score = continuity * self.weights["buying_continuity"]
        desc = (
            f"از {len(recent)} نمونه قبلی، {sum(1 for h in recent if h.real_money_flow_ratio > 0)} نمونه ورود پول مثبت داشت. "
            f"تداوم = {continuity*100:.0f}٪."
        )
        return AccumulationFactorResult(
            name="buying_continuity",
            label="تداوم رفتار خرید در چند بازه زمانی",
            max_points=self.weights["buying_continuity"],
            raw_value=continuity,
            raw_unit="شاخص ۰-۱",
            normalized=continuity,
            score=score,
            description=desc,
        )

    # -------------------------------------------------------------------
    # محاسبه نهایی
    # -------------------------------------------------------------------
    def evaluate(
        self, snap: MarketSnapshot,
        prev_snap: Optional[MarketSnapshot] = None,
        history: Optional[List[MarketSnapshot]] = None
    ) -> AccumulationResult:
        """محاسبه امتیاز جمع‌آوری برای یک نمونه."""
        if history is None:
            history = []

        data_warning = None
        if not snap.data_complete:
            data_warning = f"داده‌های ناقص: {', '.join(snap.missing_fields)}"

        factors = [
            self._factor_real_buyer_power(snap),
            self._factor_real_money_inflow(snap),
            self._factor_real_buyer_count_superiority(snap),
            self._factor_supply_absorption_persistence(snap, prev_snap),
            self._factor_price_resistance(snap),
            self._factor_buying_continuity(snap, history),
        ]

        total = sum(f.score for f in factors)
        level = self._determine_level(total)
        is_strong = total >= self.identification_threshold

        # شواهد جذب عرضه: شاخص ۴ و ۵ با امتیاز >= 50٪
        absorption_evidence = (
            factors[3].normalized >= 0.5 and
            factors[4].normalized >= 0.5
        )

        return AccumulationResult(
            total_score=total,
            level=level,
            factors=factors,
            is_strong=is_strong,
            snapshot_time=snap.tehran_time,
            absorption_evidence=absorption_evidence,
            data_quality_warning=data_warning,
        )

    def _determine_level(self, score: float) -> str:
        if score <= 24:
            return self.levels["0-24"]["label"]
        elif score <= 39:
            return self.levels["25-39"]["label"]
        elif score <= 59:
            return self.levels["40-59"]["label"]
        elif score <= 79:
            return self.levels["60-79"]["label"]
        else:
            return self.levels["80-100"]["label"]
