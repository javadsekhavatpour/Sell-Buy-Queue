"""
sell_pressure.py
موتور فشار فروش و خرید — نسخه ۴.۰ (تأیید قیمت)
==================================================
تغییرات اصلی نسبت به ۳.۱:
  ✓ ضریب تأیید قیمت (price confirmation):
      سیگنال فروش با افت قیمت ← ×1.5
      سیگنال فروش با رشد قیمت ← ×0.2 (رد سیگنال)
      همین به‌صورت آینه‌ای برای خرید
  ✓ رد شکاف زمانی: اگر gap > 90s، prev_snap = None
  ✓ فیلتر داده خراب: |Δprice| > 20% یا last=0 ← invalid_data
  ✓ فیلدهای جدید: price_confirmation, raw_sell_score, raw_buy_score
  ✓ is_critical فقط اگر sell_score ≥ 65 و تأیید قیمت ≥ 1.0
  ✓ سازگاری کامل با adaptive_scoring.py
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional
from .data_collector import MarketSnapshot


# ============================================================
# ابزارهای کمکی
# ============================================================

def _clamp(v, lo=0.0, hi=1.0):
    if v is None:
        return lo
    if isinstance(v, float) and math.isnan(v):
        return lo
    return max(lo, min(hi, v))


def _clamp_signed(v, lim=1.0):
    if v is None:
        return 0.0
    if isinstance(v, float) and math.isnan(v):
        return 0.0
    return max(-lim, min(lim, v))


def _safe_div(a, b):
    if b == 0 or (isinstance(b, float) and math.isnan(b)):
        return float("nan")
    return a / b


def _ask5(snap):
    rows = snap.sell_rows or []
    return float(sum(r.volume for r in rows[:5]))


def _bid5(snap):
    rows = snap.buy_rows or []
    return float(sum(r.volume for r in rows[:5]))


def _round_or_none(v, ndigits=4):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    try:
        return round(v, ndigits)
    except (TypeError, ValueError):
        return None


def _parse_time(t):
    try:
        return datetime.strptime(str(t), "%H:%M:%S")
    except Exception:
        return None


# ============================================================
# نتایج
# ============================================================

@dataclass
class SellPressureFactorResult:
    name: str
    label: str
    max_points: float
    raw_value: float
    raw_unit: str
    normalized: float
    score: float
    description: str
    status: str = "ok"
    normalized_signed: float = 0.0
    sell_score: float = 0.0
    buy_score: float = 0.0
    side: str = "neutral"
    # جدید
    raw_sell_score: float = 0.0
    raw_buy_score: float = 0.0

    def to_dict(self):
        return {
            "name": self.name, "label": self.label,
            "max_points": self.max_points,
            "raw_value": _round_or_none(self.raw_value, 4),
            "raw_unit": self.raw_unit,
            "normalized": _round_or_none(self.normalized, 4) or 0.0,
            "score": _round_or_none(self.score, 2) or 0.0,
            "description": self.description, "status": self.status,
            "normalized_signed": _round_or_none(self.normalized_signed, 4) or 0.0,
            "sell_score": _round_or_none(self.sell_score, 2) or 0.0,
            "buy_score": _round_or_none(self.buy_score, 2) or 0.0,
            "side": self.side,
            "raw_sell_score": _round_or_none(self.raw_sell_score, 2) or 0.0,
            "raw_buy_score": _round_or_none(self.raw_buy_score, 2) or 0.0,
        }


@dataclass
class SellPressureResult:
    total_score: float
    level: str
    action: str
    factors: List[SellPressureFactorResult]
    independent_signals_count: int
    is_critical: bool
    snapshot_time: str
    valid_indicators: int = 6
    engine_status: str = "official"
    data_quality_warning: Optional[str] = None
    sell_score: float = 0.0
    buy_score: float = 0.0
    net_score: float = 0.0
    dominant: str = "neutral"
    strength: float = 0.0
    is_critical_buy: bool = False
    # جدید
    price_confirmation_sell: float = 1.0
    price_confirmation_buy: float = 1.0
    raw_sell_score: float = 0.0
    raw_buy_score: float = 0.0

    def to_dict(self):
        return {
            "total_score": _round_or_none(self.total_score, 2) or 0.0,
            "level": self.level, "action": self.action,
            "factors": [f.to_dict() for f in self.factors],
            "independent_signals_count": self.independent_signals_count,
            "is_critical": self.is_critical,
            "snapshot_time": self.snapshot_time,
            "valid_indicators": self.valid_indicators,
            "engine_status": self.engine_status,
            "data_quality_warning": self.data_quality_warning,
            "sell_score": _round_or_none(self.sell_score, 2) or 0.0,
            "buy_score": _round_or_none(self.buy_score, 2) or 0.0,
            "net_score": _round_or_none(self.net_score, 2) or 0.0,
            "dominant": self.dominant,
            "strength": _round_or_none(self.strength, 2) or 0.0,
            "is_critical_buy": self.is_critical_buy,
            "price_confirmation_sell": _round_or_none(self.price_confirmation_sell, 2) or 1.0,
            "price_confirmation_buy": _round_or_none(self.price_confirmation_buy, 2) or 1.0,
            "raw_sell_score": _round_or_none(self.raw_sell_score, 2) or 0.0,
            "raw_buy_score": _round_or_none(self.raw_buy_score, 2) or 0.0,
        }


# ============================================================
# موتور
# ============================================================

class SellPressureDetector:
    """موتور امتیازدهی دوجهته با تأیید قیمت — نسخه ۴.۰."""

    LABELS = {
        "sell_breadth": "گستردگی معامله‌گران حقیقی",
        "sell_flow":    "خالص جریان پول حقیقی",
        "sell_ticket":  "سرانه ارزش معاملات حقیقی",
        "sell_price":   "واکنش قیمت (۳۰ثانیه)",
        "sell_supply":  "تغییر عرضه/تقاضا در دفتر سفارش",
        "sell_lower":   "موقعیت قیمت در دامنه روز",
    }

    REQUIRED_LEVELS = ["0-24", "25-34", "35-49", "50-64", "65-79", "80-100"]
    MAX_TIME_GAP = 90  # ثانیه
    MAX_PRICE_MOVE = 20.0  # درصد — بیشتر از این یعنی داده خراب

    def __init__(self, config: Dict, normalizer=None):
        sp_cfg = config["sell_pressure"]
        self.weights = sp_cfg["weights"]
        self.levels = sp_cfg["levels"]
        self.norm = sp_cfg["norm"]
        self.min_history = config.get("min_history", 30)
        self.normalizer = normalizer

        missing_w = [f for f in self.LABELS if f not in self.weights]
        if missing_w:
            raise ValueError(f"weights missing: {missing_w}")
        missing_n = [f for f in self.LABELS if f not in self.norm]
        if missing_n:
            raise ValueError(f"norm missing: {missing_n}")
        missing_lv = [k for k in self.REQUIRED_LEVELS if k not in self.levels]
        if missing_lv:
            raise ValueError(f"levels missing: {missing_lv}")

    # -------------------------------------------------------------------
    # اعتبارسنجی و تأیید قیمت
    # -------------------------------------------------------------------
    def _time_gap_seconds(self, snap, prev_snap):
        t1 = _parse_time(prev_snap.tehran_time)
        t2 = _parse_time(snap.tehran_time)
        if t1 is None or t2 is None:
            return 30.0
        diff = (t2 - t1).total_seconds()
        if diff < 0:
            diff += 24 * 3600
        return diff

    def _is_valid_prev(self, snap, prev_snap):
        if prev_snap is None:
            return False
        gap = self._time_gap_seconds(snap, prev_snap)
        return 10 <= gap <= self.MAX_TIME_GAP

    def _price_change_pct(self, snap, prev_snap):
        if prev_snap is None or prev_snap.last_price <= 0 or snap.last_price <= 0:
            return None
        pct = (snap.last_price - prev_snap.last_price) / prev_snap.last_price * 100
        if abs(pct) > self.MAX_PRICE_MOVE:
            return None
        return pct

    def _price_confirm(self, snap, prev_snap):
        """برمی‌گرداند (confirm_sell, confirm_buy, price_change_pct)."""
        pct = self._price_change_pct(snap, prev_snap)
        if pct is None:
            return 0.5, 0.5, None   # تأیید خنثی
        if pct < -0.1:      # قیمت افت
            return 1.5, 0.2, pct
        elif pct > 0.1:     # قیمت رشد
            return 0.2, 1.5, pct
        else:               # تخت
            return 0.8, 0.8, pct

    # -------------------------------------------------------------------
    # آستانه
    # -------------------------------------------------------------------
    def _get_threshold(self, symbol, factor_name):
        try:
            fallback = self.norm[factor_name]["full_at"]
        except (KeyError, TypeError):
            return float("nan")
        if self.normalizer is None:
            return fallback
        try:
            return self.normalizer.get_threshold(symbol, factor_name, fallback)
        except Exception:
            return fallback

    # -------------------------------------------------------------------
    # ضرایب کاهش
    # -------------------------------------------------------------------
    def _ceiling_damp(self, snap):
        L, U = snap.min_allowed_price, snap.max_allowed_price
        if U <= L or U <= 0 or snap.last_price <= 0:
            return 1.0
        pos = max(0.0, min(1.0, (snap.last_price - L) / (U - L)))
        return 1.0 if pos <= 0.7 else 1.0 - 0.7 * (pos - 0.7) / 0.3

    def _floor_damp(self, snap):
        L, U = snap.min_allowed_price, snap.max_allowed_price
        if U <= L or U <= 0 or snap.last_price <= 0:
            return 1.0
        pos = max(0.0, min(1.0, (snap.last_price - L) / (U - L)))
        return 1.0 if pos >= 0.3 else 1.0 - 0.7 * (0.3 - pos) / 0.3

    def _damp_for(self, norm_signed, snap):
        if norm_signed > 0:
            return self._ceiling_damp(snap)
        if norm_signed < 0:
            return self._floor_damp(snap)
        return 1.0

    # -------------------------------------------------------------------
    # هسته
    # -------------------------------------------------------------------
    def _score_signed(self, name, raw, raw_unit, norm_signed, damp, description):
        w = self.weights.get(name, 0)
        if norm_signed > 0:
            sell_score, buy_score, side = norm_signed * w * damp, 0.0, "sell"
        elif norm_signed < 0:
            sell_score, buy_score, side = 0.0, -norm_signed * w * damp, "buy"
        else:
            sell_score = buy_score = 0.0
            side = "neutral"
        return SellPressureFactorResult(
            name=name, label=self.LABELS.get(name, name),
            max_points=w, raw_value=raw, raw_unit=raw_unit,
            normalized=abs(norm_signed), normalized_signed=norm_signed,
            sell_score=sell_score, buy_score=buy_score,
            score=sell_score, description=description, status="ok", side=side,
            raw_sell_score=sell_score, raw_buy_score=buy_score)

    # -------------------------------------------------------------------
    # شاخص ۱: گستردگی
    # -------------------------------------------------------------------
    def _factor_sell_breadth(self, snap, prev_snap):
        if prev_snap is None:
            return self._no_prev("sell_breadth", "تعداد معاملات حقیقی")
        nb = snap.real_buy_count - prev_snap.real_buy_count
        ns = snap.real_sell_count - prev_snap.real_sell_count
        if nb < 0 or ns < 0:
            return self._counter_reset("sell_breadth", nb, ns)
        if nb == 0 and ns == 0:
            return self._no_trades("sell_breadth", "معامله حقیقی")
        raw = (ns - nb) / (nb + ns)
        full_at = self._get_threshold(snap.symbol, "sell_breadth")
        if not self._valid_full_at(full_at):
            return self._invalid_threshold("sell_breadth", full_at)
        norm_signed = _clamp_signed(raw / full_at)
        damp = self._damp_for(norm_signed, snap)
        side_txt = "فشار فروش" if norm_signed > 0 else ("فشار خرید" if norm_signed < 0 else "تعادل")
        desc = f"Δ خریداران={nb}، Δ فروشندگان={ns} → {side_txt} ({raw:+.3f})"
        return self._score_signed("sell_breadth", raw, "نسبت", norm_signed, damp, desc)

    # -------------------------------------------------------------------
    # شاخص ۲: جریان پول
    # -------------------------------------------------------------------
    def _factor_sell_flow(self, snap, prev_snap):
        if prev_snap is None:
            return self._no_prev("sell_flow", "ارزش معاملات حقیقی")
        vb = snap.real_buy_value - prev_snap.real_buy_value
        vs = snap.real_sell_value - prev_snap.real_sell_value
        if vb < 0 or vs < 0:
            return self._counter_reset("sell_flow", vb, vs)
        if vb == 0 and vs == 0:
            return self._no_trades("sell_flow", "معامله حقیقی")
        raw = (vs - vb) / (vb + vs)
        full_at = self._get_threshold(snap.symbol, "sell_flow")
        if not self._valid_full_at(full_at):
            return self._invalid_threshold("sell_flow", full_at)
        norm_signed = _clamp_signed(raw / full_at)
        damp = self._damp_for(norm_signed, snap)
        side_txt = "خروج پول" if norm_signed > 0 else ("ورود پول" if norm_signed < 0 else "تعادل")
        desc = f"Δ خرید={vb:,.0f}، Δ فروش={vs:,.0f} → {side_txt} ({raw:+.3f})"
        return self._score_signed("sell_flow", raw, "نسبت", norm_signed, damp, desc)

    # -------------------------------------------------------------------
    # شاخص ۳: سرانه تیکت
    # -------------------------------------------------------------------
    def _factor_sell_ticket(self, snap, prev_snap):
        if prev_snap is None:
            return self._no_prev("sell_ticket", "سرانه معاملات حقیقی")
        nb = snap.real_buy_count - prev_snap.real_buy_count
        ns = snap.real_sell_count - prev_snap.real_sell_count
        vb = snap.real_buy_value - prev_snap.real_buy_value
        vs = snap.real_sell_value - prev_snap.real_sell_value
        if nb < 0 or ns < 0 or vb < 0 or vs < 0:
            return self._counter_reset("sell_ticket", nb, ns)
        if nb == 0 and ns == 0:
            return self._no_trades("sell_ticket", "معامله حقیقی")
        full_at = self._get_threshold(snap.symbol, "sell_ticket")
        if not self._valid_full_at(full_at):
            return self._invalid_threshold("sell_ticket", full_at)
        if nb == 0:
            norm_signed, raw = 1.0, full_at
            desc = "(فقط فروشنده — امتیاز فروش کامل)"
        elif ns == 0:
            norm_signed, raw = -1.0, -full_at
            desc = "(فقط خریدار — امتیاز خرید کامل)"
        else:
            avg_b, avg_s = vb / nb, vs / ns
            ratio = _safe_div(avg_s, avg_b)
            if math.isnan(ratio) or ratio <= 0:
                return self._invalid_threshold("sell_ticket", full_at)
            raw = math.log(ratio)
            norm_signed = _clamp_signed(raw / full_at)
            desc = f"ln(سرانه فروش/خرید)={raw:+.4f}"
        damp = self._damp_for(norm_signed, snap)
        return self._score_signed("sell_ticket", raw, "ln(نسبت)", norm_signed, damp, desc)

    # -------------------------------------------------------------------
    # شاخص ۴: واکنش قیمت
    # -------------------------------------------------------------------
    def _factor_sell_price(self, snap, prev_snap):
        if prev_snap is None or prev_snap.last_price <= 0:
            return self._no_prev("sell_price", "قیمت ۳۰ث قبل")
        if snap.last_price <= 0:
            return self._invalid_threshold("sell_price", 0.0)
        ratio = snap.last_price / prev_snap.last_price
        if ratio <= 0:
            return self._invalid_threshold("sell_price", 0.0)
        raw = -math.log(ratio)
        # محافظ: |raw| بزرگ یعنی شکاف زمانی یا داده خراب
        if abs(raw) > 0.20:  # معادل ~22% تغییر — رد
            return self._invalid_threshold("sell_price", 0.20)
        full_at = self._get_threshold(snap.symbol, "sell_price")
        if not self._valid_full_at(full_at):
            return self._invalid_threshold("sell_price", full_at)
        norm_signed = _clamp_signed(raw / full_at)
        side_txt = "افت قیمت" if norm_signed > 0 else ("رشد قیمت" if norm_signed < 0 else "بدون تغییر")
        desc = f"Pt={snap.last_price:,.0f}، Pt-30s={prev_snap.last_price:,.0f} → {side_txt} ({raw:+.4f})"
        return self._score_signed("sell_price", raw, "−ln", norm_signed, 1.0, desc)

    # -------------------------------------------------------------------
    # شاخص ۵: عرضه/تقاضا در دفتر سفارش
    # -------------------------------------------------------------------
    def _factor_sell_supply(self, snap, prev_snap):
        if prev_snap is None:
            return self._no_prev("sell_supply", "عمق بازار")
        ask_prev, bid_prev = _ask5(prev_snap), _bid5(prev_snap)
        ask_now, bid_now = _ask5(snap), _bid5(snap)
        if ask_prev > 0:
            d_ask = (ask_now - ask_prev) / ask_prev
        elif ask_now > 0:
            d_ask = 1.0
        else:
            d_ask = 0.0
        if bid_prev > 0:
            d_bid = (bid_now - bid_prev) / bid_prev
        elif bid_now > 0:
            d_bid = 1.0
        else:
            d_bid = 0.0
        if ask_prev == 0 and ask_now == 0 and bid_prev == 0 and bid_now == 0:
            return self._no_trades("sell_supply", "عمق بازار")
        raw = d_ask - d_bid
        full_at = self._get_threshold(snap.symbol, "sell_supply")
        if not self._valid_full_at(full_at):
            return self._invalid_threshold("sell_supply", full_at)
        norm_signed = _clamp_signed(raw / full_at)
        side_txt = "رشد عرضه" if norm_signed > 0 else ("رشد تقاضا" if norm_signed < 0 else "تعادل")
        desc = f"Δask5={d_ask*100:+.1f}٪، Δbid5={d_bid*100:+.1f}٪ → {side_txt} ({raw:+.3f})"
        return self._score_signed("sell_supply", raw, "تفاضل درصد", norm_signed, 1.0, desc)

    # -------------------------------------------------------------------
    # شاخص ۶: موقعیت قیمت در دامنه
    # -------------------------------------------------------------------
    def _factor_sell_lower(self, snap):
        L, U = snap.min_allowed_price, snap.max_allowed_price
        if U <= L or U <= 0 or snap.last_price <= 0:
            return self._invalid_threshold("sell_lower", 0.0)
        raw = _clamp(1.0 - (snap.last_price - L) / (U - L), 0.0, 1.0)
        full_at = self._get_threshold(snap.symbol, "sell_lower")
        if not self._valid_full_at(full_at):
            return self._invalid_threshold("sell_lower", full_at)
        half = max(full_at - 0.5, 0.15)
        norm_signed = _clamp_signed((raw - 0.5) / half)
        side_txt = "نزدیک کف" if norm_signed > 0 else ("نزدیک سقف" if norm_signed < 0 else "وسط دامنه")
        desc = f"موقعیت={raw:.3f} ({side_txt})"
        return self._score_signed("sell_lower", raw, "موقعیت", norm_signed, 1.0, desc)

    # -------------------------------------------------------------------
    # کمکی‌ها
    # -------------------------------------------------------------------
    def _valid_full_at(self, full_at):
        return full_at is not None and not math.isnan(full_at) and full_at > 0

    def _no_prev(self, name, field):
        return SellPressureFactorResult(
            name=name, label=self.LABELS.get(name, name),
            max_points=self.weights.get(name, 0), raw_value=float("nan"),
            raw_unit="—", normalized=0.0, score=0.0,
            description=f"{field} در دسترس نیست.",
            status="no_prev", side="neutral")

    def _no_trades(self, name, field):
        return SellPressureFactorResult(
            name=name, label=self.LABELS.get(name, name),
            max_points=self.weights.get(name, 0), raw_value=0.0,
            raw_unit="—", normalized=0.0, score=0.0,
            description=f"بدون {field} جدید — خنثی.",
            status="no_trades", side="neutral")

    def _counter_reset(self, name, d1, d2):
        return SellPressureFactorResult(
            name=name, label=self.LABELS.get(name, name),
            max_points=self.weights.get(name, 0), raw_value=float("nan"),
            raw_unit="—", normalized=0.0, score=0.0,
            description=f"ریست شمارنده (Δ={d1},{d2}).",
            status="counter_reset", side="neutral")

    def _invalid_threshold(self, name, full_at):
        return SellPressureFactorResult(
            name=name, label=self.LABELS.get(name, name),
            max_points=self.weights.get(name, 0), raw_value=float("nan"),
            raw_unit="—", normalized=0.0, score=0.0,
            description=f"آستانه/دادهٔ نامعتبر ({full_at}).",
            status="invalid_threshold", side="neutral")

    # -------------------------------------------------------------------
    # محاسبه نهایی
    # -------------------------------------------------------------------
    def evaluate(self, snap, prev_snap=None):
        data_warning = None
        try:
            if not snap.data_complete:
                data_warning = f"داده ناقص: {', '.join(snap.missing_fields)}"
        except AttributeError:
            pass

        # رد شکاف زمانی
        gap = None
        if prev_snap is not None:
            gap = self._time_gap_seconds(snap, prev_snap)
            if not self._is_valid_prev(snap, prev_snap):
                data_warning = (data_warning or "") + f" | شکاف زمانی {gap:.0f}ث — دلتا رد شد"
                prev_snap = None

        # تأیید قیمت
        confirm_sell, confirm_buy, price_pct = self._price_confirm(snap, prev_snap)

        factors = [
            self._factor_sell_breadth(snap, prev_snap),
            self._factor_sell_flow(snap, prev_snap),
            self._factor_sell_ticket(snap, prev_snap),
            self._factor_sell_price(snap, prev_snap),
            self._factor_sell_supply(snap, prev_snap),
            self._factor_sell_lower(snap),
        ]

        # اعمال تأیید قیمت
        raw_sell = 0.0
        raw_buy = 0.0
        adj_sell = 0.0
        adj_buy = 0.0
        for f in factors:
            raw_sell += f.raw_sell_score
            raw_buy += f.raw_buy_score
            if f.side == "sell":
                f.sell_score = f.raw_sell_score * confirm_sell
                f.score = f.sell_score
                adj_sell += f.sell_score
            elif f.side == "buy":
                f.buy_score = f.raw_buy_score * confirm_buy
                adj_buy += f.buy_score

        sell_score = min(adj_sell, 100.0)
        buy_score = min(adj_buy, 100.0)
        net_score = buy_score - sell_score
        strength = max(sell_score, buy_score)
        dominant = "sell" if sell_score > buy_score else ("buy" if buy_score > sell_score else "neutral")

        valid = sum(1 for f in factors if f.status == "ok")
        independent_signals = sum(1 for f in factors if f.normalized >= 0.5)
        level, action = self._determine_level(sell_score)

        # بحرانی فقط با تأیید قیمت
        is_critical = sell_score >= 65 and confirm_sell >= 1.0
        is_critical_buy = buy_score >= 65 and confirm_buy >= 1.0
        engine_status = "official" if valid == len(factors) else "warming_up"

        return SellPressureResult(
            total_score=sell_score, level=level, action=action,
            factors=factors, independent_signals_count=independent_signals,
            is_critical=is_critical, snapshot_time=snap.tehran_time,
            valid_indicators=valid, engine_status=engine_status,
            data_quality_warning=data_warning,
            sell_score=sell_score, buy_score=buy_score,
            net_score=net_score, dominant=dominant, strength=strength,
            is_critical_buy=is_critical_buy,
            price_confirmation_sell=confirm_sell,
            price_confirmation_buy=confirm_buy,
            raw_sell_score=min(raw_sell, 100.0),
            raw_buy_score=min(raw_buy, 100.0))

    def _determine_level(self, score):
        if score <= 24: return self.levels["0-24"]["label"], self.levels["0-24"]["action"]
        elif score <= 34: return self.levels["25-34"]["label"], self.levels["25-34"]["action"]
        elif score <= 49: return self.levels["35-49"]["label"], self.levels["35-49"]["action"]
        elif score <= 64: return self.levels["50-64"]["label"], self.levels["50-64"]["action"]
        elif score <= 79: return self.levels["65-79"]["label"], self.levels["65-79"]["action"]
        else: return self.levels["80-100"]["label"], self.levels["80-100"]["action"]