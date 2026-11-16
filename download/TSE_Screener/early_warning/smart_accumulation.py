"""
smart_accumulation.py
موتور خرید — نسخه ۲.۰ (فرمول‌های features.py + نرمال‌سازی آستانه ثابت).

شش شاخص مستقل (مجموع امتیاز = ۱۰۰):
  1. buy_breadth    — گستردگی مشارکت خریداران حقیقی   (15)  (Nb−Ns)/(Nb+Ns)
  2. buy_flow       — ورود پول حقیقی                   (20)  (Vb−Vs)/(Vb+Vs)
  3. buy_ticket     — برتری اندازه معاملات خرید         (15)  ln(V̄b/V̄s)
  4. buy_price      — واکنش مثبت قیمت (۳۰ث)            (15)  ln(Pt/Pt−30s)
  5. buy_absorption — جذب عرضه قابل مشاهده              (20)  min(−Δask5, Δvol)/ask5_prev
  6. buy_support    — حفظ حمایت و فاصله از کف قیمت      (15)  recovery × proximity

نکته مهم: اگر خریداران حجم زیادی از عرضه را جذب کنند ولی قیمت هنوز رشد نکند،
این وضعیت می‌تواند نشانه جمع‌آوری سهم باشد. بنابراین رشد قیمت را شرط ضروری
تشخیص جمع‌آوری قرار نمی‌دهیم.

شاخص‌های ۱-۳ آینه‌ای موتور فروش هستند (buy_breadth = −sell_breadth) تا از
دوباره‌نویسی جلوگیری شود.

Phase 1: نرمال‌سازی با آستانه ثابت (full_at).
Phase 2: نرمال‌سازی تطبیقی صدکی (adaptive_scoring.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Dict, Optional
from .data_collector import MarketSnapshot


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _safe_div(a: float, b: float) -> float:
    if b == 0 or (isinstance(b, float) and math.isnan(b)):
        return float("nan")
    return a / b


def _ask5(snap: MarketSnapshot) -> float:
    rows = snap.sell_rows or []
    return float(sum(r.volume for r in rows[:5]))


def _bid5(snap: MarketSnapshot) -> float:
    rows = snap.buy_rows or []
    return float(sum(r.volume for r in rows[:5]))


@dataclass
class BuyPressureFactorResult:
    name: str
    label: str
    max_points: float
    raw_value: float
    raw_unit: str
    normalized: float
    score: float
    description: str
    status: str = "ok"

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
class BuyPressureResult:
    total_score: float
    level: str
    factors: List[BuyPressureFactorResult]
    independent_signals_count: int
    is_strong: bool
    snapshot_time: str
    valid_indicators: int = 6
    engine_status: str = "official"
    absorption_evidence: bool = False
    data_quality_warning: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            "total_score": round(self.total_score, 2),
            "level": self.level,
            "factors": [f.to_dict() for f in self.factors],
            "independent_signals_count": self.independent_signals_count,
            "is_strong": self.is_strong,
            "snapshot_time": self.snapshot_time,
            "valid_indicators": self.valid_indicators,
            "engine_status": self.engine_status,
            "absorption_evidence": self.absorption_evidence,
            "data_quality_warning": self.data_quality_warning,
        }


class BuyPressureDetector:
    """موتور امتیازدهی فشار خرید — نسخه ۲.۰."""

    LABELS = {
        "buy_breadth":    "گستردگی مشارکت خریداران حقیقی",
        "buy_flow":       "ورود پول حقیقی",
        "buy_ticket":     "برتری اندازه معاملات خرید",
        "buy_price":      "واکنش مثبت قیمت (۳۰ثانیه)",
        "buy_absorption": "جذب عرضه قابل مشاهده",
        "buy_support":    "حفظ حمایت و فاصله از کف قیمت",
    }

    def __init__(self, config: Dict):
        bp_cfg = config["buy_pressure"]
        self.weights = bp_cfg["weights"]
        self.levels = bp_cfg["levels"]
        self.norm = bp_cfg["norm"]
        self.identification_threshold = bp_cfg["identification_threshold"]
        self.min_history = config.get("min_history", 30)

    # -------------------------------------------------------------------
    # شاخص ۱: گستردگی مشارکت خریداران حقیقی (۱۵ امتیاز)
    #   (Nb−Ns)/(Nb+Ns)  —  آینه‌ای sell_breadth
    # -------------------------------------------------------------------
    def _factor_buy_breadth(self, snap: MarketSnapshot,
                            prev_snap: Optional[MarketSnapshot]) -> BuyPressureFactorResult:
        if prev_snap is None:
            return self._no_prev("buy_breadth", "تعداد معاملات حقیقی")
        nb = snap.real_buy_count - prev_snap.real_buy_count
        ns = snap.real_sell_count - prev_snap.real_sell_count
        denom = nb + ns
        if denom == 0:
            return self._no_trades(
                "buy_breadth", "معامله حقیقی",
                cum_info=f"تجمعی: خریدار={snap.real_buy_count}، فروشنده={snap.real_sell_count}")
        raw = _safe_div(nb - ns, denom)
        full_at = self.norm["buy_breadth"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["buy_breadth"]
        desc = f"Δ خریداران={nb}، Δ فروشندگان={ns} → گستردگی={raw:+.3f} (افزایش خریدار = مثبت)"
        return BuyPressureFactorResult(
            name="buy_breadth", label=self.LABELS["buy_breadth"],
            max_points=self.weights["buy_breadth"], raw_value=raw,
            raw_unit="نسبت [-1,1]", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۲: ورود پول حقیقی (۲۰ امتیاز)
    #   (Vb−Vs)/(Vb+Vs)  —  آینه‌ای sell_flow
    # -------------------------------------------------------------------
    def _factor_buy_flow(self, snap: MarketSnapshot,
                         prev_snap: Optional[MarketSnapshot]) -> BuyPressureFactorResult:
        if prev_snap is None:
            return self._no_prev("buy_flow", "ارزش معاملات حقیقی")
        vb = snap.real_buy_value - prev_snap.real_buy_value
        vs = snap.real_sell_value - prev_snap.real_sell_value
        denom = vb + vs
        if denom == 0:
            return self._no_trades(
                "buy_flow", "معامله حقیقی",
                cum_info=f"تجمعی: حجم خرید={snap.real_buy_volume:,}، فروش={snap.real_sell_volume:,}")
        raw = _safe_div(vb - vs, denom)
        full_at = self.norm["buy_flow"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["buy_flow"]
        desc = f"Δ ارزش خرید={vb:,.0f}، Δ ارزش فروش={vs:,.0f} → ورود={raw:+.3f}"
        return BuyPressureFactorResult(
            name="buy_flow", label=self.LABELS["buy_flow"],
            max_points=self.weights["buy_flow"], raw_value=raw,
            raw_unit="نسبت [-1,1]", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۳: برتری اندازه معاملات خرید (۱۵ امتیاز)
    #   ln(V̄b/V̄s)  —  آینه‌ای sell_ticket
    # -------------------------------------------------------------------
    def _factor_buy_ticket(self, snap: MarketSnapshot,
                           prev_snap: Optional[MarketSnapshot]) -> BuyPressureFactorResult:
        if prev_snap is None:
            return self._no_prev("buy_ticket", "سرانه معاملات حقیقی")
        nb = snap.real_buy_count - prev_snap.real_buy_count
        ns = snap.real_sell_count - prev_snap.real_sell_count
        vb = snap.real_buy_value - prev_snap.real_buy_value
        vs = snap.real_sell_value - prev_snap.real_sell_value
        if nb == 0 and ns == 0:
            return self._no_trades(
                "buy_ticket", "معامله حقیقی",
                cum_info=f"تجمعی: خریدار={snap.real_buy_count}، فروشنده={snap.real_sell_count}")
        avg_b = _safe_div(vb, nb)
        avg_s = _safe_div(vs, ns)
        ratio = _safe_div(avg_b, avg_s)
        raw = math.log(ratio) if (not math.isnan(ratio) and ratio > 0) else float("nan")
        full_at = self.norm["buy_ticket"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["buy_ticket"]
        desc = f"سرانه خرید={avg_b:,.0f}، سرانه فروش={avg_s:,.0f} → ln={raw:+.3f}"
        return BuyPressureFactorResult(
            name="buy_ticket", label=self.LABELS["buy_ticket"],
            max_points=self.weights["buy_ticket"], raw_value=raw,
            raw_unit="ln(نسبت)", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۴: واکنش مثبت قیمت — ۳۰ ثانیه (۱۵ امتیاز)
    #   ln(Pt/Pt−30s)  —  رشد قیمت = مثبت
    # -------------------------------------------------------------------
    def _factor_buy_price(self, snap: MarketSnapshot,
                          prev_snap: Optional[MarketSnapshot]) -> BuyPressureFactorResult:
        if prev_snap is None or prev_snap.last_price <= 0:
            return self._no_prev("buy_price", "قیمت ۳۰ث قبل")
        ratio = snap.last_price / prev_snap.last_price
        raw = math.log(ratio) if ratio > 0 else float("nan")
        full_at = self.norm["buy_price"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["buy_price"]
        desc = f"Pt={snap.last_price:,.0f}، Pt-30s={prev_snap.last_price:,.0f} → تغییر={raw:+.4f}"
        return BuyPressureFactorResult(
            name="buy_price", label=self.LABELS["buy_price"],
            max_points=self.weights["buy_price"], raw_value=raw,
            raw_unit="ln(نسبت)", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۵: جذب عرضه قابل مشاهده (۲۰ امتیاز)
    #   min(−Δask5, Δvol_traded) / ask5_prev
    #   فقط مقدار کاهش عرضه را می‌شمارد که با حجم معامله واقعی تأیید شده.
    #   این شاخص «نشانه تقریبی جذب» است، نه تأیید قطعی (لغو سفارش جدا نمی‌شود).
    # -------------------------------------------------------------------
    def _factor_buy_absorption(self, snap: MarketSnapshot,
                               prev_snap: Optional[MarketSnapshot]) -> BuyPressureFactorResult:
        if prev_snap is None:
            return self._no_prev("buy_absorption", "عمق بازار ۳۰ث قبل")
        ask_prev = _ask5(prev_snap)
        ask_now = _ask5(snap)
        ask_depletion = max(0.0, ask_prev - ask_now)   # کاهش عرضه = مثبت
        traded = max(0.0, snap.total_volume - prev_snap.total_volume)  # حجم معامله شده
        confirmed = min(ask_depletion, traded)   # فقط بخش تأییدشده با معامله واقعی
        raw = _safe_div(confirmed, ask_prev) if ask_prev > 0 else float("nan")
        full_at = self.norm["buy_absorption"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["buy_absorption"]
        desc = (f"کاهش عرضه={ask_depletion:,.0f}، حجم معامله={traded:,.0f}، "
                f"تأییدشده={confirmed:,.0f} → جذب={raw:.3f}")
        return BuyPressureFactorResult(
            name="buy_absorption", label=self.LABELS["buy_absorption"],
            max_points=self.weights["buy_absorption"], raw_value=raw,
            raw_unit="نسبت", normalized=norm, score=score,
            description=desc)

    # -------------------------------------------------------------------
    # شاخص ۶: حفظ حمایت و فاصله از کف قیمت (۱۵ امتیاز)
    #   recovery × proximity  —  بازگشت از کف در پنجره ۳۶ نمونه (۱۸ دقیقه)
    #   recovery = (P − low) / low  ;  proximity = 1 − (low − L)/(U − L)
    # -------------------------------------------------------------------
    def _factor_buy_support(self, snap: MarketSnapshot,
                            history: List[MarketSnapshot]) -> BuyPressureFactorResult:
        L = snap.min_allowed_price
        U = snap.max_allowed_price
        day_range = U - L
        # پنجره ۳۶ نمونه اخیر + نمونه فعلی
        window = history[-35:] + [snap] if len(history) >= 1 else [snap]
        prices = [h.last_price for h in window if h.last_price > 0]
        if not prices or day_range <= 0:
            raw = float("nan")
            status = "insufficient_history" if len(history) < 6 else "missing"
        else:
            low = min(prices)
            recovery = _safe_div(snap.last_price - low, low)
            proximity = 1.0 - _safe_div(low - L, day_range)
            if math.isnan(recovery) or math.isnan(proximity):
                raw = float("nan")
                status = "missing"
            else:
                raw = max(0.0, recovery) * max(0.0, proximity)
                status = "ok" if len(history) >= 6 else "warming_up"
        full_at = self.norm["buy_support"]["full_at"]
        norm = _clamp(_safe_div(raw, full_at)) if not math.isnan(raw) else 0.0
        score = norm * self.weights["buy_support"]
        if math.isnan(raw):
            raw_disp = 0.0
        else:
            raw_disp = raw
        desc = (f"کف روزانه={L:,.0f}، حداقل پنجره={min(prices) if prices else 0:,.0f}، "
                f"آخرین={snap.last_price:,.0f} → حمایت={raw_disp:.3f}")
        return BuyPressureFactorResult(
            name="buy_support", label=self.LABELS["buy_support"],
            max_points=self.weights["buy_support"], raw_value=raw if not math.isnan(raw) else 0.0,
            raw_unit="شاخص ترکیبی", normalized=norm, score=score,
            description=desc, status=status)

    # -------------------------------------------------------------------
    def _no_prev(self, name: str, field: str) -> BuyPressureFactorResult:
        return BuyPressureFactorResult(
            name=name, label=self.LABELS.get(name, name),
            max_points=self.weights.get(name, 0), raw_value=float("nan"),
            raw_unit="—", normalized=0.0, score=0.0,
            description=f"{field} در دسترس نیست (نمونه قبلی وجود ندارد).",
            status="no_prev")

    # -------------------------------------------------------------------
    # کمکی: شاخص‌هایی که در بازه ۳۰ثانیه‌ای معامله جدیدی نداشتند
    #   داده تجمعی موجود است ولی delta = 0 → خنثی (نه مفقود)
    # -------------------------------------------------------------------
    def _no_trades(self, name: str, field: str,
                   cum_info: str = "") -> BuyPressureFactorResult:
        extra = f" ({cum_info})" if cum_info else ""
        return BuyPressureFactorResult(
            name=name, label=self.LABELS.get(name, name),
            max_points=self.weights.get(name, 0), raw_value=0.0,
            raw_unit="—", normalized=0.0, score=0.0,
            description=f"بدون {field} جدید در بازه ۳۰ثانیه‌ای{extra} — خنثی.",
            status="no_trades")

    # -------------------------------------------------------------------
    # محاسبه نهایی
    # -------------------------------------------------------------------
    def evaluate(self, snap: MarketSnapshot,
                 prev_snap: Optional[MarketSnapshot] = None,
                 history: Optional[List[MarketSnapshot]] = None) -> BuyPressureResult:
        if history is None:
            history = []

        data_warning = None
        if not snap.data_complete:
            data_warning = f"داده‌های ناقص: {', '.join(snap.missing_fields)}"

        factors = [
            self._factor_buy_breadth(snap, prev_snap),
            self._factor_buy_flow(snap, prev_snap),
            self._factor_buy_ticket(snap, prev_snap),
            self._factor_buy_price(snap, prev_snap),
            self._factor_buy_absorption(snap, prev_snap),
            self._factor_buy_support(snap, history),
        ]

        valid = sum(1 for f in factors if f.status == "ok")
        total = sum(f.score for f in factors)
        independent_signals = sum(1 for f in factors if f.normalized >= 0.5)
        level = self._determine_level(total)
        is_strong = total >= self.identification_threshold
        # شواهد جذب: buy_absorption و buy_support هر دو >= ۵۰٪
        absorption_evidence = factors[4].normalized >= 0.5 and factors[5].normalized >= 0.5
        engine_status = "official" if valid == len(factors) else "warming_up"

        return BuyPressureResult(
            total_score=total, level=level, factors=factors,
            independent_signals_count=independent_signals,
            is_strong=is_strong, snapshot_time=snap.tehran_time,
            valid_indicators=valid, engine_status=engine_status,
            absorption_evidence=absorption_evidence,
            data_quality_warning=data_warning)

    def _determine_level(self, score: float) -> str:
        if score <= 24:
            return self.levels["0-24"]["label"]
        elif score <= 34:
            return self.levels["25-34"]["label"]
        elif score <= 49:
            return self.levels["35-49"]["label"]
        elif score <= 64:
            return self.levels["50-64"]["label"]
        elif score <= 79:
            return self.levels["65-79"]["label"]
        else:
            return self.levels["80-100"]["label"]


# سازگاری با نسخه قبلی — نام قدقیق
SmartAccumulationDetector = BuyPressureDetector
AccumulationFactorResult = BuyPressureFactorResult
AccumulationResult = BuyPressureResult
