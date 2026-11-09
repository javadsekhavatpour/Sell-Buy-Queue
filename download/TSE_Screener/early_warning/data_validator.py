"""
data_validator.py
اعتبارسنجی نمونه‌های دریافتی پیش از ورود به موتورهای تحلیلی.

اصل معماری: «اگر فیلدی قابل دریافت نباشد، آن را حدس نمی‌زنیم؛
            امتیاز قابل محاسبه و وضعیت نقص داده جداگانه ثبت می‌شود.»
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from .data_collector import MarketSnapshot


@dataclass
class DataQualityReport:
    """گزارش کیفیت داده برای یک نمونه."""
    snapshot_timestamp: str
    is_valid: bool                      # قابل استفاده برای محاسبه
    completeness_pct: float             # درصد فیلدهای موجود
    missing_critical_fields: List[str]  # فیلدهای حیاتی مفقود (محاسبه غیرممکن)
    missing_optional_fields: List[str]  # فیلدهای اختیاری مفقود (محاسبه با کاهش دقت)
    anomalies: List[str]               # ناهنجاری‌های منطقی
    field_status: Dict[str, str] = field(default_factory=dict)  # per-field: 'ok'|'missing'|'anomaly'

    def summary(self) -> str:
        out = [
            f"نمونه {self.snapshot_timestamp}",
            f"  معتبر: {self.is_valid}",
            f"  کمال: {self.completeness_pct:.0f}%",
        ]
        if self.missing_critical_fields:
            out.append(f"  فیلدهای حیاتی مفقود: {', '.join(self.missing_critical_fields)}")
        if self.missing_optional_fields:
            out.append(f"  فیلدهای اختیاری مفقود: {', '.join(self.missing_optional_fields)}")
        if self.anomalies:
            out.append(f"  ناهنجاری‌ها: {'; '.join(self.anomalies)}")
        return "\n".join(out)


class DataValidator:
    """
    اعتبارسنج نمونه تابلو.

    فیلدهای حیاتی: last_price, close_price, buy_rows[0], sell_rows[0]
    فیلدهای اختیاری (با کاهش دقت موتورها): clienttype (real/legal)
    """

    CRITICAL_FIELDS = [
        "last_price",
        "close_price",
        "best_buy_price",
        "best_buy_volume",
        "best_sell_price",
        "best_sell_volume",
        "trade_volume",
        "trade_value",
    ]

    OPTIONAL_FIELDS = [
        "real_buy_count", "real_sell_count",
        "real_buy_volume", "real_sell_volume",
        "buy_rows (5 ردیف)", "sell_rows (5 ردیف)",
    ]

    def validate(self, snap: MarketSnapshot) -> DataQualityReport:
        report = DataQualityReport(
            snapshot_timestamp=snap.tehran_time,
            is_valid=True,
            completeness_pct=0.0,
            missing_critical_fields=[],
            missing_optional_fields=[],
            anomalies=[],
            field_status={},
        )

        # ----- بررسی فیلدهای حیاتی -----
        for f in self.CRITICAL_FIELDS:
            v = getattr(snap, f, None)
            if v is None or (isinstance(v, (int, float)) and v <= 0):
                report.missing_critical_fields.append(f)
                report.field_status[f] = "missing"
            else:
                report.field_status[f] = "ok"

        # ----- بررسی فیلدهای اختیاری -----
        if snap.real_buy_count == 0 and snap.real_sell_count == 0:
            report.missing_optional_fields.extend(["real_buy_count", "real_sell_count"])
            report.field_status["clienttype"] = "missing"
        else:
            report.field_status["clienttype"] = "ok"

        if len(snap.buy_rows) < 5:
            report.missing_optional_fields.append("buy_rows (کمتر از ۵ ردیف)")
        if len(snap.sell_rows) < 5:
            report.missing_optional_fields.append("sell_rows (کمتر از ۵ ردیف)")

        # ----- بررسی ناهنجاری‌های منطقی -----
        if snap.last_price > 0 and snap.close_price > 0:
            spread = abs(snap.last_price - snap.close_price) / snap.close_price
            if spread > 0.05:
                report.anomalies.append(
                    f"فاصله غیرعادی آخرین و پایانی ({spread*100:.1f}%)"
                )

        if snap.best_buy_price >= snap.best_sell_price and snap.best_buy_price > 0:
            report.anomalies.append("بهترین خرید >= بهترین فروش (ناممکن منطقی)")

        if snap.daily_high > 0 and snap.daily_low > 0 and snap.daily_high < snap.daily_low:
            report.anomalies.append("سقف روز < کف روز")

        if snap.buyer_power > 100 or snap.buyer_power < 0.01:
            if snap.buyer_power > 0:  # صفر فقط در نبود داده
                report.anomalies.append(f"قدرت خریدار غیرعادی: {snap.buyer_power:.1f}")

        if snap.trade_volume > 0 and snap.real_buy_volume + snap.real_sell_volume > snap.trade_volume * 1.5:
            report.anomalies.append("حجم حقیقی بیش از ۱.۵ برابر کل معاملات")

        # ----- محاسبه کمال -----
        total_fields = len(self.CRITICAL_FIELDS) + len(self.OPTIONAL_FIELDS)
        missing_count = (
            len(report.missing_critical_fields) +
            len(report.missing_optional_fields)
        )
        report.completeness_pct = 100 * (1 - missing_count / total_fields)

        # ----- تصمیم نهایی اعتبار -----
        if report.missing_critical_fields:
            report.is_valid = False
        elif report.anomalies and len(report.anomalies) >= 3:
            report.is_valid = False

        return report

    def validate_series(self, snapshots: list) -> List[DataQualityReport]:
        """اعتبارسنجی زنجیره‌ای از نمونه‌ها."""
        return [self.validate(s) for s in snapshots]


def mark_invalid_snapshot(snap: MarketSnapshot, report: DataQualityReport):
    """علامت‌گذاری نمونه به‌عنوان ناقص بر اساس گزارش."""
    snap.data_complete = report.is_valid
    snap.missing_fields = report.missing_critical_fields + report.missing_optional_fields
