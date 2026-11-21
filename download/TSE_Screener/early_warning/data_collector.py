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
from dataclasses import dataclass, field, asdict, fields, MISSING
from datetime import datetime, timedelta, date, timezone
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Any

from early_warning.market_detector import tehran_now

import requests

from .price_range import to_jalali


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
    interval_real_buy_value: float = 0.0
    interval_real_sell_value: float = 0.0
    interval_real_buy_count: int = 0
    interval_real_sell_count: int = 0
    # --- کیفیت دادهٔ حقیقی/حقوقی (پچ رفع تأخیر ClientType) ---
    # حجم/ارزش بازهٔ حقیقی اکنون در _classify_interval_real از معاملات (aggressor)
    # و interval_volume محاسبه می‌شود، نه از دلتای تجمعی ClientType.
    clienttype_stale: bool = False          # True اگر ClientType تأخیر داشته/پرش کرده
    clienttype_lag_shares: int = 0          # سهم معامله‌شده ولی هنوز طبقه‌بندی‌نشده
    interval_buy_volume: int = 0            # حجم خریدآغازگر واقعی در بازه (از trades)
    interval_sell_volume: int = 0           # حجم فروش‌آغازگر واقعی در بازه
    last_fresh_real_frac: float = 0.5       # نسبت حقیقی حمل‌شده از آخرین نمونهٔ تازه
    ask5_volume: float = 0.0   # مجموع حجم ۵ ردیف عرضه (محاسبه‌شده)
    bid5_volume: float = 0.0   # مجموع حجم ۵ ردیف تقاضا (محاسبه‌شده)

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

    @classmethod
    def from_flat_dict(cls, d: Dict) -> "MarketSnapshot":
        """بازسازی MarketSnapshot از دیکشنری flat (مثلاً یک ردیف از جدول snapshots).

        برعکس to_flat_dict: ستون‌های bid_price_1..5 / ask_price_1..5 را به
        buy_rows / sell_rows تبدیل می‌کند، missing_fields را از string به list،
        و data_complete را از 0/1 به bool.
        """
        buy_rows: List[BestLimitRow] = []
        sell_rows: List[BestLimitRow] = []
        for i in range(1, 6):
            bp = d.get(f"bid_price_{i}")
            bv = d.get(f"bid_volume_{i}")
            bc = d.get(f"bid_count_{i}")
            if bp is not None or bv is not None:
                buy_rows.append(BestLimitRow(
                    price=float(bp or 0), volume=int(bv or 0), order_count=int(bc or 0)))
            ap = d.get(f"ask_price_{i}")
            av = d.get(f"ask_volume_{i}")
            ac = d.get(f"ask_count_{i}")
            if ap is not None or av is not None:
                sell_rows.append(BestLimitRow(
                    price=float(ap or 0), volume=int(av or 0), order_count=int(ac or 0)))
        # missing_fields: string → list
        mf = d.get("missing_fields", "")
        if isinstance(mf, str) and mf.strip():
            missing_fields = [x.strip() for x in mf.split(",") if x.strip()]
        else:
            missing_fields = []
        # data_complete: 0/1 → bool
        dc = d.get("data_complete")
        data_complete = bool(dc) if dc is not None else True
        # فقط فیلدهای معتبر dataclass را از d بگیریم (ستون‌های اضافی DB مثل snapshot_id نادیده)
        # تبدیل None → پیش‌فرض فیلد: ستون‌های جدیدِ اضافه‌شده (ALTER TABLE) روی ردیف‌های
        # قدیمیِ DB مقدار NULL دارند؛ بدون این تبدیل، None به موتور می‌رسد و
        # «NoneType - NoneType» می‌شود.
        defaults: Dict = {}
        for f in fields(cls):
            if f.default is not MISSING:
                defaults[f.name] = f.default
            elif f.default_factory is not MISSING:  # لیست‌ها (buy_rows و …) جدا مدیریت می‌شوند
                defaults[f.name] = None
        valid = {f.name for f in fields(cls)}
        kwargs: Dict = {}
        for k, v in d.items():
            if k in valid:
                if v is None and defaults.get(k) is not None:
                    kwargs[k] = defaults[k]
                else:
                    kwargs[k] = v
        kwargs["buy_rows"] = buy_rows
        kwargs["sell_rows"] = sell_rows
        kwargs["missing_fields"] = missing_fields
        kwargs["data_complete"] = data_complete
        return cls(**kwargs)

    def validate_bid_ask_range(self) -> tuple:
        """
        بررسی اینکه آیا قیمت‌های bid/ask در رنج مجاز [min, max] هستند.

        بررسی می‌کند:
          - ask_price_1 تا ask_price_5 (sell_rows)
          - bid_price_1 تا bid_price_5 (buy_rows)

        فقط قیمت‌های غیرصفر بررسی می‌شوند (صفر = ردیف خالی).

        خروجی: (is_valid, out_of_range_list)
          is_valid: True اگر همه قیمت‌ها در رنج هستند
          out_of_range_list: لیست دیکشنری‌های {side, level, price} که خارج از رنج هستند
        """
        lo = self.min_allowed_price
        hi = self.max_allowed_price
        out_of_range = []

        # اگر کف/سقف محاسبه نشده، اعتبارسنجی معنا ندارد → معتبر
        if lo <= 0 or hi <= 0:
            return (True, [])

        # بررسی buy_rows (bid)
        for i, row in enumerate(self.buy_rows[:5], 1):
            if row.price and row.price > 0:
                if not (lo <= row.price <= hi):
                    out_of_range.append({
                        "side": "bid", "level": i,
                        "price": row.price, "min": lo, "max": hi,
                    })

        # بررسی sell_rows (ask)
        for i, row in enumerate(self.sell_rows[:5], 1):
            if row.price and row.price > 0:
                if not (lo <= row.price <= hi):
                    out_of_range.append({
                        "side": "ask", "level": i,
                        "price": row.price, "min": lo, "max": hi,
                    })

        return (len(out_of_range) == 0, out_of_range)


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

        # -----------------------------------------------------------------
        # نام کلیدهای واقعی API (تایید شده با پاسخ واقعی cdn.tsetmc.com):
        #   priceFirst / priceYesterday / priceMax / priceMin
        #   qTotTran5J (حجم کل) / qTotCap (ارزش کل) / zTotTran (تعداد)
        #   instrumentState.cEtavalTitle (وضعیت نماد)
        # نام‌های قدیمی pPriceFirst و ... در این API وجود ندارند و فقط به‌عنوان
        # fallback نگه‌داری شده‌اند. qBaseVol و pMinAllowed/pMaxAllowed هم در
        # این API نیستند (حجم مبنا از پیکربندی، بازه مجاز از دیروز محاسبه می‌شود).
        # -----------------------------------------------------------------
        cfg_sym = self.cfg.get("test_symbol", {}) if isinstance(self.cfg, dict) else {}
        state = info_data.get("instrumentState") or {}
        info = {
            # آخرین قیمت (آخرین معامله)
            "last_price": float(info_data.get("pDrCotVal") or 0),
            # قیمت پایانی (میانگین وزنی)
            "close_price": float(info_data.get("pClosing") or 0),
            # اولین قیمت روز (open price)
            "open_price": float(info_data.get("priceFirst") or info_data.get("pPriceFirst") or 0),
            # قیمت دیروز
            "yesterday_price": float(info_data.get("priceYesterday") or info_data.get("pPriceYesterday") or 0),
            # بیشترین قیمت روز
            "daily_high": float(info_data.get("priceMax") or info_data.get("pPriceMax") or 0),
            # کمترین قیمت روز
            "daily_low": float(info_data.get("priceMin") or info_data.get("pPriceMin") or 0),
            # حجم کل معاملات روز (سهم) - نام واقعی: qTotTran5J
            "trade_volume": int(float(info_data.get("qTotTran5J") or info_data.get("qTotTran") or 0)),
            # ارزش کل معاملات روز (ریال) - نام واقعی: qTotCap
            "trade_value": float(info_data.get("qTotCap") or info_data.get("qTotTranValJAdj") or 0),
            # تعداد معاملات روز - zTotTran
            "trade_count": int(float(info_data.get("zTotTran") or 0)),
            # حجم مبنا - در این API موجود نیست؛ از پیکربندی یا ۱۰۰٬۰۰۰
            "base_volume": int(float(info_data.get("qBaseVol") or cfg_sym.get("base_volume") or 100000)),
            # وضعیت نماد از instrumentState (مثلا «مجاز»)
            "symbol_status": str(state.get("cEtavalTitle") or "").strip(),
            "buy_rows": [],
            "sell_rows": [],
            "min_allowed": 0,
            "max_allowed": 0,
        }

        # کف و سقف مجاز روز - اگر fixed_price_range در پیکربندی باشد (توسط
        # run_live.py از tse_range_rules.json و yesterday_price محاسبه و تزریق
        # شده)، از همان مقادیر ثابت استفاده می‌کنیم؛ در غیر این صورت از
        # limit_percent پیکربندی به‌عنوان fallback.
        fixed_pr = cfg_sym.get("fixed_price_range")
        if fixed_pr and float(fixed_pr.get("min_allowed_price", 0)) > 0:
            info["min_allowed"] = float(fixed_pr["min_allowed_price"])
            info["max_allowed"] = float(fixed_pr["max_allowed_price"])
            # قیمت دیروز نیز ثابت (از daily_params)، نه از API زنده
            if float(fixed_pr.get("yesterday_price", 0)) > 0:
                info["yesterday_price"] = float(fixed_pr["yesterday_price"])
        else:
            limit_pct = float(cfg_sym.get("limit_percent", 10))
            low_factor = 1 - limit_pct / 100.0
            high_factor = 1 + limit_pct / 100.0
            if info["yesterday_price"] > 0:
                info["min_allowed"] = round(info["yesterday_price"] * low_factor, 0)
                info["max_allowed"] = round(info["yesterday_price"] * high_factor, 0)

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

        # min_allowed/max_allowed بالایی کافی است (یا از API یا محاسبه ۱۰٪)
        # این بخش قدیمی حذف شد

        return info

    def fetch_clienttype(self, ins_code: str) -> Optional[Dict]:
        """
        دریافت اطلاعات حقیقی/حقوقی از API جدید.

        نام فیلدهای صحیح (مشاهده شده در پاسخ):
          buy_I_Volume  = حجم خرید حقیقی (Individual)
          buy_N_Volume  = حجم خرید حقوقی (Non-individual)
          buy_CountI    = تعداد خریداران حقیقی
          buy_CountN    = تعداد خریداران حقوقی
          sell_I_Volume = حجم فروش حقیقی
          sell_N_Volume = حجم فروش حقوقی
          sell_CountI   = تعداد فروشندگان حقیقی
          sell_CountN   = تعداد فروشندگان حقوقی

        اگر نماد در GetClientType خالی بود، از GetClientTypeAll پیدا می‌شود.
        """
        # تلاش با چندین پارامتر مختلف
        ct_data = None
        for params in ["/1/0", "/0/0", "/2/0"]:
            data = self._api_get(f"ClientType/GetClientType/{ins_code}{params}")
            if data and isinstance(data, dict):
                ct_data = data.get("clientType") or data.get("ClientType")
                if isinstance(ct_data, dict):
                    break

        # اگر ct_data پیدا شد، بررسی کن آیا داده واقعی دارد (نه همه صفر)
        has_data = False
        if isinstance(ct_data, dict):
            has_data = any([
                ct_data.get("buy_I_Volume", 0) > 0,
                ct_data.get("buy_N_Volume", 0) > 0,
                ct_data.get("sell_I_Volume", 0) > 0,
                ct_data.get("sell_N_Volume", 0) > 0,
                ct_data.get("buy_CountI", 0) > 0,
                ct_data.get("buy_CountN", 0) > 0,
                ct_data.get("sell_CountI", 0) > 0,
                ct_data.get("sell_CountN", 0) > 0,
            ])

        # اگر داده‌ای نبود، از GetClientTypeAll استفاده کن
        if not has_data:
            if self.debug_mode:
                print(f"  [!] GetClientType خالی، جستجو در GetClientTypeAll...")
            ct_data_all = self._api_get("ClientType/GetClientTypeAll")
            if ct_data_all and isinstance(ct_data_all, dict):
                all_list = ct_data_all.get("clientTypeAllDto", [])
                for item in all_list:
                    if str(item.get("insCode", "")) == str(ins_code):
                        ct_data = item
                        has_data = True
                        if self.debug_mode:
                            print(f"  ✓ نماد در GetClientTypeAll پیدا شد")
                        break

        if not isinstance(ct_data, dict):
            return None

        # استخراج با نام فیلدهای صحیح
        def get_int(ct, *names):
            for n in names:
                if n in ct and ct[n] is not None:
                    try:
                        return int(float(ct[n]))
                    except (ValueError, TypeError):
                        continue
            return 0

        result = {
            # حقیقی = Individual (I)
            "real_buy_count":   get_int(ct_data, "buy_CountI"),
            "real_sell_count":  get_int(ct_data, "sell_CountI"),
            "real_buy_volume":  get_int(ct_data, "buy_I_Volume"),
            "real_sell_volume": get_int(ct_data, "sell_I_Volume"),
            # حقوقی = Non-individual (N)
            "legal_buy_count":  get_int(ct_data, "buy_CountN"),
            "legal_sell_count": get_int(ct_data, "sell_CountN"),
            "legal_buy_volume": get_int(ct_data, "buy_N_Volume"),
            "legal_sell_volume": get_int(ct_data, "sell_N_Volume"),
        }

        # محاسبه ارزش‌ها (حجم × قیمت پایانی)
        # این کار در _compute_derived انجام می‌شود

        return result

    # -----------------------------------------------------------------
    # دریافت اطلاعات سازمت (شامل ISIN) از API جدید
    # -----------------------------------------------------------------

    def fetch_instrument_info(self, ins_code: str) -> Optional[Dict]:
        """
        دریافت اطلاعات سازمت از Instrument/GetInstrumentInfo/{InsCode}.

        این endpoint فیلدهایی مثل cIsin (کد ISIN)، lVal18AFC (نماد) و
        lVal30 (نام کامل) را برمی‌گرداند.
        """
        data = self._api_get(f"Instrument/GetInstrumentInfo/{ins_code}")
        if not data or not isinstance(data, dict):
            return None
        info = data.get("instrumentInfo") or data.get("InstrumentInfo")
        if isinstance(info, list) and info:
            info = info[0]
        if not isinstance(info, dict):
            # گاهی کل پاسخ خود instrumentInfo است
            if "cIsin" in data or "cISIN" in data:
                info = data
            else:
                return None
        return info

    def fetch_isin(self, ins_code: str) -> Optional[str]:
        """
        دریافت کد ISIN نماد از API.

        مثال: ins_code=17914401175772326 → ISIN="IRO7TSEF0121"
        پیشوند ISIN (مثل IRO7) دسته نماد را مشخص می‌کند.
        """
        info = self.fetch_instrument_info(ins_code)
        if not info:
            return None
        isin = info.get("cIsin") or info.get("cISIN") or info.get("isin")
        if isin:
            return str(isin).strip().upper()
        return None

    def fetch_trades(self, ins_code: str) -> List[Trade]:
        """دریافت لیست معاملات امروز از API جدید TSETMC.

        Endpoint: Trade/GetTradeList/{insCode}/{dateYYYYMMDD}
          date = تاریخ میلادی امروز به‌صورت فشرده (مثل 20261121).
          (تاریخ میلادی، نه شمسی — dEven در API TSETMC میلادی است.)
        پاسخ: {"tradeList": [...]} که هر مورد شامل:
          pTran (قیمت)، qTitMeTran (حجم)، hEven (ساعت به‌صورت int HHMMSS)،
          nSBN (شماره سفارش خرید)، nSSN (شماره سفارش فروش)، dEven (تاریخ).

        aggressor_side در این متد None گذاشته می‌شود (TSETMC مستقیماً اعلام
        نمی‌کند) و در collect() با مقایسهٔ قیمت معامله با best_bid/best_ask
        استنتاج می‌شود.

        اگر endpoint در دسترس نباشد (مثلاً IP غیرایرانی بلاک یا 502) یا داده‌ای
        نبود، لیست خالی برمی‌گردد (سازگار با رفتار قبلی؛ موتورها به fallback
        دلتای تجمعی ClientType برمی‌شوند).
        """
        greg_today = date.today().strftime("%Y%m%d")  # 20261121
        data = self._api_get(f"Trade/GetTradeList/{ins_code}/{greg_today}")
        if not data or not isinstance(data, dict):
            return []
        trade_list = (data.get("tradeList") or data.get("TradeList") or [])
        if not isinstance(trade_list, list):
            return []

        def _fmt_time(h):
            """تبدیل hEven (int HHMMSS مثل 91500 یا 9155) به 'HH:MM:SS'."""
            try:
                s = str(int(h)).zfill(6)
                return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"
            except (ValueError, TypeError):
                return ""

        def _get(row, *names):
            for n in names:
                if n in row and row[n] is not None:
                    return row[n]
            return None

        trades: List[Trade] = []
        for row in trade_list:
            if not isinstance(row, dict):
                continue
            try:
                price = float(_get(row, "pTran") or 0)
                vol = int(float(_get(row, "qTitMeTran") or 0))
            except (ValueError, TypeError):
                continue
            if price <= 0 or vol <= 0:
                continue
            n_sbn = _get(row, "nSBN")
            n_ssn = _get(row, "nSSN")
            trades.append(Trade(
                trade_time=_fmt_time(_get(row, "hEven")),
                trade_price=price,
                trade_volume=vol,
                trade_id=f"{n_sbn}/{n_ssn}" if (n_sbn or n_ssn) else None,
                aggressor_side=None,
            ))
        # مرتب بر اساس زمان صعودی
        trades.sort(key=lambda t: str(t.trade_time or ""))
        return trades

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
        # فیلتر معاملات جدید: فقط معاملاتی که بعد از snapshot قبلی‌اند.
        # این از درج duplicate در trades table جلوگیری می‌کند (هر معامله یک‌بار).
        if fetch_trades and prev_snap is not None and trades:
            prev_t = str(prev_snap.tehran_time or "")
            trades = [t for t in trades if str(t.trade_time or "") > prev_t]

        # اگر هیچ داده‌ای دریافت نشد
        if not inst or (inst.get("last_price", 0) == 0 and inst.get("close_price", 0) == 0):
            # ساخت یک نمونه خالی ولی با اطلاعات زمانی
            now = tehran_now()  # زمان تهران (UTC+3:30)
            cfg_sym_err = self.cfg.get("test_symbol", {}) if isinstance(self.cfg, dict) else {}
            fixed_pr_err = cfg_sym_err.get("fixed_price_range")
            if fixed_pr_err and float(fixed_pr_err.get("yesterday_price", 0)) > 0:
                yp = float(fixed_pr_err["yesterday_price"])
                min_a = float(fixed_pr_err["min_allowed_price"])
                max_a = float(fixed_pr_err["max_allowed_price"])
            else:
                yp = cfg_sym_err.get("base_price", 13000)
                min_a = yp * 0.95
                max_a = yp * 1.05
            snap = MarketSnapshot(
                timestamp=now.isoformat(),
                tehran_time=now.strftime("%H:%M:%S"),
                date_jalali=to_jalali(date.today()),
                symbol=symbol,
                ins_code=ins_code,
                market_phase=self._detect_market_phase(),
                data_status="error",
                fetch_error="داده از TSETMC دریافت نشد - بررسی اتصال یا کد نماد",
                yesterday_price=yp,
                min_allowed_price=min_a,
                max_allowed_price=max_a,
            )
            return snap, []

        # ساخت نمونه
        now = tehran_now()  # زمان تهران (UTC+3:30)
        cfg_sym = self.cfg.get("test_symbol", {}) if isinstance(self.cfg, dict) else {}
        fixed_pr = cfg_sym.get("fixed_price_range")
        # yesterday_price: اگر fixed_price_range موجود است، ثابت از آن؛
        # در غیر این صورت از داده زنده API یا base_price پیکربندی.
        if fixed_pr and float(fixed_pr.get("yesterday_price", 0)) > 0:
            yesterday_price = float(fixed_pr["yesterday_price"])
        else:
            yesterday_price = inst.get("yesterday_price") or cfg_sym.get("base_price", 13000)
        # min/max_allowed: اولویت با inst (که fetch_intraday تنظیم کرده)؛
        # در غیر این صورت از fixed_price_range یا محاسبه با limit_percent.
        min_allowed = inst.get("min_allowed", 0)
        max_allowed = inst.get("max_allowed", 0)
        if min_allowed == 0:
            if fixed_pr and float(fixed_pr.get("min_allowed_price", 0)) > 0:
                min_allowed = float(fixed_pr["min_allowed_price"])
            elif yesterday_price > 0:
                limit_pct = float(cfg_sym.get("limit_percent", 10))
                min_allowed = round(yesterday_price * (1 - limit_pct / 100.0), 0)
        if max_allowed == 0:
            if fixed_pr and float(fixed_pr.get("max_allowed_price", 0)) > 0:
                max_allowed = float(fixed_pr["max_allowed_price"])
            elif yesterday_price > 0:
                limit_pct = float(cfg_sym.get("limit_percent", 10))
                max_allowed = round(yesterday_price * (1 + limit_pct / 100.0), 0)
        snap = MarketSnapshot(
            timestamp=now.isoformat(),
            tehran_time=now.strftime("%H:%M:%S"),
            date_jalali=to_jalali(date.today()),
            symbol=symbol,
            ins_code=ins_code,
            market_phase=self._detect_market_phase(),
            symbol_status=inst.get("symbol_status") or "allowed",
            source_update_time=now.isoformat(),
            data_status="ok" if inst.get("last_price", 0) > 0 else "partial",
            # last_price: اولویت با pDrCotVal؛ اگر صفر بود (pre_open/stale)
            # به close_price (پایانی = close دیروز) و سپس yesterday_price برگرد.
            last_price=inst.get("last_price") or inst.get("close_price") or yesterday_price,
            close_price=inst.get("close_price") or yesterday_price,
            # open_price: اولین قیمت روز؛ اگر priceFirst صفر بود (pre_open قبل
            # از اولین معامله، یا پاسخ stale-cache از لحظهٔ pre_open) به
            # yesterday_price برگرد. قبلاً از inst.get("open_price", yesterday_price)
            # استفاده می‌شد که چون fetch_intraday همیشه کلید را ست می‌کند (حتی صفر)،
            # هرگز به yesterday_price نمی‌رسید → open_price=0 ذخیره می‌شد.
            open_price=inst.get("open_price") or yesterday_price,
            yesterday_price=yesterday_price,
            daily_high=inst.get("daily_high", 0),
            daily_low=inst.get("daily_low", 0),
            min_allowed_price=min_allowed,
            max_allowed_price=max_allowed,
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
        # تشخیص پاسخ stale-cache از CDN: اگر حجم/تعداد معاملات تجمعی و آخرین
        # قیمت دقیقاً با snapshot قبلی یکسان باشد، یعنی CDN پاسخ cacheشده (تکراری)
        # برگردانده و دادهٔ جدیدی نیست. این ردیف‌ها علامت‌گذاری می‌شوند تا
        # داشبورد/آنالیز بتواند آن‌ها را فیلتر کند (WHERE data_status != 'stale').
        # توجه: فقط در فاز پیوسته معنادار است؛ در pre_open همهٔ نمونه‌ها یکسان‌اند
        # و stale بودنشان طبیعی است.
        if prev_snap is not None and snap.market_phase == MarketPhase.CONTINUOUS.value:
            if (snap.total_volume == prev_snap.total_volume and
                    snap.total_trade_count == prev_snap.total_trade_count and
                    snap.last_price == prev_snap.last_price and
                    snap.total_volume > 0):
                snap.data_status = "stale"
        # بانک اصلی فقط دادهٔ خام را ذخیره می‌کند (آنچه از TSE دریافت می‌شود).
        # محاسبات مشتق (interval_real_*، per_capita، real_money_flow،
        # data_complete، …) در لایهٔ جداگانهٔ derived_compute و فقط در حافظه
        # انجام می‌شوند — بدون نوشتن در بانک اصلی.
        # استنتاج طرف آغازگر (aggressor) معامله: TSETMC در لیست معاملات اعلام
        # نمی‌کند؛ با مقایسهٔ قیمت معامله با best_bid/best_ask تخمین می‌زنیم:
        #   قیمت >= best_ask → خریدار آغازگر (buy)   (ask را برداشته)
        #   قیمت <= best_bid  → فروشنده آغازگر (sell) (bid را زد)
        if trades:
            bb = snap.best_buy_price or 0
            ba = snap.best_sell_price or 0
            for t in trades:
                if ba > 0 and t.trade_price >= ba:
                    t.aggressor_side = "buy"
                elif bb > 0 and t.trade_price <= bb:
                    t.aggressor_side = "sell"
                else:
                    t.aggressor_side = None
        return snap, trades

    def _detect_market_phase(self) -> str:
        """تشخیص فاز بازار بر اساس زمان تهران."""
        now = tehran_now()  # زمان تهران (UTC+3:30)
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

    @staticmethod
    def _classify_interval_real(snap, prev_snap, trades):
        """محاسبهٔ حجم/ارزش فشار حقیقی در بازه با تشخیص تأخیر ClientType.

        اولویت داده‌ها (از قابل‌اعتماد به کم‌اعتماد):
          ۱) interval_volume و معاملات (aggressor side) — هر دو لحظه‌ای از TSETMC.
          ۲) دلتای تجمعی ClientType — فقط اگر تازه باشد.
        در هر حالت، خروجی در بازهٔ interval_volume مهار می‌شود تا پرش جبرانی نباشد
        (مثل ۳۴٬۰۰۰ در برابر ۵۲۸). money_flow به‌صورت بازه‌ای از ارزش واقعی معاملات
        محاسبه می‌شود، نه از حجم تجمعی × قیمت پایانی.
        """
        d_total = max(0, snap.total_volume - prev_snap.total_volume)
        d_trade_count = max(0, snap.total_trade_count - prev_snap.total_trade_count)
        d_rbv = snap.real_buy_volume - prev_snap.real_buy_volume
        d_rsv = snap.real_sell_volume - prev_snap.real_sell_volume
        d_rbc = snap.real_buy_count - prev_snap.real_buy_count
        d_rsc = snap.real_sell_count - prev_snap.real_sell_count
        classified = max(0, d_rbv) + max(0, d_rsv)

        # --- تشخیص تأخیر/پرش ClientType ---
        frozen = (snap.real_buy_volume == prev_snap.real_buy_volume and
                  snap.real_sell_volume == prev_snap.real_sell_volume and d_total > 0)
        backward = (d_rbv < 0 or d_rsv < 0)
        spike = (d_total > 0 and classified > d_total * 1.2)         # پرش جبرانی > حجم واقعی
        coverage = ((snap.real_buy_volume + snap.real_sell_volume +
                     snap.legal_buy_volume + snap.legal_sell_volume) /
                    max(snap.total_volume, 1))
        lagged = coverage < 0.95                                     # بخشی هنوز طبقه‌بندی‌نشده

        snap.clienttype_stale = bool(frozen or backward or spike or lagged)
        snap.clienttype_lag_shares = max(
            0, snap.total_volume - (snap.real_buy_volume + snap.legal_buy_volume))

        # --- حجم واقعی خرید/فروش در بازه از روی معاملات (قابل‌اعتماد، لحظه‌ای) ---
        t0, t1 = str(prev_snap.tehran_time), str(snap.tehran_time)

        def _in_win(t):
            ts = str(t)
            return t0 <= ts <= t1

        iv_buy = sum(t.trade_volume for t in trades
                     if getattr(t, "aggressor_side", None) == "buy" and _in_win(getattr(t, "trade_time", "")))
        iv_sell = sum(t.trade_volume for t in trades
                      if getattr(t, "aggressor_side", None) == "sell" and _in_win(getattr(t, "trade_time", "")))
        vb = sum(t.trade_price * t.trade_volume for t in trades
                 if getattr(t, "aggressor_side", None) == "buy" and _in_win(getattr(t, "trade_time", "")))
        vs = sum(t.trade_price * t.trade_volume for t in trades
                 if getattr(t, "aggressor_side", None) == "sell" and _in_win(getattr(t, "trade_time", "")))
        snap.interval_buy_volume = iv_buy
        snap.interval_sell_volume = iv_sell

        # اگر در بازه معامله‌ای نداشتیم، نصف d_total به هر سمت (خنثی)
        base_buy = iv_buy if (iv_buy + iv_sell) > 0 else d_total / 2.0
        base_sell = iv_sell if (iv_buy + iv_sell) > 0 else d_total / 2.0

        # نسبت حقیقی: از نمونهٔ فعلی اگر تازه، وگرنه حمل‌شده
        rb = snap.real_buy_volume + snap.real_sell_volume
        lb = snap.legal_buy_volume + snap.legal_sell_volume
        if (rb + lb) > 0:
            frac_real = rb / (rb + lb)
            if not snap.clienttype_stale:
                snap.last_fresh_real_frac = frac_real
        else:
            frac_real = snap.last_fresh_real_frac
        if snap.clienttype_stale:
            frac_real = snap.last_fresh_real_frac

        # --- حجم حقیقی بازه (مهار در d_total) ---
        snap.interval_real_buy_volume = round(base_buy * frac_real)
        snap.interval_real_sell_volume = round(base_sell * frac_real)
        tot = snap.interval_real_buy_volume + snap.interval_real_sell_volume
        if d_total > 0 and tot > d_total:
            f = d_total / tot
            snap.interval_real_buy_volume = round(snap.interval_real_buy_volume * f)
            snap.interval_real_sell_volume = round(snap.interval_real_sell_volume * f)

        # --- تعداد حقیقی بازه: دلتای تجمعی مهارشده در d_trade_count (یا توزیع بر frac_real) ---
        nb_raw = max(0, d_rbc)
        ns_raw = max(0, d_rsc)
        if (nb_raw + ns_raw) > d_trade_count and d_trade_count > 0:
            # پرش تعداد هم مهار می‌شود
            f = d_trade_count / (nb_raw + ns_raw)
            nb_raw, ns_raw = round(nb_raw * f), round(ns_raw * f)
        if snap.clienttype_stale and d_trade_count > 0 and (nb_raw + ns_raw) == 0:
            nb_raw = round(d_trade_count * frac_real)
            ns_raw = round(d_trade_count * (1 - frac_real))
        snap.interval_real_buy_count = nb_raw
        snap.interval_real_sell_count = ns_raw

        # --- ارزش و money_flow از ارزش واقعی معاملات (نه proxy حجم×قیمت پایانی) ---
        px = snap.close_price or snap.last_price or 0
        snap.interval_real_buy_value = round(vb * frac_real, 0) if vb else snap.interval_real_buy_volume * px
        snap.interval_real_sell_value = round(vs * frac_real, 0) if vs else snap.interval_real_sell_volume * px
        # money_flow به‌صورت بازه‌ای (ورود/خروج پول حقیقی در همین لحظه) — معنادارتر برای موتور
        snap.real_money_flow = snap.interval_real_buy_value - snap.interval_real_sell_value
        snap.real_money_flow_ratio = snap.real_money_flow / max(snap.interval_value, 1.0)

    @staticmethod
    def _compute_derived(s: MarketSnapshot):
        """محاسبه شاخص‌های مشتق.

        real_buy_value/real_sell_value تجمعیِ تقریبی (volume×avg_price) برای نمایش و
        ذخیره باقی می‌ماند. real_money_flow و real_money_flow_ratio اکنون در
        _classify_interval_real از ارزش واقعی معاملاتِ بازه محاسبه می‌شوند
        (در این‌جا بازنویسی نمی‌شوند).
        """
        s.per_capita_buy_real = s.real_buy_volume / max(s.real_buy_count, 1)
        s.per_capita_sell_real = s.real_sell_volume / max(s.real_sell_count, 1)
        s.buyer_power = s.per_capita_buy_real / max(s.per_capita_sell_real, 1e-9)
        avg_price = s.close_price if s.close_price > 0 else s.last_price
        s.real_buy_value = s.real_buy_volume * avg_price
        s.real_sell_value = s.real_sell_volume * avg_price
        s.legal_buy_value = s.legal_buy_volume * avg_price
        s.legal_sell_value = s.legal_sell_volume * avg_price

    @staticmethod
    def _mark_completeness(s: MarketSnapshot):
        """علامت‌گذاری فیلدهای مفقود."""
        missing = []
        if s.last_price <= 0: missing.append("last_price")
        if s.close_price <= 0: missing.append("close_price")
        if s.daily_high <= 0: missing.append("daily_high")
        if s.daily_low <= 0: missing.append("daily_low")
        if s.total_volume <= 0: missing.append("total_volume")
        if s.total_value <= 0: missing.append("total_value")
        if not s.buy_rows: missing.append("buy_rows")
        if not s.sell_rows: missing.append("sell_rows")
        if s.real_buy_count == 0 and s.real_sell_count == 0:
            missing.append("clienttype")
        elif s.clienttype_stale:
            missing.append("clienttype_stale")   # داده هست ولی تأخیر دارد → تخمینی
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
      - 'normal':          روز عادی با نوسان ملایم
      - 'sell_pressure':   فشار فروش تدریجی منتهی به صف فروش
      - 'accumulation':    جمع‌آوری پنهان در روز منفی
      - 'mixed':           ترکیب فشار فروش و جمع‌آوری هم‌زمان
      - 'ladder_collapse': تخلیه خاموش نردبان خرید (صف فروش در حال
        شکل‌گیری) - برای نمایش بعد سوم: عمق نردبان آب می‌رود ولی تاچ
        رفرش می‌شود؛ موتورهای لحظه‌ای دیر واکنش می‌دهند ولی شاخص‌های
        سرعتی کل نردبان را می‌بینند و هشدار زرد را به قرمز ارتقا می‌دهند

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
            elif self.scenario == "ladder_collapse":
                # افت زودهنگام و سپس رکود: قیمت زود به کف روز می‌چسبد
                # تا «نزدیکی به کف» در موتور فشار فروش از میانه روز فعال شود
                last = self.base_price * (
                    1 - 0.018 * min(1.0, 3.0 * adj_progress)
                    - 0.002 * adj_progress
                    + self.rng.gauss(0, 0.002)
                )
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
            elif self.scenario == "ladder_collapse":
                # پایانی کمی بالاتر از آخرین: گپ منفی کوچک (نشانه ضعف ملایم)
                close = max(close, last * 1.002)

            if st["open_price"] == self.base_price and adjusted_idx == 0:
                st["open_price"] = last

        st["high"] = max(st["high"], last, close)
        st["low"] = min(st["low"], last, close)

        min_allowed = round(self.base_price * 0.95, 2)
        max_allowed = round(self.base_price * 1.05, 2)

        best_buy_price = int(last * 0.998)
        best_sell_price = int(last * 1.002)

        if is_pre_open:
            if self.scenario == "ladder_collapse":
                # حجم پیش‌گشایش هم‌سطح پیوسته تا جهش کاذب نردبان در گشایش رخ ندهد
                base_buy_vol = int(40000 * (1 + 0.05 * self.rng.gauss(0, 1)))
                base_sell_vol = int(34000 * (1 + 0.05 * self.rng.gauss(0, 1)))
            else:
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
        elif self.scenario == "ladder_collapse":
            # نردبان‌ها در طول روز تقریباً ثابت‌اند؛ پویایی در فاز تخلیه است
            base_buy_vol = int(40000 * (1 + 0.05 * self.rng.gauss(0, 1)))
            base_sell_vol = int(34000 * (1 + 0.05 * self.rng.gauss(0, 1)))
        else:
            base_buy_vol = int(50000 * (1 + 0.05 * self.rng.gauss(0, 1)))
            base_sell_vol = int(45000 * (1 + 0.05 * self.rng.gauss(0, 1)))

        # فاز پایانی سناریوها (ده نمونه آخر) - ضریب هر ردیف نردبان:
        # sell_pressure: صف فروش - کل نردبان خرید تخلیه و کل نردبان فروش
        #   موج عظیم می‌شود (رفتار ریزش آشکار)
        # ladder_collapse: تخلیه خاموش - عمق نردبان خرید آب می‌رود ولی تاچ
        #   (ردیف اول) با سفارش‌های جدید تا حدی refresh می‌شود؛ در سمت
        #   فروش، عرضه در عمق انباشته می‌شود ولی تاچ فروش ملایم رشد می‌کند.
        #   نتیجه: فاکتورهای «بهترین ردیف» موتور فشار فروش دیر واکنش
        #   نشان می‌دهند ولی شاخص‌های سرعتی (کل نردبان) فوراً وضعیت را
        #   می‌بینند - همان لبه اطلاعاتی بعد سوم.
        row_factor_buy = [1.0] * 5
        row_factor_sell = [1.0] * 5
        if not is_pre_open and adj_progress >= 0.95:
            c = (adj_progress - 0.95) / 0.05  # ۰ → ۱ در ده نمونه پایانی
            if self.scenario == "sell_pressure":
                for k in range(5):
                    row_factor_buy[k] = 1.0 - 0.94 * c
                    row_factor_sell[k] = 1.0 + 5.0 * c
            elif self.scenario == "ladder_collapse":
                for k in range(5):
                    row_factor_buy[k] = (
                        (0.60 + 0.40 * (1.0 - 0.93 * c)) if k == 0
                        else (1.0 - 0.93 * c)
                    )
                    row_factor_sell[k] = 1.0 + (0.4 if k == 0 else 2.6) * c

        buy_rows = []
        # نویز ردیف‌ها در سناریوی تخلیه خاموش کمتر است تا امتیاز فشار فروش
        # در باند زرد بماند و اثر فاز تخلیه بر شاخص‌های سرعتی تمیز دیده شود
        row_noise = 0.04 if self.scenario == "ladder_collapse" else 0.1
        for k in range(5):
            buy_rows.append(BestLimitRow(
                price=best_buy_price - k * 10,
                volume=max(100, int(base_buy_vol * row_factor_buy[k]
                                    * (1 - 0.15 * k) * (1 + self.rng.gauss(0, row_noise)))),
                order_count=max(1, int(20 * (1 - 0.1 * k) + self.rng.gauss(0, 3))),
            ))
        sell_rows = []
        for k in range(5):
            sell_rows.append(BestLimitRow(
                price=best_sell_price + k * 10,
                volume=max(100, int(base_sell_vol * row_factor_sell[k]
                                    * (1 - 0.15 * k) * (1 + self.rng.gauss(0, row_noise)))),
                order_count=max(1, int(20 * (1 - 0.1 * k) + self.rng.gauss(0, 3))),
            ))

        trades_in_minute: List[Trade] = []
        if not is_pre_open:
            num_trades = int(self.rng.uniform(20, 60))
            # در فاز پایانیِ ریزش/تخلیه نقدشوندگی تقریباً خشک می‌شود:
            # تعداد و حجم معامله‌ها به‌شدت افت می‌کند (نکته کلیدی:
            # عرضه جدید روی نردبان می‌ماند و جذب نمی‌شود)
            collapse_c = 0.0
            if (self.scenario in ("sell_pressure", "ladder_collapse")
                    and adj_progress >= 0.95):
                collapse_c = (adj_progress - 0.95) / 0.05
                num_trades = max(1, int(num_trades * (1.0 - 0.97 * collapse_c)))
            for _ in range(num_trades):
                st["trade_seq"] += 1
                t_price = last * (1 + self.rng.gauss(0, 0.001))
                t_vol = int(self.rng.uniform(500, 5000) * (1.0 - 0.95 * collapse_c))
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
        elif self.scenario == "ladder_collapse":
            # تعداد خریدار/فروشنده متقارن و سهم‌ها نزدیک هم: جریان پول
            # فقط خروج ملایم نشان می‌دهد و فشار فروش در باند زرد می‌ماند
            # (در پیش‌گشایش این سهم‌ها بعداً صفر می‌شوند؛ progress همیشه تعریف شده)
            end_buy_count = 3000
            end_sell_count = 3000
            real_buy_share = 0.34 - 0.02 * progress
            real_sell_share = 0.395 - 0.012 * progress
            legal_buy_share = 0.04
            legal_sell_share = 0.04
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
            # ارزش/تعداد حقیقیِ بازه (از دادهٔ دقیقِ sim، نه دلتای تجمعی)
            snap.interval_real_buy_value = real_buy_vol * snap.close_price
            snap.interval_real_sell_value = real_sell_vol * snap.close_price
            snap.interval_real_buy_count = new_buyers
            snap.interval_real_sell_count = new_sellers
            snap.interval_buy_volume = sum(t.trade_volume for t in trades_in_minute
                                           if t.aggressor_side == "buy")
            snap.interval_sell_volume = sum(t.trade_volume for t in trades_in_minute
                                            if t.aggressor_side == "sell")
            snap.clienttype_stale = False   # دادهٔ sim تأخیر ندارد
            snap.clienttype_lag_shares = 0

        snap.per_capita_buy_real = snap.real_buy_volume / max(snap.real_buy_count, 1)
        snap.per_capita_sell_real = snap.real_sell_volume / max(snap.real_sell_count, 1)
        snap.buyer_power = snap.per_capita_buy_real / max(snap.per_capita_sell_real, 1e-9)
        # ارزش تجمعیِ تقریبی (برای نمایش/ذخیره)
        snap.real_buy_value = snap.real_buy_volume * snap.close_price
        snap.real_sell_value = snap.real_sell_volume * snap.close_price
        snap.legal_buy_value = snap.legal_buy_volume * snap.close_price
        snap.legal_sell_value = snap.legal_sell_volume * snap.close_price
        # money_flow بازه‌ای (ورود/خروج پول حقیقی در همین دقیقه) — معنادار برای موتور
        snap.real_money_flow = snap.interval_real_buy_value - snap.interval_real_sell_value
        snap.real_money_flow_ratio = snap.real_money_flow / max(snap.interval_value, 1e-9)

        st["money_flow_history"].append(snap.real_money_flow)
        st["buyer_power_history"].append(snap.buyer_power)
        st["prev_best_buy_volume"] = snap.best_buy_volume
        st["prev_best_sell_volume"] = snap.best_sell_volume
        st["price_path"].append(last)

        snap.data_complete = True
        snap._enriched = True  # شبیه‌ساز: snapshot از پیش مشتق‌شده → enrich در _publish رد می‌شود
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
