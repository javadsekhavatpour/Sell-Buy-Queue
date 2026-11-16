"""
sell_pressure.py
موتور فشار فروش — نسخه ۲.۰ (فرمول‌های features.py + نرمال‌سازی آستانه ثابت).

شش شاخص مستقل (مجموع امتیاز = ۱۰۰):
  1. sell_breadth  — ضعف گستردگی خریداران حقیقی    (15)  (Ns−Nb)/(Ns+Nb)
  2. sell_flow     — خروج پول حقیقی                 (20)  (Vs−Vb)/(Vs+Vb)
  3. sell_ticket   — برتری اندازه معاملات فروش       (15)  ln(V̄s/V̄b)
  4. sell_price    — واکنش منفی قیمت (۳۰ث)          (15)  −ln(Pt/Pt−30s)
  5. sell_supply   — افزایش عرضه قابل مشاهده         (20)  Δask5% − Δbid5%
  6. sell_lower    — نزدیکی به کف قیمت               (15)  1−(P−L)/(U−L)

نکته فنی: داده‌های حقیقی از TSETMC تجمعی روزانه‌اند؛ لذا اختلاف نمونه‌های متوالی
(prev_snap → snap) به‌عنوان دلتای بازه ۳۰ثانیه‌ای استفاده می‌شود تا از
دوباره‌شماری جلوگیری شود.

Phase 1: نرمال‌سازی با آستانه ثابت (full_at).
Phase 2: نرمال‌سازی تطبیقی صدکی (adaptive_scoring.py جایگزین می‌شود).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Dict, Optional
from .data_collector import MarketSnapshot


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """محدود کردن مقدار بین [lo, hi]."""
    return max(lo, min(hi, v))


def _safe_div(a: float, b: float) -> float:
    """تقسیم امن — اگر مخرج صفر باشد NaN برمی‌گرداند."""
    if b == 0 or (isinstance(b, float) and math.isnan(b)):
        return float("nan")
    return a / b


def _ask5(snap: MarketSnapshot) -> float:
    """مجموع حجم ۵ ردیف عرضه (فروش)."""
    rows = snap.sell_rows or []
    return float(sum(r.volume for r in rows[:5]))


def _bid5(snap: MarketSnapshot) -> float:
    """مجموع حجم ۵ ردیف تقاضا (خرید)."""
    rows = snap.buy_rows or []
    return float(sum(r.volume for r in rows[:5]))


@dataclass
class SellPressureFactorResult:
    """نتیجه یک شاخص."""
    name: str
    label: str
    max_points: float
    raw_value: float
    raw_unit: str
    normalized: float
    score: float
    description: str
    status: str = "ok"   # ok | missing | insufficient_history | no_prev

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "label": self.label,
            "max_points": self.max_points,
            "raw_value": None if (isinstance(self.raw_value, float) and math.isnan(self.raw_value)) else round(self.raw_value, 4),
            "raw_unit": self.raw_unit,
            "normalized": round(self.normalized, 4),
            "score": round(self.score, 2),
            "description": self.description,
            "status": self.status,
        }


@dataclass
class SellPressureResult:
    """خروجی کامل موتور فشار فروش."""
    total_score: float
    level: str
    action: str
    factors: List[SellPressureFactorResult]
    independent_signals_count: int
    is_critical: bool
    snapshot_time: str
    valid_indicators: int = 6
    engine_status: str = "official"   # official | warming_up
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
            "valid_indicators": self.valid_indicators,
            "engine_status": self.engine_status,
            "data_quality_warning": self.data_quality_warning,
        }


class SellPressureDetector:
    """موتور امتیازدهی فشار فروش — نسخه ۲.۰."""

    LABELS = {
        "sell_breadth": "ضعف گستردگی خریداران حقیقی",
        "sell_flow":    "خروج پول حقیقی",
        "sell_ticket":  "برتری اندازه معاملات فروش",
        "sell_price":   "واکنش منفی قیمت (۳۰ثانیه)",
        "sell_supply":  "افزایش عرضه قابل مشاهده",
        "sell_lower":   "نزدیکی به کف قیمت",
    }

    def __init__(self, config: Dict):
        sp_cfg = config["sell_pressure"]
        self.weights = sp_cfg["weights"]
        self.levels = sp_cfg["levels"]
        self.norm = sp_cfg["norm"]
        self.min_history = config.get("min_history", 30)

    # -------------------------------------------------------------------
    # شاخص ۱: ضعف گستردگی خریداران حقیقی (۱۵ امتیاز)
    #   (Ns−Nb)/(Ns+Nb)  —  N = تعداد معاملات حقیقی در بازه ۳۰ث
    # -------------------------------------------------------------------
    def _factor_sell_breadth(self, snap: MarketSnapshot,
                             prev_snap: Optional[MarketSnapshot]) -> SellPressureFactorResult:
        if prev_snap is None:
            return self._no_prev("sell_breadth", "تعداد معاملات حقیقی")
        nb = snap.real_buy_count - prev_snap.real_buy_count
        ns = snap.real_sell_count - prev_snap.real_sell_count
        denom = nb + ns
        raw = _safe_div(ns - nb, denom)
        full_at = self.norm["sell_breadth"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["sell_breadth"]
        desc = f"Δ خریداران={nb}، Δ فروشندگان={ns} → گستردگی={raw:+.3f} (کاهش خریدار = مثبت)"
        return SellPressureFactorResult(
            name="sell_breadth", label=self.LABELS["sell_breadth"],
            max_points=self.weights["sell_breadth"], raw_value=raw,
            raw_unit="نسبت [-1,1]", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۲: خروج پول حقیقی (۲۰ امتیاز)
    #   (Vs−Vb)/(Vs+Vb)  —  V = ارزش معاملات حقیقی در بازه ۳۰ث
    # -------------------------------------------------------------------
    def _factor_sell_flow(self, snap: MarketSnapshot,
                          prev_snap: Optional[MarketSnapshot]) -> SellPressureFactorResult:
        if prev_snap is None:
            return self._no_prev("sell_flow", "ارزش معاملات حقیقی")
        vb = snap.real_buy_value - prev_snap.real_buy_value
        vs = snap.real_sell_value - prev_snap.real_sell_value
        denom = vb + vs
        raw = _safe_div(vs - vb, denom)
        full_at = self.norm["sell_flow"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["sell_flow"]
        desc = f"Δ ارزش خرید={vb:,.0f}، Δ ارزش فروش={vs:,.0f} → خروج={raw:+.3f}"
        return SellPressureFactorResult(
            name="sell_flow", label=self.LABELS["sell_flow"],
            max_points=self.weights["sell_flow"], raw_value=raw,
            raw_unit="نسبت [-1,1]", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۳: برتری اندازه معاملات فروش (۱۵ امتیاز)
    #   ln(V̄s/V̄b)  —  V̄ = ارزش به‌ازای هر معامله‌گر حقیقی
    # -------------------------------------------------------------------
    def _factor_sell_ticket(self, snap: MarketSnapshot,
                            prev_snap: Optional[MarketSnapshot]) -> SellPressureFactorResult:
        if prev_snap is None:
            return self._no_prev("sell_ticket", "سرانه معاملات حقیقی")
        nb = snap.real_buy_count - prev_snap.real_buy_count
        ns = snap.real_sell_count - prev_snap.real_sell_count
        vb = snap.real_buy_value - prev_snap.real_buy_value
        vs = snap.real_sell_value - prev_snap.real_sell_value
        avg_b = _safe_div(vb, nb)
        avg_s = _safe_div(vs, ns)
        ratio = _safe_div(avg_s, avg_b)
        raw = math.log(ratio) if (not math.isnan(ratio) and ratio > 0) else float("nan")
        full_at = self.norm["sell_ticket"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["sell_ticket"]
        desc = f"سرانه خرید={avg_b:,.0f}، سرانه فروش={avg_s:,.0f} → ln={raw:+.3f}"
        return SellPressureFactorResult(
            name="sell_ticket", label=self.LABELS["sell_ticket"],
            max_points=self.weights["sell_ticket"], raw_value=raw,
            raw_unit="ln(نسبت)", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۴: واکنش منفی قیمت — ۳۰ ثانیه (۱۵ امتیاز)
    #   −ln(Pt/Pt−30s)  —  افت قیمت = مثبت
    # -------------------------------------------------------------------
    def _factor_sell_price(self, snap: MarketSnapshot,
                           prev_snap: Optional[MarketSnapshot]) -> SellPressureFactorResult:
        if prev_snap is None or prev_snap.last_price <= 0:
            return self._no_prev("sell_price", "قیمت ۳۰ث قبل")
        ratio = snap.last_price / prev_snap.last_price
        raw = -math.log(ratio) if ratio > 0 else float("nan")
        full_at = self.norm["sell_price"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["sell_price"]
        desc = f"Pt={snap.last_price:,.0f}، Pt-30s={prev_snap.last_price:,.0f} → تغییر={raw:+.4f}"
        return SellPressureFactorResult(
            name="sell_price", label=self.LABELS["sell_price"],
            max_points=self.weights["sell_price"], raw_value=raw,
            raw_unit="−ln(نسبت)", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۵: افزایش عرضه قابل مشاهده (۲۰ امتیاز)
    #   Δask5% − Δbid5%  —  رشد خالص عرضه نسبت به تقاضا
    # -------------------------------------------------------------------
    def _factor_sell_supply(self, snap: MarketSnapshot,
                            prev_snap: Optional[MarketSnapshot]) -> SellPressureFactorResult:
        if prev_snap is None:
            return self._no_prev("sell_supply", "عمق بازار ۳۰ث قبل")
        ask_prev = _ask5(prev_snap)
        bid_prev = _bid5(prev_snap)
        ask_now = _ask5(snap)
        bid_now = _bid5(snap)
        d_ask = _safe_div(ask_now - ask_prev, ask_prev) if ask_prev > 0 else float("nan")
        d_bid = _safe_div(bid_now - bid_prev, bid_prev) if bid_prev > 0 else float("nan")
        raw = (d_ask - d_bid) if not (math.isnan(d_ask) or math.isnan(d_bid)) else float("nan")
        full_at = self.norm["sell_supply"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["sell_supply"]
        desc = f"Δask5={d_ask*100:+.1f}٪، Δbid5={d_bid*100:+.1f}٪ → خالص={raw:+.3f}"
        return SellPressureFactorResult(
            name="sell_supply", label=self.LABELS["sell_supply"],
            max_points=self.weights["sell_supply"], raw_value=raw,
            raw_unit="تفاضل درصد", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۶: نزدیکی به کف قیمت (۱۵ امتیاز)
    #   1−(P−L)/(U−L)  —  L=کف، U=سقف روزانه
    # -------------------------------------------------------------------
    def _factor_sell_lower(self, snap: MarketSnapshot) -> SellPressureFactorResult:
        L = snap.min_allowed_price
        U = snap.max_allowed_price
        if U <= L or U <= 0:
            raw = float("nan")
        else:
            raw = 1.0 - (snap.last_price - L) / (U - L)
        full_at = self.norm["sell_lower"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["sell_lower"]
        status = "ok"
        if math.isnan(raw):
            status = "missing"
            raw = 0.0
        desc = f"کف={L:,.0f}، سقف={U:,.0f}، آخرین={snap.last_price:,.0f} → موقعیت={raw:.3f} (۱=کف)"
        return SellPressureFactorResult(
            name="sell_lower", label=self.LABELS["sell_lower"],
            max_points=self.weights["sell_lower"], raw_value=raw,
            raw_unit="موقعیت [0,1]", normalized=norm, score=score,
            description=desc, status=status)

    # -------------------------------------------------------------------
    # کمکی: شاخص‌هایی که به نمونه قبلی نیاز دارند
    # -------------------------------------------------------------------
    def _no_prev(self, name: str, field: str) -> SellPressureFactorResult:
        return SellPressureFactorResult(
            name=name, label=self.LABELS.get(name, name),
            max_points=self.weights.get(name, 0), raw_value=float("nan"),
            raw_unit="—", normalized=0.0, score=0.0,
            description=f"{field} در دسترس نیست (نمونه قبلی وجود ندارد).",
            status="no_prev")

    # -------------------------------------------------------------------
    # محاسبه نهایی
    # -------------------------------------------------------------------
    def evaluate(self, snap: MarketSnapshot,
                 prev_snap: Optional[MarketSnapshot] = None) -> SellPressureResult:
        """محاسبه امتیاز فشار فروش برای یک نمونه."""
        data_warning = None
        if not snap.data_complete:
            data_warning = f"داده‌های ناقص: {', '.join(snap.missing_fields)}"

        factors = [
            self._factor_sell_breadth(snap, prev_snap),
            self._factor_sell_flow(snap, prev_snap),
            self._factor_sell_ticket(snap, prev_snap),
            self._factor_sell_price(snap, prev_snap),
            self._factor_sell_supply(snap, prev_snap),
            self._factor_sell_lower(snap),
        ]

        valid = sum(1 for f in factors if f.status == "ok")
        total = sum(f.score for f in factors)
        independent_signals = sum(1 for f in factors if f.normalized >= 0.5)

        level, action = self._determine_level(total)
        is_critical = total >= 65
        engine_status = "official" if valid == len(factors) else "warming_up"

        return SellPressureResult(
            total_score=total, level=level, action=action,
            factors=factors, independent_signals_count=independent_signals,
            is_critical=is_critical, snapshot_time=snap.tehran_time,
            valid_indicators=valid, engine_status=engine_status,
            data_quality_warning=data_warning)

    def _determine_level(self, score: float) -> tuple:
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
