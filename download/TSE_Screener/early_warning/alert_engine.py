"""
alert_engine.py
موتور ترکیب و صدور هشدار زودهنگام.

سه سطح هشدار:
  - زرد (مراقبت):      فشار فروش >= 35
  - قرمز (ریسک خروج):  فشار فروش >= 50 با ضعف جمع‌آوری + حداقل ۲ نشانه مستقل
  - سبز (جذب عرضه):    جمع‌آوری >= 40 با شواهد جذب عرضه

منطق ترکیب (۴ وضعیت):
  فشار فروش بالا + جمع‌آوری ضعیف   → خطر خروج
  فشار فروش بالا + جمع‌آوری بالا   → جذب عرضه توسط خریدار قوی (خروج عجولانه توصیه نمی‌شود)
  فشار فروش پایین + جمع‌آوری بالا  → فرصت احتمالی ورود
  فشار فروش پایین + جمع‌آوری ضعیف  → بدون سیگنال خاص

قانون ضد تکرار: هر هشدار فقط یک بار هنگام ورود به سطح جدید صادر می‌شود.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Tuple
from .sell_pressure import SellPressureResult
from .smart_accumulation import AccumulationResult


class AlertLevel(Enum):
    NONE = "بدون هشدار"
    YELLOW = "هشدار زرد - مراقبت"
    RED = "هشدار قرمز - ریسک خروج"
    GREEN = "هشدار سبز - جذب عرضه"
    ORANGE = "جذب عرضه + فشار فروش هم‌زمان"


@dataclass
class AlertEvent:
    """یک رویداد هشدار."""
    timestamp: str
    level: AlertLevel
    title: str
    message: str
    sell_pressure_score: float
    accumulation_score: float
    combination_state: str        # یکی از ۴ وضعیت ترکیب
    suggested_action: str
    is_critical: bool

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "sell_pressure_score": round(self.sell_pressure_score, 2),
            "accumulation_score": round(self.accumulation_score, 2),
            "combination_state": self.combination_state,
            "suggested_action": self.suggested_action,
            "is_critical": self.is_critical,
        }


@dataclass
class CombinedState:
    """وضعیت ترکیب دو موتور در یک لحظه."""
    timestamp: str
    sell_pressure_score: float
    accumulation_score: float
    combination_label: str
    combination_state_key: str    # high_pressure_low_accumulation و ...
    interpretation: str           # توضیح فارسی
    alert: Optional[AlertEvent]
    sell_level: str
    acc_level: str

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "sell_pressure_score": round(self.sell_pressure_score, 2),
            "accumulation_score": round(self.accumulation_score, 2),
            "combination_label": self.combination_label,
            "combination_state_key": self.combination_state_key,
            "interpretation": self.interpretation,
            "alert": self.alert.to_dict() if self.alert else None,
            "sell_level": self.sell_level,
            "acc_level": self.acc_level,
        }


class AlertEngine:
    """موتور صدور هشدار بر اساس ترکیب دو موتور تحلیلی."""

    def __init__(self, config: Dict):
        self.cfg = config
        self.combination = config["combination_matrix"]
        self.alerts_cfg = config["alerts"]
        # آستانه‌ها
        self.yellow_threshold = 35    # فشار فروش >= 35
        self.red_threshold = 50       # فشار فروش >= 50
        self.green_threshold = 40     # جمع‌آوری >= 40
        self.weak_acc_threshold = 40
        # آخرین سطح فعال برای ضدتکرار
        self.last_level: AlertLevel = AlertLevel.NONE
        self.events: List[AlertEvent] = []

    def evaluate(
        self,
        sp_result: SellPressureResult,
        acc_result: AccumulationResult
    ) -> CombinedState:
        """ترکیب دو خروجی و تعیین هشدار."""
        sp_score = sp_result.total_score
        acc_score = acc_result.total_score

        # تعیین وضعیت ترکیب (۴ حالت)
        high_sp = sp_score >= self.red_threshold
        high_acc = acc_score >= self.green_threshold

        if high_sp and not high_acc:
            state_key = "high_pressure_low_accumulation"
            interpretation = (
                "فشار فروش بالا و شواهد جمع‌آوری ضعیف است. "
                "خطر خروج جدی."
            )
        elif high_sp and high_acc:
            state_key = "high_pressure_high_accumulation"
            interpretation = (
                "فشار فروش بالا است، اما خریداران قدرتمند در حال جذب عرضه هستند؛ "
                "احتمال توزیع و جمع‌آوری هم‌زمان. "
                "خروج عجولانه توصیه نمی‌شود؛ نیاز به بررسی رفتار سفارش‌ها."
            )
        elif not high_sp and high_acc:
            state_key = "low_pressure_high_accumulation"
            interpretation = (
                "فشار فروش پایین و خریداران قدرتمند در حال جمع‌آوری هستند. "
                "فرصت احتمالی ورود."
            )
        else:
            state_key = "low_pressure_low_accumulation"
            interpretation = "بدون سیگنال خاص. وضعیت عادی."

        combination_label = self.combination[state_key]

        # تعیین سطح هشدار فعلی
        current_level = self._determine_alert_level(
            sp_result, acc_result, state_key
        )

        # ضدتکرار: فقط هنگام تغییر سطح، هشدار جدید صادر کن
        alert = None
        if current_level != self.last_level and current_level != AlertLevel.NONE:
            alert = self._make_alert(
                current_level, sp_result, acc_result,
                state_key, combination_label, interpretation
            )
            self.events.append(alert)
        elif current_level == AlertLevel.NONE and self.last_level != AlertLevel.NONE:
            # بازگشت به حالت عادی
            alert = AlertEvent(
                timestamp=sp_result.snapshot_time,
                level=AlertLevel.NONE,
                title="بازگشت به وضعیت عادی",
                message="وضعیت از سطح هشدار خارج شد.",
                sell_pressure_score=sp_score,
                accumulation_score=acc_score,
                combination_state=combination_label,
                suggested_action="ادامه پایش عادی",
                is_critical=False,
            )
            self.events.append(alert)

        self.last_level = current_level

        return CombinedState(
            timestamp=sp_result.snapshot_time,
            sell_pressure_score=sp_score,
            accumulation_score=acc_score,
            combination_label=combination_label,
            combination_state_key=state_key,
            interpretation=interpretation,
            alert=alert,
            sell_level=sp_result.level,
            acc_level=acc_result.level,
        )

    def _determine_alert_level(
        self,
        sp: SellPressureResult,
        acc: AccumulationResult,
        state_key: str
    ) -> AlertLevel:
        """تعیین سطح هشدار بر اساس امتیازها و قوانین."""
        # اولویت: قرمز > سبز > زرد > نارنجی > هیچ
        sp_score = sp.total_score
        acc_score = acc.total_score

        # ----- هشدار قرمز (ریسک خروج) -----
        # شرط: فشار فروش >= 50 + جمع‌آوری ضعیف + حداقل ۲ نشانه مستقل
        if (sp_score >= self.red_threshold and
            acc_score < self.weak_acc_threshold and
            sp.independent_signals_count >= 2):
            return AlertLevel.RED

        # ----- وضعیت نارنجی (جذب + فشار هم‌زمان) -----
        # فشار فروش >= 50 ولی جمع‌آوری >= 40 (خریدار قوی در حال جذب)
        if (sp_score >= self.red_threshold and
            acc_score >= self.green_threshold and
            acc.absorption_evidence):
            return AlertLevel.ORANGE

        # ----- هشدار سبز (جذب عرضه) -----
        # جمع‌آوری >= 40 + شواهد جذب عرضه
        if acc_score >= self.green_threshold and acc.absorption_evidence:
            return AlertLevel.GREEN

        # ----- هشدار زرد (مراقبت) -----
        # فشار فروش >= 35
        if sp_score >= self.yellow_threshold:
            return AlertLevel.YELLOW

        return AlertLevel.NONE

    def _make_alert(
        self,
        level: AlertLevel,
        sp: SellPressureResult,
        acc: AccumulationResult,
        state_key: str,
        combination_label: str,
        interpretation: str
    ) -> AlertEvent:
        """ساخت رویداد هشدار."""
        if level == AlertLevel.RED:
            title = "هشدار جدی ریسک خروج"
            message = (
                f"فشار فروش در حال تشدید است (امتیاز {sp.total_score:.0f}). "
                f"جمع‌آوری ضعیف است (امتیاز {acc.total_score:.0f}). "
                f"{self.alerts_cfg['red']['message']}"
            )
            action = "بررسی نقدشوندگی و احتمال خروج"
            critical = True
        elif level == AlertLevel.ORANGE:
            title = "جذب عرضه + فشار فروش هم‌زمان"
            message = (
                f"فشار فروش بالا (امتیاز {sp.total_score:.0f})، اما خریداران قدرتمند "
                f"در حال جذب عرضه هستند (امتیاز {acc.total_score:.0f}). "
                f"احتمال توزیع و جمع‌آوری هم‌زمان. "
                f"خروج عجولانه توصیه نمی‌شود."
            )
            action = "بررسی رفتار سفارش‌ها قبل از تصمیم"
            critical = False
        elif level == AlertLevel.GREEN:
            title = "جذب عرضه توسط خریدار قوی"
            message = (
                f"جمع‌آوری قابل توجه (امتیاز {acc.total_score:.0f}) با شواهد جذب عرضه. "
                f"{self.alerts_cfg['green']['message']}"
            )
            action = "بررسی فرصت ورود"
            critical = False
        elif level == AlertLevel.YELLOW:
            title = "نشانه‌های اولیه ضعف تقاضا"
            message = (
                f"امتیاز فشار فروش به {sp.total_score:.0f} رسید. "
                f"{self.alerts_cfg['yellow']['message']}"
            )
            action = "ثبت تغییرات و افزایش پایش"
            critical = False
        else:
            title = ""
            message = ""
            action = ""
            critical = False

        return AlertEvent(
            timestamp=sp.snapshot_time,
            level=level,
            title=title,
            message=message,
            sell_pressure_score=sp.total_score,
            accumulation_score=acc.total_score,
            combination_state=combination_label,
            suggested_action=action,
            is_critical=critical,
        )

    def reset(self):
        """بازنشانی موتور (برای روز جدید)."""
        self.last_level = AlertLevel.NONE
        self.events = []

    def get_all_events(self) -> List[AlertEvent]:
        """همه رویدادهای هشدار ثبت‌شده."""
        return self.events.copy()
