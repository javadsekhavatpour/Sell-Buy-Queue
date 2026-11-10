"""
data_collector.py (نسخه ۲.۰)
دریافت‌کننده داده‌های تابلو از TSETMC و حالت شبیه‌سازی

بهبودهای نسخه ۲.۰:
  - پشتیبانی از چندین endpoint TSETMC به‌عنوان fallback
  - پیام خطای واضح‌تر
  - پارسر انعطاف‌پذیرتر (با ساختارهای مختلف)
  - ذخیره‌ی پاسخ خام برای دیباگ
  - وضعیت نماد و کد نماد به‌صورت خودکار
  - رفع مشکل آخرین قیمت ۰ در پیش‌گشایش
"""

from __future__ import annotations

import json
import random
import time
import math
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

import requests


# ---------------------------------------------------------------------------
# مدل داده - یک نمونه کامل از تابلو در یک لحظه زمانی
# ---------------------------------------------------------------------------

class MarketPhase(Enum):
    """گروه F - فاز بازار."""
    PRE_OPEN = "pre_open"
    OPENING_AUCTION = "opening_auction"
    CONTINUOUS = "continuous"
    HALTED = "halted"
    SYMBOL_SUSPENDED = "suspended"
    CLOSED = "closed"


@dataclass
class BestLimitRow:
    price: int = 0
    volume: int = 0
    order_count: int = 0


@dataclass
class Trade:
    trade_time: str
    trade_price: float
    trade_volume: int
    trade_id: Optional[str] = None
    aggressor_side: Optional[str] = None


@dataclass
class MarketSnapshot:
    """یک تصویر کامل از تابلو در یک لحظه - شامل تمام شش گروه فیلد."""

    # ===== گروه F - وضعیت بازار و شناسه =====
    snapshot_id: Optional[int] = None
    date_jalali: str = ""
    timestamp: str = ""
    tehran_time: str = ""
    symbol: str = ""
    ins_code: str = ""
    market_phase: str = "continuous"
    symbol_status: str = "allowed"
    source_update_time: str = ""
    data_status: str = "ok"
    fetch_error: str = ""

    # ===== گروه A - قیمت‌ها =====
    last_price: float = 0.0
    close_price: float = 0.0
    open_price: float = 0.0
    yesterday_price: float = 0.0
    daily_high: float = 0.0
    daily_low: float = 0.0
    min_allowed_price: float = 0.0
    max_allowed_price: float = 0.0

    # ===== گروه B - پنج ردیف سفارش =====
    best_buy_price: float = 0.0
    best_buy_volume: int = 0
    best_sell_price: float = 0.0
    best_sell_volume: int = 0
    buy_rows: List[BestLimitRow] = field(default_factory=list)
    sell_rows: List[BestLimitRow] = field(default_factory=list)
    buy_order_count: int = 0
    sell_order_count: int = 0

    # ===== گروه C - حجم/ارزش/تعداد معاملات تجمعی =====
    total_volume: int = 0
    total_value: float = 0.0
    total_trade_count: int = 0
    base_volume: int = 0
    interval_volume: int = 0
    interval_value: float = 0.0
    interval_trade_count: int = 0

    # ===== گروه D - اطلاعات حقیقی/حقوقی =====
    real_buy_count: int = 0
    real_buy_volume: int = 0
    real_buy_value: float = 0.0
    real_sell_count: int = 0
    real_sell_volume: int = 0
    real_sell_value: float = 0.0
    legal_buy_count: int = 0
    legal_buy_volume: int = 0
    legal_buy_value: float = 0.0
    legal_sell_count: int = 0
    legal_sell_volume: int = 0
    legal_sell_value: float = 0.0

    # ===== شاخص‌های مشتق =====
    buyer_power: float = 0.0
    per_capita_buy_real: float = 0.0
    per_capita_sell_real: float = 0.0
    real_money_flow: float = 0.0
    real_money_flow_ratio: float = 0.0
    interval_real_buy_volume: int = 0
    interval_real_sell_volume: int = 0

    # ===== کیفیت داده =====
    data_complete: bool = True
    missing_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_flat_dict(self) -> Dict:
        d = {}
        for k, v in asdict(self).items():
            if k not in ("buy_rows", "sell_rows", "missing_fields"):
                d[k] = v
        for i, row in enumerate(self.buy_rows[:5], 1):
            d[f"bid_price_{i}"] = row.price
            d[f"bid_volume_{i}"] = row.volume
            d[f"bid_count_{i}"] = row.order_count
        for i, row in enumerate(self.sell_rows[:5], 1):
            d[f"ask_price_{i}"] = row.price
            d[f"ask_volume_{i}"] = row.volume
            d[f"ask_count_{i}"] = row.order_count
        for i in range(len(self.buy_rows) + 1, 6):
            d[f"bid_price_{i}"] = None
            d[f"bid_volume_{i}"] = None
            d[f"bid_count_{i}"] = None
        for i in range(len(self.sell_rows) + 1, 6):
            d[f"ask_price_{i}"] = None
            d[f"ask_volume_{i}"] = None
            d[f"ask_count_{i}"] = None
        d["missing_fields"] = ", ".join(self.missing_fields) if self.missing_fields else ""
        return d


# ---------------------------------------------------------------------------
# کلکتور واقعی - TSETMC (نسخه ۲.۰ با fallback و diagnostic)
# ---------------------------------------------------------------------------

class MarketDataCollector:
    """
    دریافت داده از TSETMC برای نماد مشخص شده.

    نسخه ۳.۰: استفاده از API جدید cdn.tsetmc.com (JSON API)

    TSETMC سایت قدیمی را به یک React SPA تبدیل کرده و دیگر
    /tsev2/data/instinfodata.aspx پاسخ متنی نمی‌دهد. به‌جای آن
    از JSON API روی cdn.tsetmc.com استفاده می‌کنیم.

    Endpoints استفاده‌شده:
      - ClosingPrice/GetClosingPriceInfo/{InsCode}  - داده‌های قیمت
      - BestLimits/{InsCode}                       - ۵ ردیف سفارش
      - ClientType/GetClientType/{InsCode}          - حقیقی/حقوقی
      - Instrument/GetInstrumentSearch/{query}      - جستجوی نماد
      - Trade/GetTradeHistory/{InsCode}/{Top}       - معاملات اخیر
    """

    # API جدید TSETMC روی cdn.tsetmc.com (نه www)
    API_BASE = "https://cdn.tsetmc.com/api"

    def __init__(self, config: Dict):
        self.cfg = config
        self.endpoints = config.get("tsetmc_endpoints", {})
        self.session = requests.Session()
        # هدرهای کامل برای شبیه‌سازی مرورگر
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Referer": "http://www.tsetmc.com/",
            "Origin": "http://www.tsetmc.com",
        })
        self.timeout = self.endpoints.get("timeout_seconds", 15)
        self.debug_mode = False
        self.last_raw_responses: Dict[str, str] = {}

    def enable_debug(self, debug_dir: Optional[Path] = None):
        """فعال‌سازی حالت دیباگ - ذخیره پاسخ‌های خام."""
        self.debug_mode = True
        self.debug_dir = debug_dir or Path("data/raw_responses")
        self.debug_dir.mkdir(parents=True, exist_ok=True)

    def _save_debug(self, name: str, content: str):
        if not self.debug_mode:
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = self.debug_dir / f"{name}_{ts}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    def _api_get(self, endpoint: str, parse_json: bool = True) -> Optional[Any]:
        """درخواست GET به API جدید TSETMC."""
        url = f"{self.API_BASE}/{endpoint.lstrip('/')}"
        try:
            r = self.session.get(url, timeout=self.timeout)
            if r.status_code != 200:
                if self.debug_mode:
                    print(f"  [!] {endpoint}: HTTP {r.status_code}")
                return None
            if not r.text.strip():
                return None
            self._save_debug(endpoint.replace("/", "_"), r.text)
            if parse_json:
                try:
                    return r.json()
                except Exception:
                    # اگر JSON نبود، متن خام را برگردان
                    return r.text
            return r.text
        except Exception as e:
            if self.debug_mode:
                print(f"  [!] {endpoint}: {e}")
            return None

    # -----------------------------------------------------------------
    # دریافت داده با API جدید
    # -----------------------------------------------------------------

    def fetch_intraday(self, ins_code: str) -> Optional[Dict]:
        """دریافت داده‌های قیمت روز جاری از API جدید."""
        # داده‌های قیمت پایانی
        price_data = self._api_get(f"ClosingPrice/GetClosingPriceInfo/{ins_code}")
        if not price_data or not isinstance(price_data, dict):
            if self.debug_mode:
                print(f"  [!] price data: invalid response")
            return None

        # استخراج داده‌ها از JSON
        # ساختار معمول: {"closingPriceInfo": {...}, "closingPriceInfoHistory": [...]}
        info_data = price_data.get("closingPriceInfo") or price_data.get("ClosingPriceInfo") or price_data
        if not isinstance(info_data, dict):
            return None

        info = {
            "last_price": float(info_data.get("pDrCotVal") or info_data.get("lastPrice") or 0),
            "close_price": float(info_data.get("pClosing") or info_data.get("closingPrice") or 0),
            "yesterday_price": float(info_data.get("priceYesterday") or info_data.get("yesterday") or 0),
            "daily_high": float(info_data.get("priceHigh") or 0),
            "daily_low": float(info_data.get("priceLow") or 0),
            "trade_volume": int(info_data.get("zTotTran") or info_data.get("totalVolume") or 0),
            "trade_value": float(info_data.get("qTotTranValJAdj") or info_data.get("totalValue") or 0),
            "trade_count": int(info_data.get("zTotTran") or info_data.get("tradeCount") or 0),
            "buy_rows": [],
            "sell_rows": [],
            "min_allowed": 0,
            "max_allowed": 0,
            "base_volume": 100000,
        }

        # دریافت BestLimits (۵ ردیف سفارش)
        limits_data = self._api_get(f"BestLimits/{ins_code}")
        if limits_data and isinstance(limits_data, dict):
            # ساختار: {"bestLimits": [...], "bestLimitsHistory": [...]}
            limits_list = (limits_data.get("bestLimits") or
                          limits_data.get("BestLimits") or
                          limits_data.get("bestLimitsHistory") or [])
            if isinstance(limits_list, list):
                buy_rows, sell_rows = [], []
                for row in limits_list:
                    if not isinstance(row, dict):
                        continue
                    # هر ردیف: pMeDem (قیمت خرید), qTitMeDem (حجم خرید), zOrdMeDem (تعداد خرید)
                    #           pMeOf (قیمت فروش), qTitMeOf (حجم فروش), zOrdMeOf (تعداد فروش)
                    buy_price = int(float(row.get("pMeDem") or 0))
                    buy_vol = int(float(row.get("qTitMeDem") or 0))
                    buy_count = int(float(row.get("zOrdMeDem") or 0))
                    sell_price = int(float(row.get("pMeOf") or 0))
                    sell_vol = int(float(row.get("qTitMeOf") or 0))
                    sell_count = int(float(row.get("zOrdMeOf") or 0))

                    if buy_price > 0:
                        buy_rows.append({
                            "price": buy_price,
                            "volume": buy_vol,
                            "order_count": max(1, buy_count),
                        })
                    if sell_price > 0:
                        sell_rows.append({
                            "price": sell_price,
                            "volume": sell_vol,
                            "order_count": max(1, sell_count),
                        })

                info["buy_rows"] = buy_rows[:5]
                info["sell_rows"] = sell_rows[:5]
                if buy_rows:
                    info["daily_high"] = info["daily_high"] or max(r["price"] for r in sell_rows + buy_rows if r["price"] > 0)
                if buy_rows:
                    info["daily_low"] = info["daily_low"] or min(r["price"] for r in buy_rows if r["price"] > 0)

        # محاسبه کف و سقف مجاز
        if info["yesterday_price"] > 0:
            info["min_allowed"] = round(info["yesterday_price"] * 0.95, 2)
            info["max_allowed"] = round(info["yesterday_price"] * 1.05, 2)

        return info

    def fetch_clienttype(self, ins_code: str) -> Optional[Dict]:
        """دریافت اطلاعات حقیقی/حقوقی از API جدید."""
        data = self._api_get(f"ClientType/GetClientType/{ins_code}/1/0")
        if not data or not isinstance(data, dict):
            return None

        # ساختار: {"clientType": {...}}
        ct_data = data.get("clientType") or data.get("ClientType") or data
        if not isinstance(ct_data, dict):
            # ممکن است لیست باشد
            if isinstance(ct_data, list) and len(ct_data) > 0:
                ct_data = ct_data[-1]  # آخرین ردیف
            else:
                return None

        return {
            "real_buy_count": int(float(ct_data.get("nIndividualBuy") or 0)),
            "real_sell_count": int(float(ct_data.get("nIndividualSell") or 0)),
            "real_buy_volume": int(float(ct_data.get("nVolIndividualBuy") or 0)),
            "real_sell_volume": int(float(ct_data.get("nVolIndividualSell") or 0)),
            "legal_buy_count": int(float(ct_data.get("nCorporateBuy") or 0)),
            "legal_sell_count": int(float(ct_data.get("nCorporateSell") or 0)),
            "legal_buy_volume": int(float(ct_data.get("nVolCorporateBuy") or 0)),
            "legal_sell_volume": int(float(ct_data.get("nVolCorporateSell") or 0)),
        }

    def fetch_trades(self, ins_code: str) -> List[Trade]:
        """
        دریافت معاملات انجام‌شده اخیر از API جدید.

        نکته: API جدید TSETMC (cdn.tsetmc.com) endpoint جداگانه برای
        تاریخچه معاملات اخیر ندارد. داده‌های معاملات در GetClosingPriceInfo
        به‌صورت تجمعی موجود است (zTotTran تعداد، qTotTranValJAdj ارزش).
        برای دریافت لیست معاملات لحظه‌ای، از MarketWatch استفاده می‌کنیم.

        این متد لیست خالی برمی‌گرداند تا با موتورهای تحلیلی سازگار باشد.
        """
        # در API جدید، داده‌های تجمعی معاملات در fetch_intraday آمده
        # برای معاملات لحظه‌ای می‌توان از MarketWatch استفاده کرد
        # ولی برای سادگی فعلاً لیست خالی برمی‌گردانیم
        return []

    def search_symbol(self, query: str) -> List[Dict]:
        """جستجوی نماد در TSETMC."""
        data = self._api_get(f"Instrument/GetInstrumentSearch/{query}")
        if not data or not isinstance(data, dict):
            return []

        results_list = data.get("instrumentSearch") or data.get("InstrumentSearch") or []
        if not isinstance(results_list, list):
            return []

        return [{
            "code": str(item.get("insCode") or ""),
            "name_fa": item.get("lVal18Afc") or item.get("lVal30File") or "",
            "name_en": item.get("lSym") or "",
            "isin": item.get("lVal18Afc") or "",
        } for item in results_list if isinstance(item, dict)]

    # -----------------------------------------------------------------
    # دریافت کامل یک نمونه
    # -----------------------------------------------------------------

    def collect(self, symbol: str, ins_code: str,
                prev_snap: Optional[MarketSnapshot] = None,
                fetch_trades: bool = True) -> Tuple[Optional[MarketSnapshot], List[Trade]]:
        """دریافت کامل یک نمونه از تابلو + معاملات اخیر."""

        # دریافت داده‌ها
        inst = self.fetch_intraday(ins_code)
        ct = self.fetch_clienttype(ins_code)
        trades = self.fetch_trades(ins_code) if fetch_trades else []

        # اگر هیچ داده‌ای دریافت نشد
        if not inst or (inst.get("last_price", 0) == 0 and inst.get("close_price", 0) == 0):
            # ساخت یک نمونه خالی ولی با اطلاعات زمانی
            now = datetime.now()
            snap = MarketSnapshot(
                timestamp=now.isoformat(),
                tehran_time=now.strftime("%H:%M:%S"),
                symbol=symbol,
                ins_code=ins_code,
                market_phase=self._detect_market_phase(),
                data_status="error",
                fetch_error="داده از TSETMC دریافت نشد - بررسی اتصال یا کد نماد",
                yesterday_price=self.cfg.get("test_symbol", {}).get("base_price", 13000),
                min_allowed_price=self.cfg.get("test_symbol", {}).get("base_price", 13000) * 0.95,
                max_allowed_price=self.cfg.get("test_symbol", {}).get("base_price", 13000) * 1.05,
            )
            return snap, []

        # ساخت نمونه
        now = datetime.now()
        yesterday_price = inst.get("yesterday_price") or self.cfg.get("test_symbol", {}).get("base_price", 13000)
        snap = MarketSnapshot(
            timestamp=now.isoformat(),
            tehran_time=now.strftime("%H:%M:%S"),
            symbol=symbol,
            ins_code=ins_code,
            market_phase=self._detect_market_phase(),
            source_update_time=now.isoformat(),
            data_status="ok" if inst.get("last_price", 0) > 0 else "partial",
            last_price=inst.get("last_price", 0),
            close_price=inst.get("close_price", 0),
            open_price=inst.get("open_price", yesterday_price),
            yesterday_price=yesterday_price,
            daily_high=inst.get("daily_high", 0),
            daily_low=inst.get("daily_low", 0),
            min_allowed_price=round(yesterday_price * 0.95, 2),
            max_allowed_price=round(yesterday_price * 1.05, 2),
            base_volume=inst.get("base_volume", 100000),
            best_buy_price=inst["buy_rows"][0]["price"] if inst.get("buy_rows") else 0,
            best_buy_volume=inst["buy_rows"][0]["volume"] if inst.get("buy_rows") else 0,
            best_sell_price=inst["sell_rows"][0]["price"] if inst.get("sell_rows") else 0,
            best_sell_volume=inst["sell_rows"][0]["volume"] if inst.get("sell_rows") else 0,
            buy_rows=[BestLimitRow(**r) for r in inst.get("buy_rows", [])],
            sell_rows=[BestLimitRow(**r) for r in inst.get("sell_rows", [])],
            buy_order_count=sum(r["order_count"] for r in inst.get("buy_rows", [])),
            sell_order_count=sum(r["order_count"] for r in inst.get("sell_rows", [])),
            total_volume=inst.get("trade_volume", 0),
            total_value=inst.get("trade_value", 0) or (inst.get("last_price", 0) * inst.get("trade_volume", 0)),
            total_trade_count=inst.get("trade_count", 0),
            real_buy_volume=ct.get("real_buy_volume", 0) if ct else 0,
            real_sell_volume=ct.get("real_sell_volume", 0) if ct else 0,
            legal_buy_volume=ct.get("legal_buy_volume", 0) if ct else 0,
            legal_sell_volume=ct.get("legal_sell_volume", 0) if ct else 0,
            real_buy_count=ct.get("real_buy_count", 0) if ct else 0,
            real_sell_count=ct.get("real_sell_count", 0) if ct else 0,
            legal_buy_count=ct.get("legal_buy_count", 0) if ct else 0,
            legal_sell_count=ct.get("legal_sell_count", 0) if ct else 0,
        )

        # مقادیر بازه‌ای از تفاضل نمونه قبلی
        if prev_snap is not None:
            snap.interval_volume = max(0, snap.total_volume - prev_snap.total_volume)
            snap.interval_value = max(0, snap.total_value - prev_snap.total_value)
            snap.interval_trade_count = max(0, snap.total_trade_count - prev_snap.total_trade_count)
            snap.interval_real_buy_volume = max(0, snap.real_buy_volume - prev_snap.real_buy_volume)
            snap.interval_real_sell_volume = max(0, snap.real_sell_volume - prev_snap.real_sell_volume)

        # محاسبه شاخص‌های مشتق
        self._compute_derived(snap)
        self._mark_completeness(snap)

        return snap, trades

    def _detect_market_phase(self) -> str:
        """تشخیص فاز بازار بر اساس زمان تهران."""
        now = datetime.now()
        h, m = now.hour, now.minute
        hm = h * 60 + m
        # فاز پیش‌گشایش: 08:45 تا 09:00
        if 8 * 60 + 45 <= hm < 9 * 60:
            return MarketPhase.PRE_OPEN.value
        # فاز پیوسته - بازار اولیه: 09:00 تا 12:30 (بورس اوراق بهادار)
        elif 9 * 60 <= hm < 12 * 60 + 30:
            return MarketPhase.CONTINUOUS.value
        # فاز پیوسته - بازار ثانویه: 12:30 تا 18:00
        # (شامل صندوق‌های کالایی مثل ریتون که تا 18:00 باز هستند)
        elif 12 * 60 + 30 <= hm < 18 * 60:
            return MarketPhase.CONTINUOUS.value
        else:
            return MarketPhase.CLOSED.value

    def _compute_derived(self, s: MarketSnapshot):
        """محاسبه شاخص‌های مشتق."""
        s.per_capita_buy_real = s.real_buy_volume / max(s.real_buy_count, 1)
        s.per_capita_sell_real = s.real_sell_volume / max(s.real_sell_count, 1)
        s.buyer_power = s.per_capita_buy_real / max(s.per_capita_sell_real, 1e-9)
        avg_price = s.close_price if s.close_price > 0 else s.last_price
        s.real_buy_value = s.real_buy_volume * avg_price
        s.real_sell_value = s.real_sell_volume * avg_price
        s.legal_buy_value = s.legal_buy_volume * avg_price
        s.legal_sell_value = s.legal_sell_volume * avg_price
        s.real_money_flow = s.real_buy_value - s.real_sell_value
        s.real_money_flow_ratio = s.real_money_flow / max(s.total_value, 1e-9)

    def _mark_completeness(self, s: MarketSnapshot):
        """علامت‌گذاری فیلدهای مفقود."""
        missing = []
        if s.last_price <= 0: missing.append("last_price")
        if s.close_price <= 0: missing.append("close_price")
        if not s.buy_rows: missing.append("buy_rows")
        if not s.sell_rows: missing.append("sell_rows")
        if s.real_buy_count == 0 and s.real_sell_count == 0: missing.append("clienttype")
        s.missing_fields = missing
        s.data_complete = (len(missing) == 0)


# ---------------------------------------------------------------------------
# شبیه‌ساز کامل - برای تست آفلاین موتورها
# (دقیقاً همان نسخه قبلی باقی می‌ماند)
# ---------------------------------------------------------------------------

class SimulationDataCollector:
    """
    شبیه‌ساز داده تابلو با سناریوهای واقع‌نما برای تست موتورهای تحلیلی.

    سناریوها:
      - 'normal':       روز عادی با نوسان ملایم
      - 'sell_pressure': فشار فروش تدریجی منتهی به صف فروش
      - 'accumulation':  جمع‌آوری پنهان در روز منفی
      - 'mixed':         ترکیب فشار فروش و جمع‌آوری هم‌زمان

    پشتیبانی از فازهای بازار (گروه F):
      - 08:45-09:00 پیش‌گشایش (PRE_OPEN)
      - 09:00-12:30 معاملات پیوسته (CONTINUOUS)
    """

    def __init__(self, config: Dict, scenario: str = "sell_pressure",
                 seed: Optional[int] = None):
        self.cfg = config
        self.scenario = scenario
        self.rng = random.Random(seed)
        sym = config["test_symbol"]
        self.symbol = sym["name"]
        self.ins_code = sym["ins_code"]
        self.base_price = float(sym["base_price"])
        self.base_volume = 100_000
        self.start_time = datetime(2024, 11, 9, 8, 45, 0)

    def generate_series(self, num_samples: int = 226) -> Tuple[List[MarketSnapshot], List[Trade]]:
        snapshots: List[MarketSnapshot] = []
        all_trades: List[Trade] = []
        state = self._init_scenario_state()

        for i in range(num_samples):
            t = self.start_time + timedelta(seconds=60 * i)
            snap, trades_in_minute = self._build_snapshot(t, i, num_samples, state)
            snapshots.append(snap)
            all_trades.extend(trades_in_minute)
        return snapshots, all_trades

    def _init_scenario_state(self) -> Dict:
        return {
            "yesterday_price": self.base_price,
            "open_price": self.base_price,
            "high": self.base_price,
            "low": self.base_price,
            "accumulated_buy_volume": 0,
            "accumulated_sell_volume": 0,
            "prev_best_buy_volume": 50000,
            "prev_best_sell_volume": 40000,
            "trade_volume_today": 0,
            "trade_value_today": 0,
            "trade_count_today": 0,
            "cumulative_buy_count": 0,
            "cumulative_sell_count": 0,
            "cumulative_legal_buy_count": 0,
            "cumulative_legal_sell_count": 0,
            "accumulated_legal_buy_volume": 0,
            "accumulated_legal_sell_volume": 0,
            "money_flow_history": [],
            "buyer_power_history": [],
            "price_path": [self.base_price],
            "trade_seq": 0,
        }

    def _is_pre_open(self, idx: int) -> bool:
        return idx < 15

    def _build_snapshot(self, t: datetime, idx: int, total: int, st: Dict) -> Tuple[MarketSnapshot, List[Trade]]:
        progress = idx / max(total - 1, 1)
        is_pre_open = self._is_pre_open(idx)
        market_phase = MarketPhase.PRE_OPEN.value if is_pre_open else MarketPhase.CONTINUOUS.value

        if is_pre_open:
            last = self.base_price
            close = self.base_price
        else:
            adjusted_idx = idx - 15
            adjusted_total = total - 15
            adj_progress = adjusted_idx / max(adjusted_total - 1, 1)

            if self.scenario == "normal":
                last = self.base_price * (1 + 0.005 * math.sin(adjusted_idx * 0.3) + self.rng.gauss(0, 0.002))
            elif self.scenario == "sell_pressure":
                drop = -(0.005 + 0.075 * adj_progress ** 1.3)
                last = self.base_price * (1 + drop + self.rng.gauss(0, 0.002))
            elif self.scenario == "accumulation":
                drop = -(0.005 + 0.025 * adj_progress)
                last = self.base_price * (1 + drop + self.rng.gauss(0, 0.002))
            else:
                drop = -(0.005 + 0.035 * adj_progress)
                last = self.base_price * (1 + drop + 0.004 * math.sin(adjusted_idx * 0.4) + self.rng.gauss(0, 0.002))

            last = max(last, self.base_price * 0.85)
            close = last * (1 + self.rng.gauss(0, 0.0008))
            close = max(close, last * 0.998)
            if self.scenario == "sell_pressure":
                close = max(close, last * 1.001)
            elif self.scenario == "accumulation":
                close = min(close, last * 0.999)

            if st["open_price"] == self.base_price and adjusted_idx == 0:
                st["open_price"] = last

        st["high"] = max(st["high"], last, close)
        st["low"] = min(st["low"], last, close)

        min_allowed = round(self.base_price * 0.95, 2)
        max_allowed = round(self.base_price * 1.05, 2)

        best_buy_price = int(last * 0.998)
        best_sell_price = int(last * 1.002)

        if is_pre_open:
            base_buy_vol = int(20000 * (1 + 0.05 * self.rng.gauss(0, 1)))
            base_sell_vol = int(18000 * (1 + 0.05 * self.rng.gauss(0, 1)))
        elif self.scenario == "sell_pressure":
            base_buy_vol = max(2000, int(50000 * (1 - 0.7 * progress)))
            base_sell_vol = int(40000 * (1 + 2.0 * progress))
        elif self.scenario == "accumulation":
            base_buy_vol = int(60000 * (1 + 0.5 * progress))
            base_sell_vol = int(80000 * (1 + 0.4 * progress))
        elif self.scenario == "mixed":
            base_buy_vol = int(70000 * (1 + 0.5 * progress))
            base_sell_vol = int(90000 * (1 + 0.7 * progress))
        else:
            base_buy_vol = int(50000 * (1 + 0.05 * self.rng.gauss(0, 1)))
            base_sell_vol = int(45000 * (1 + 0.05 * self.rng.gauss(0, 1)))

        buy_rows = []
        for k in range(5):
            buy_rows.append(BestLimitRow(
                price=best_buy_price - k * 10,
                volume=max(100, int(base_buy_vol * (1 - 0.15 * k) * (1 + self.rng.gauss(0, 0.1)))),
                order_count=max(1, int(20 * (1 - 0.1 * k) + self.rng.gauss(0, 3))),
            ))
        sell_rows = []
        for k in range(5):
            sell_rows.append(BestLimitRow(
                price=best_sell_price + k * 10,
                volume=max(100, int(base_sell_vol * (1 - 0.15 * k) * (1 + self.rng.gauss(0, 0.1)))),
                order_count=max(1, int(20 * (1 - 0.1 * k) + self.rng.gauss(0, 3))),
            ))

        trades_in_minute: List[Trade] = []
        if not is_pre_open:
            num_trades = int(self.rng.uniform(20, 60))
            for _ in range(num_trades):
                st["trade_seq"] += 1
                t_price = last * (1 + self.rng.gauss(0, 0.001))
                t_vol = int(self.rng.uniform(500, 5000))
                aggressor = "buy" if self.rng.random() < 0.5 else "sell"
                trades_in_minute.append(Trade(
                    trade_time=t.strftime("%H:%M:%S"),
                    trade_price=round(t_price, 2),
                    trade_volume=t_vol,
                    trade_id=f"SIM-{st['trade_seq']:06d}",
                    aggressor_side=aggressor,
                ))

        if not is_pre_open:
            trade_vol_minute = sum(tr.trade_volume for tr in trades_in_minute)
            trade_val_minute = sum(tr.trade_price * tr.trade_volume for tr in trades_in_minute)
            trade_count_minute = len(trades_in_minute)
        else:
            trade_vol_minute = 0
            trade_val_minute = 0.0
            trade_count_minute = 0

        if self.scenario == "sell_pressure":
            end_buy_count = 600
            end_sell_count = 2500
            real_buy_share = 0.10
            real_sell_share = 0.85
            legal_buy_share = 0.05
            legal_sell_share = 0.10
        elif self.scenario == "accumulation":
            end_buy_count = 600
            end_sell_count = 2500
            real_buy_share = 0.80
            real_sell_share = 0.15
            legal_buy_share = 0.18
            legal_sell_share = 0.10
        elif self.scenario == "mixed":
            end_buy_count = 200
            end_sell_count = 2500
            real_buy_share = 0.40
            real_sell_share = 0.55
            legal_buy_share = 0.15
            legal_sell_share = 0.15
        else:
            end_buy_count = 1500
            end_sell_count = 1500
            real_buy_share = 0.45
            real_sell_share = 0.45
            legal_buy_share = 0.15
            legal_sell_share = 0.10

        new_buyers = max(0, int((end_buy_count / total) * (1 + self.rng.gauss(0, 0.15))))
        new_sellers = max(0, int((end_sell_count / total) * (1 + self.rng.gauss(0, 0.15))))
        if is_pre_open:
            new_buyers = int(new_buyers * 0.3)
            new_sellers = int(new_sellers * 0.3)
        st["cumulative_buy_count"] += new_buyers
        st["cumulative_sell_count"] += new_sellers

        if not is_pre_open:
            real_buy_share = max(0.05, real_buy_share + self.rng.gauss(0, 0.03))
            real_sell_share = max(0.05, real_sell_share + self.rng.gauss(0, 0.03))
        else:
            real_buy_share = 0
            real_sell_share = 0

        real_buy_vol = int(trade_vol_minute * real_buy_share)
        real_sell_vol = int(trade_vol_minute * real_sell_share)
        legal_buy_vol = int(trade_vol_minute * max(0.02, legal_buy_share)) if not is_pre_open else 0
        legal_sell_vol = int(trade_vol_minute * max(0.02, legal_sell_share)) if not is_pre_open else 0

        st["trade_volume_today"] += trade_vol_minute
        st["trade_value_today"] += trade_val_minute
        st["trade_count_today"] += trade_count_minute
        st["accumulated_buy_volume"] += real_buy_vol
        st["accumulated_sell_volume"] += real_sell_vol
        st["accumulated_legal_buy_volume"] += legal_buy_vol
        st["accumulated_legal_sell_volume"] += legal_sell_vol
        new_legal_buyers = max(0, int((end_buy_count * 0.3 / total) * (1 + self.rng.gauss(0, 0.15))))
        new_legal_sellers = max(0, int((end_sell_count * 0.3 / total) * (1 + self.rng.gauss(0, 0.15))))
        st["cumulative_legal_buy_count"] += new_legal_buyers
        st["cumulative_legal_sell_count"] += new_legal_sellers

        snap = MarketSnapshot(
            date_jalali="1403-08-19",
            timestamp=t.isoformat(),
            tehran_time=t.strftime("%H:%M:%S"),
            symbol=self.symbol,
            ins_code=self.ins_code,
            market_phase=market_phase,
            symbol_status="allowed",
            source_update_time=t.isoformat(),
            data_status="ok",
            last_price=round(last, 2),
            close_price=round(close, 2),
            open_price=st["open_price"],
            yesterday_price=st["yesterday_price"],
            daily_high=st["high"],
            daily_low=st["low"],
            min_allowed_price=min_allowed,
            max_allowed_price=max_allowed,
            best_buy_price=buy_rows[0].price,
            best_buy_volume=buy_rows[0].volume,
            best_sell_price=sell_rows[0].price,
            best_sell_volume=sell_rows[0].volume,
            buy_rows=buy_rows,
            sell_rows=sell_rows,
            buy_order_count=sum(r.order_count for r in buy_rows),
            sell_order_count=sum(r.order_count for r in sell_rows),
            total_volume=st["trade_volume_today"],
            total_value=st["trade_value_today"],
            total_trade_count=st["trade_count_today"],
            base_volume=self.base_volume,
            interval_volume=trade_vol_minute,
            interval_value=trade_val_minute,
            interval_trade_count=trade_count_minute,
            real_buy_volume=st["accumulated_buy_volume"],
            real_sell_volume=st["accumulated_sell_volume"],
            legal_buy_volume=st["accumulated_legal_buy_volume"],
            legal_sell_volume=st["accumulated_legal_sell_volume"],
            real_buy_count=st["cumulative_buy_count"],
            real_sell_count=st["cumulative_sell_count"],
            legal_buy_count=st["cumulative_legal_buy_count"],
            legal_sell_count=st["cumulative_legal_sell_count"],
        )

        if not is_pre_open:
            snap.interval_real_buy_volume = real_buy_vol
            snap.interval_real_sell_volume = real_sell_vol

        snap.per_capita_buy_real = snap.real_buy_volume / max(snap.real_buy_count, 1)
        snap.per_capita_sell_real = snap.real_sell_volume / max(snap.real_sell_count, 1)
        snap.buyer_power = snap.per_capita_buy_real / max(snap.per_capita_sell_real, 1e-9)
        snap.real_buy_value = snap.real_buy_volume * snap.close_price
        snap.real_sell_value = snap.real_sell_volume * snap.close_price
        snap.legal_buy_value = snap.legal_buy_volume * snap.close_price
        snap.legal_sell_value = snap.legal_sell_volume * snap.close_price
        snap.real_money_flow = snap.real_buy_value - snap.real_sell_value
        snap.real_money_flow_ratio = snap.real_money_flow / max(snap.total_value, 1e-9)

        st["money_flow_history"].append(snap.real_money_flow)
        st["buyer_power_history"].append(snap.buyer_power)
        st["prev_best_buy_volume"] = snap.best_buy_volume
        st["prev_best_sell_volume"] = snap.best_sell_volume
        st["price_path"].append(last)

        snap.data_complete = True
        return snap, trades_in_minute


# ---------------------------------------------------------------------------
# توابع کمکی
# ---------------------------------------------------------------------------

def save_snapshot_json(snapshot: MarketSnapshot, base_dir: Path):
    base_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{snapshot.symbol}_{snapshot.timestamp.replace(':', '-')}.json"
    path = base_dir / fname
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2, default=str)
    return path


def load_config(config_path: Path) -> Dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)
