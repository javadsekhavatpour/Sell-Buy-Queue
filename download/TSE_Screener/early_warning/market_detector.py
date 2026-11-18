"""
market_detector.py — تشخیص نوع بازار و ساعت‌های معاملات نماد از داده TSETMC.

منطق تشخیص:
  ۱. دریافت instrument_info از TSETMC (cIsin + flow)
  ۲. نگاشت پیشوند ISIN + کد flow به نوع بازار
  ۳. بازگشت برچسب بازار + ساعت پیش‌گشایش و معاملات پیوسته

جدول ساعت‌ها بر اساس منابع رسمی (emofid، charisma، bmibourse):
  سهام عادی + حق تقدم:        ۰۸:۴۵-۰۹:۰۰ پیش‌گشایش | ۰۹:۰۰-۱۲:۳۰ پیوسته
  صندوق ETF سهامی/مختلط:      ۰۸:۴۵-۰۹:۰۰ پیش‌گشایش | ۰۹:۰۰-۱۲:۳۰ پیوسته
  صندوق درآمد ثابت:            ۰۸:۲۵-۰۸:۳۰ پیش‌گشایش | ۰۸:۳۰-۱۵:۰۰ پیوسته
  صندوق کالایی طلا:            ۱۱:۳۰-۱۲:۰۰ پیش‌گشایش | ۱۲:۰۰-۱۸:۰۰ پیوسته
  صندوق کالایی کشاورزی:        ۰۸:۴۵-۰۹:۰۰ پیش‌گشایش | ۰۹:۰۰-۱۵:۰۰ پیوسته

کد flow در TSETMC:
  ۱ = بازار اول/دوم بورس (سهام + ETF) | ۲ = فرابورس | ۳ = اختیار معامله
  ۴ = بازار پایه | ۶ = صندوق درآمد ثابت | ۷ = بازار کالا (صندوق کالایی)

پیشوند ISIN:
  IRO1/IRO3/IRO7 = سهام | IRT1/IRT3 = صندوق سهامی ETF
  IRTK/IRTB = صندوق کالایی طلا | IRB = اوراق/صندوق درآمد ثابت | IRR = حق تقدم
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# جدول ساعت‌های معاملات بر اساس نوع بازار
# ---------------------------------------------------------------------------

MARKET_HOURS: Dict[str, Dict] = {
    "stock": {
        "label": "\u0633\u0647\u0627\u0645 \u0639\u0627\u062f\u06cc",  # سهام عادی
        "instrument_type": "\u0633\u0647\u0645",  # سهام
        "pre_open": ("08:45", "09:00"),
        "continuous": ("09:00", "12:30"),
        "days": "\u0634\u0646\u0628\u0647 \u062a\u0627 \u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",  # شنبه تا چهارشنبه
        "session_minutes": 210,  # 9:00-12:30 = 3.5h
    },
    "equity_etf": {
        "label": "\u0635\u0646\u062f\u0648\u0642 ETF \u0633\u0647\u0627\u0645\u06cc",  # صندوق ETF سهامی
        "instrument_type": "\u0635\u0646\u062f\u0648\u0642 \u0633\u0647\u0627\u0645\u06cc",  # صندوق سهامی
        "pre_open": ("08:45", "09:00"),
        "continuous": ("09:00", "12:30"),
        "days": "\u0634\u0646\u0628\u0647 \u062a\u0627 \u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
        "session_minutes": 210,
    },
    "fixed_income_fund": {
        "label": "\u0635\u0646\u062f\u0648\u0642 \u062f\u0631\u0622\u0645\u062f \u062b\u0627\u0628\u062a",  # صندوق درآمد ثابت
        "instrument_type": "\u0635\u0646\u062f\u0648\u0642 \u062f\u0631\u0622\u0645\u062f \u062b\u0627\u0628\u062a",
        "pre_open": ("08:25", "08:30"),
        "continuous": ("08:30", "15:00"),
        "days": "\u0634\u0646\u0628\u0647 \u062a\u0627 \u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
        "session_minutes": 390,  # 8:30-15:00 = 6.5h
    },
    "gold_commodity_fund": {
        "label": "\u0635\u0646\u062f\u0648\u0642 \u06a9\u0627\u0644\u0627\u06cc \u0637\u0644\u0627",  # صندوق کالایی طلا
        "instrument_type": "\u0635\u0646\u062f\u0648\u0642 \u06a9\u0627\u0644\u0627\u06cc \u0637\u0644\u0627",
        "pre_open": ("11:30", "12:00"),
        "continuous": ("12:00", "18:00"),
        "days": "\u0634\u0646\u0628\u0647 \u062a\u0627 \u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
        "session_minutes": 360,  # 12:00-18:00 = 6h
    },
    "agri_commodity_fund": {
        "label": "\u0635\u0646\u062f\u0648\u0642 \u06a9\u0627\u0644\u0627\u06cc \u06a9\u0634\u0627\u0648\u0631\u0632\u06cc",  # صندوق کالایی کشاورزی
        "instrument_type": "\u0635\u0646\u062f\u0648\u0642 \u06a9\u0627\u0644\u0627\u06cc",
        "pre_open": ("08:45", "09:00"),
        "continuous": ("09:00", "15:00"),
        "days": "\u0634\u0646\u0628\u0647 \u062a\u0627 \u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
        "session_minutes": 360,
    },
    "rights": {
        "label": "\u062d\u0642 \u062a\u0642\u062f\u0645",  # حق تقدم
        "instrument_type": "\u062d\u0642 \u062a\u0642\u062f\u0645",
        "pre_open": ("08:45", "09:00"),
        "continuous": ("09:00", "12:30"),
        "days": "\u0634\u0646\u0628\u0647 \u062a\u0627 \u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
        "session_minutes": 210,
    },
    "base_market": {
        "label": "\u0628\u0627\u0632\u0627\u0631 \u067e\u0627\u06cc\u0647",  # بازار پایه
        "instrument_type": "\u0633\u0647\u0627\u0645 \u0628\u0627\u0632\u0627\u0631 \u067e\u0627\u06cc\u0647",
        "pre_open": ("08:45", "09:00"),
        "continuous": ("09:00", "12:30"),  # بازار پایه حجم مبنایی: فقط مزایده ۱۱:۳۰
        "days": "\u0634\u0646\u0628\u0647 \u062a\u0627 \u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
        "session_minutes": 210,
    },
    "unknown": {
        "label": "\u0646\u0627\u0645\u0634\u062e\u0635",  # نامشخص
        "instrument_type": "\u0646\u0627\u0645\u0634\u062e\u0635",
        "pre_open": ("08:45", "09:00"),
        "continuous": ("09:00", "12:30"),  # fallback پیش‌فرض
        "days": "\u0634\u0646\u0628\u0647 \u062a\u0627 \u0686\u0647\u0627\u0631\u0634\u0646\u0628\u0647",
        "session_minutes": 210,
    },
}


# ---------------------------------------------------------------------------
# نگاشت پیشوند ISIN → نوع بازار
# ---------------------------------------------------------------------------

def _isin_to_market(isin: str) -> str:
    """تشخیص نوع بازار از پیشوند ISIN (۵ حرف اول)."""
    if not isin:
        return "unknown"
    p = isin[:5].upper()
    # صندوق کالایی طلا (IRTK, IRTB, IRTG, IRTA با کالایی)
    if p.startswith("IRTK") or p.startswith("IRTB") or p.startswith("IRTG"):
        return "gold_commodity_fund"
    # صندوق سهامی ETF (IRT1, IRT3, IRT7)
    if p.startswith("IRT1") or p.startswith("IRT3") or p.startswith("IRT7"):
        return "equity_etf"
    # حق تقدم (IRR1, IRR3)
    if p.startswith("IRR"):
        return "rights"
    # اوراق/صندوق درآمد ثابت (IRB1, IRB3, IRB7)
    if p.startswith("IRB"):
        return "fixed_income_fund"
    # سهام عادی (IRO1, IRO3, IRO7)
    if p.startswith("IRO"):
        return "stock"
    return "unknown"


def _flow_to_market(flow) -> str:
    """تشخیص نوع بازار از کد flow (عددی)."""
    try:
        f = int(flow)
    except (TypeError, ValueError):
        return "unknown"
    return {
        1: "stock",        # بازار اول/دوم (پیش‌فرض؛ ISIN دقیق‌تر)
        2: "stock",        # فرابورس
        3: "rights",       # اختیار معامله
        4: "base_market",  # بازار پایه
        6: "fixed_income_fund",
        7: "gold_commodity_fund",  # بازار کالا (صندوق کالایی)
    }.get(f, "unknown")


# ---------------------------------------------------------------------------
# تشخیص کامل بازار نماد
# ---------------------------------------------------------------------------

def detect_market(collector, ins_code: str) -> Dict:
    """
    تشخیص نوع بازار و ساعت‌های معاملات یک نماد.

    ورودی:
      collector: نمونه‌ی MarketDataCollector (برای fetch_instrument_info)
      ins_code: کد ۱۶ رقمی نماد در TSETMC

    خروجی:
      {
        ok: bool,
        ins_code, symbol (lVal18AFC), full_name (lVal30), isin, flow,
        market_type, market_label, instrument_type,
        trading_hours: {pre_open: (start,end), continuous: (start,end)},
        session_minutes, days
      }
    """
    try:
        info = collector.fetch_instrument_info(ins_code)
    except Exception as e:
        return {"ok": False, "ins_code": ins_code, "error": str(e)}

    if not info:
        return {"ok": False, "ins_code": ins_code, "error": "instrument_info خالی"}

    isin = (info.get("cIsin") or info.get("cISIN") or "").strip().upper()
    flow = info.get("flow")
    symbol = info.get("lVal18AFC") or ""
    full_name = info.get("lVal30") or ""

    # تشخیص از ISIN (دقیق‌تر) و fallback به flow
    market_type = _isin_to_market(isin)
    if market_type == "unknown":
        market_type = _flow_to_market(flow)

    hours = MARKET_HOURS.get(market_type, MARKET_HOURS["unknown"])

    return {
        "ok": True,
        "ins_code": ins_code,
        "symbol": symbol,
        "full_name": full_name,
        "isin": isin,
        "flow": flow,
        "market_type": market_type,
        "market_label": hours["label"],
        "instrument_type": hours["instrument_type"],
        "trading_hours": {
            "pre_open": list(hours["pre_open"]),
            "continuous": list(hours["continuous"]),
        },
        "session_minutes": hours["session_minutes"],
        "days": hours["days"],
    }


# ---------------------------------------------------------------------------
# کمکی: آیا زمان فعلی در جلسه‌ی معاملاتی نماد است؟
# ---------------------------------------------------------------------------

def _to_minutes(hhmm: str) -> int:
    """'09:00' → 540."""
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return -1


def in_trading_window(trading_hours: Dict, now_hhmm: str) -> Tuple[bool, str]:
    """
    آیا now_hhmm در پنجره‌ی معاملاتی (پیش‌گشایش تا پایان پیوسته) است؟

    خروجی: (در_جلسه, پیام_وضعیت)
    """
    pre = trading_hours.get("pre_open", ("08:45", "09:00"))
    cont = trading_hours.get("continuous", ("09:00", "12:30"))
    start = _to_minutes(pre[0])
    end = _to_minutes(cont[1])
    now = _to_minutes(now_hhmm)
    if now < 0 or start < 0 or end < 0:
        return False, "\u0646\u0627\u0645\u0634\u062e\u0635"
    if start <= now <= end:
        if now < _to_minutes(cont[0]):
            return True, "\u067e\u06cc\u0634\u200c\u06af\u0634\u0627\u06cc\u0634"  # پیش‌گشایش
        return True, "\u0645\u0639\u0627\u0645\u0644\u0627\u062a \u067e\u06cc\u0648\u0633\u062a\u0647"  # معاملات پیوسته
    if now < start:
        return False, f"\u062c\u0644\u0633\u0647 \u0634\u0631\u0648\u0639 \u0646\u0634\u062f\u0647 (\u0634\u0631\u0648\u0639 {pre[0]})"  # جلسه شروع نشده
    return False, f"\u062c\u0644\u0633\u0647 \u0628\u0633\u062a\u0647 (\u067e\u0627\u06cc\u0627\u0646 {cont[1]})"  # جلسه بسته
