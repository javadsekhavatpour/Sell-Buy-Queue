"""
alert_engine.py
موتور ترکیب و صدور هشدار — نسخه ۲.۰ (دو موتور مستقل فروش/خرید).

توابع مستقل:
  - tier(score):    طبقه‌بندی امتیاز یک موتور (عادی → بحرانی)
  - classify(sell, buy): ترکیب دو امتیاز و تشخیص جهت فشار بازار

منطق classify (از alerts.py):
  sell≥50 و buy≥50 → تقابل شدید عرضه و تقاضا
  sell≥50          → فشار فروش / غلبه فروشندگان
  buy≥50           → فشار خرید / غلبه خریداران
  sell≥35          → هشدار اولیه فروش
  buy≥35           → هشدار اولیه خرید
  sell≥25 یا buy≥25 → مراقبت
  وگرنه            → وضعیت عادی

قانون ضد تکرار: هر هشدار فقط یک بار هنگام ورود به سطح جدید صادر می‌شود.
سرعت نردبان سفارش‌ها (بعد سوم) اختیاری است و در صورت عدم ارائه بی‌اثر می‌ماند.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Optional
from .sell_pressure import SellPressureResult
from .smart_accumulation import BuyPressureResult


# -----------------------------------------------------------------------
# توابع مستقل طبقه‌بندی (مطابق alerts.py پیشنهادی)
# -----------------------------------------------------------------------

def tier(x: Optional[float]) -> str:
    """طبقه‌بندی امتیاز یک موتور به سطح کیفی."""
    if x is None:
        return "نامشخص"
    if x >= 80:
        return "بحرانی"
    if x >= 65:
        return "بسیار قوی"
    if x >= 50:
        return "قوی"
    if x >= 35:
        return "هشدار اولیه"
    if x >= 25:
        return "مراقبت"
    return "عادی"


def classify(sell: Optional[float], buy: Optional[float]) -> str:
    """ترکیب دو امتیاز و تشخیص جهت فشار بازار."""
    if sell is None or buy is None:
        return "داده ناکافی"
    if sell >= 50 and buy >= 50:
        return "تقابل شدید عرضه و تقاضا؛ نیازمند بررسی جذب یا غلبه فروش"
    if sell >= 50:
        return "فشار فروش / غلبه فروشندگان"
    if buy >= 50:
        return "فشار خرید / غلبه خریداران"
    if sell >= 35:
        return "هشدار اولیه فروش"
    if buy >= 35:
        return "هشدار اولیه خرید"
    if sell >= 25 or buy >= 25:
        return "مراقبت"
    return "وضعیت عادی"


# -----------------------------------------------------------------------
# سطح هشدار
# -----------------------------------------------------------------------

class AlertLevel(Enum):
    NONE = "بدون هشدار"
    WATCH = "مراقبت"
    EARLY_SELL = "هشدار اولیه فروش"
    EARLY_BUY = "هشدار اولیه خرید"
    RED = "فشار فروش قوی"
    GREEN = "فشار خرید قوی"
    PURPLE = "تقابل شدید"


@dataclass
class AlertEvent:
    """یک رویداد هشدار."""
    timestamp: str
    level: AlertLevel
    title: str
    message: str
    sell_score: float
    buy_score: float
    classification: str        # خروجی classify()
    sell_tier: str             # خروجی tier() برای فروش
    buy_tier: str              # خروجی tier() برای خرید
    suggested_action: str
    is_critical: bool

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "sell_score": round(self.sell_score, 2),
            "buy_score": round(self.buy_score, 2),
            "classification": self.classification,
            "sell_tier": self.sell_tier,
            "buy_tier": self.buy_tier,
            "suggested_action": self.suggested_action,
            "is_critical": self.is_critical,
        }


@dataclass
class CombinedState:
    """وضعیت ترکیب دو موتور در یک لحظه."""
    timestamp: str
    sell_score: float
    buy_score: float
    sell_tier: str
    buy_tier: str
    classification: str        # خروجی classify()
    combination_key: str       # high_sell_low_buy و ...
    combination_label: str     # برچسب فارسی از combination_matrix
    interpretation: str
    alert: Optional[AlertEvent]
    sell_engine_status: str    # official | warming_up
    buy_engine_status: str

    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp,
            "sell_score": round(self.sell_score, 2),
            "buy_score": round(self.buy_score, 2),
            "sell_tier": self.sell_tier,
            "buy_tier": self.buy_tier,
            "classification": self.classification,
            "combination_key": self.combination_key,
            "combination_label": self.combination_label,
            "interpretation": self.interpretation,
            "alert": self.alert.to_dict() if self.alert else None,
            "sell_engine_status": self.sell_engine_status,
            "buy_engine_status": self.buy_engine_status,
        }


class AlertEngine:
    """موتور صدور هشدار بر اساس ترکیب دو موتور فروش و خرید."""

    def __init__(self, config: Dict):
        self.cfg = config
        self.combination = config["combination_matrix"]
        self.alerts_cfg = config["alerts"]
        self.classify_logic = self.alerts_cfg.get("classify_logic", {})
        self.last_level: AlertLevel = AlertLevel.NONE
        self.events: List[AlertEvent] = []

    def evaluate(
        self,
        sell_result: SellPressureResult,
        buy_result: BuyPressureResult,
    ) -> CombinedState:
        """ترکیب خروجی دو موتور و تعیین هشدار."""
        sell_score = sell_result.total_score
        buy_score = buy_result.total_score

        sell_t = tier(sell_score)
        buy_t = tier(buy_score)
        classification = classify(sell_score, buy_score)

        # تعیین کلید ترکیب (۴ حالت)
        high_sell = sell_score >= 50
        high_buy = buy_score >= 50
        if high_sell and not high_buy:
            key = "high_sell_low_buy"
        elif high_sell and high_buy:
            key = "high_sell_high_buy"
        elif not high_sell and high_buy:
            key = "low_sell_high_buy"
        else:
            key = "low_sell_low_buy"

        combination_label = self.combination.get(key, classification)
        interpretation = self._interpretation(sell_score, buy_score, high_sell, high_buy)

        # تعیین سطح هشدار فعلی
        current_level = self._determine_level(sell_score, buy_score)

        # ضدتکرار: فقط هنگام تغییر سطح، هشدار جدید صادر کن
        alert = None
        if current_level != self.last_level and current_level != AlertLevel.NONE:
            alert = self._make_alert(
                current_level, sell_result, buy_result,
                classification, combination_label, interpretation,
            )
            self.events.append(alert)
        elif current_level == AlertLevel.NONE and self.last_level != AlertLevel.NONE:
            alert = AlertEvent(
                timestamp=sell_result.snapshot_time,
                level=AlertLevel.NONE,
                title="بازگشت به وضعیت عادی",
                message="وضعیت از سطح هشدار خارج شد.",
                sell_score=sell_score, buy_score=buy_score,
                classification=classification,
                sell_tier=sell_t, buy_tier=buy_t,
                suggested_action="ادامه پایش عادی",
                is_critical=False,
            )
            self.events.append(alert)

        self.last_level = current_level

        return CombinedState(
            timestamp=sell_result.snapshot_time,
            sell_score=sell_score, buy_score=buy_score,
            sell_tier=sell_t, buy_tier=buy_t,
            classification=classification,
            combination_key=key,
            combination_label=combination_label,
            interpretation=interpretation,
            alert=alert,
            sell_engine_status=sell_result.engine_status,
            buy_engine_status=buy_result.engine_status,
        )

    def _determine_level(self, sell: float, buy: float) -> AlertLevel:
        """تعیین سطح هشدار بر اساس امتیازها."""
        # اولویت: تقابل > قرمز > سبز > هشدار اولیه > مراقبت
        if sell >= 50 and buy >= 50:
            return AlertLevel.PURPLE
        if sell >= 50:
            return AlertLevel.RED
        if buy >= 50:
            return AlertLevel.GREEN
        if sell >= 35:
            return AlertLevel.EARLY_SELL
        if buy >= 35:
            return AlertLevel.EARLY_BUY
        if sell >= 25 or buy >= 25:
            return AlertLevel.WATCH
        return AlertLevel.NONE

    def _interpretation(self, sell: float, buy: float,
                        high_sell: bool, high_buy: bool) -> str:
        if high_sell and high_buy:
            return ("تقابل شدید عرضه و تقاضا. باید بررسی شود که آیا عرضه در حال "
                    "جذب شدن است (خریدار غالب) یا خریداران در حال عقب‌نشینی. "
                    "فقط بالا بودن هم‌زمان دو امتیاز برای سیگنال قطعی کافی نیست.")
        if high_sell:
            return ("فشار فروش قوی و خریداران ضعیف‌اند. خطر خروج جدی؛ "
                    "نقدشوندگی و احتمال تشکیل صف فروش را بررسی کنید.")
        if high_buy:
            return ("فشار خرید قوی و فروشندگان ضعیف‌اند. خریداران قدرتمند "
                    "در حال جذب عرضه‌اند؛ فرصت احتمالی ورود.")
        if sell >= 35:
            return "نشانه‌های اولیه فشار فروش ظاهر شده است."
        if buy >= 35:
            return "نشانه‌های اولیه فشار خرید ظاهر شده است."
        if sell >= 25 or buy >= 25:
            return "تغییرات خفیف در توزیع خریداران/فروشندگان — مراقبت."
        return "وضعیت عادی — بدون سیگنال خاص."

    def _make_alert(
        self,
        level: AlertLevel,
        sp: SellPressureResult,
        bp: BuyPressureResult,
        classification: str,
        combination_label: str,
        interpretation: str,
    ) -> AlertEvent:
        """ساخت رویداد هشدار."""
        sell_s, buy_s = sp.total_score, bp.total_score
        if level == AlertLevel.PURPLE:
            title = "تقابل شدید عرضه و تقاضا"
            message = (f"هر دو موتور بالای ۵۰ هستند (فروش={sell_s:.0f}، خرید={buy_s:.0f}). "
                       f"{interpretation}")
            action = "بررسی جذب عرضه قبل از تصمیم"
            critical = True
        elif level == AlertLevel.RED:
            title = "فشار فروش قوی"
            message = (f"امتیاز فروش={sell_s:.0f}، خرید={buy_s:.0f}. "
                       f"{interpretation}")
            action = "بررسی نقدشوندگی و احتمال خروج"
            critical = True
        elif level == AlertLevel.GREEN:
            title = "فشار خرید قوی"
            message = (f"امتیاز خرید={buy_s:.0f}، فروش={sell_s:.0f}. "
                       f"{interpretation}")
            action = "بررسی فرصت ورود"
            critical = False
        elif level == AlertLevel.EARLY_SELL:
            title = "هشدار اولیه فروش"
            message = f"امتیاز فروش به {sell_s:.0f} رسید."
            action = "افزایش پایش فروش"
            critical = False
        elif level == AlertLevel.EARLY_BUY:
            title = "هشدار اولیه خرید"
            message = f"امتیاز خرید به {buy_s:.0f} رسید."
            action = "افزایش پایش خرید"
            critical = False
        elif level == AlertLevel.WATCH:
            title = "مراقبت"
            message = (f"یکی از موتورها به محدوده مراقبت رسید "
                       f"(فروش={sell_s:.0f}، خرید={buy_s:.0f}).")
            action = "ثبت تغییرات"
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
            sell_score=sell_s,
            buy_score=buy_s,
            classification=classification,
            sell_tier=tier(sell_s),
            buy_tier=tier(buy_s),
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
