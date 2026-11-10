"""
data_collector.py
دریافت‌کننده داده‌های تابلو از TSETMC و حالت شبیه‌سازی

دو کلاس اصلی:
  - MarketDataCollector: دریافت واقعی از TSETMC (Windows 10 + requests)
  - SimulationDataCollector: شبیه‌سازی داده برای تست آفلاین موتورها

ساختار MarketSnapshot شامل تمام فیلدهای شش گروه است:
  گروه A - قیمت و وضعیت پایه
  گروه B - پنج ردیف سفارش خرید و فروش
  گروه C - حجم/ارزش/تعداد معاملات تجمعی
  گروه D - اطلاعات حقیقی/حقوقی
  گروه E - معاملات انجام‌شده (به‌صورت جداگانه در Trade)
  گروه F - وضعیت بازار و کیفیت داده
"""

from __future__ import annotations

import json
import random
import time
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests


# ---------------------------------------------------------------------------
# مدل داده - یک نمونه کامل از تابلو در یک لحظه زمانی
# ---------------------------------------------------------------------------

class MarketPhase(Enum):
    """گروه F - فاز بازار."""
    PRE_OPEN = "pre_open"             # پیش‌گشایش (۰۸:۴۵ تا ۰۹:۰۰)
    OPENING_AUCTION = "opening_auction"  # حراج آغازین
    CONTINUOUS = "continuous"          # معاملات پیوسته
    HALTED = "halted"                  # توقف موقت
    SYMBOL_SUSPENDED = "suspended"     # نماد ممنوع/متوقف
    CLOSED = "closed"                 # پایان بازار


@dataclass
class BestLimitRow:
    """یک ردیف از پنج ردیف اول سفارش خرید یا فروش."""
    price: int = 0
    volume: int = 0
    order_count: int = 0


@dataclass
class Trade:
    """گروه E - یک معامله انجام‌شده."""
    trade_time: str           # HH:MM:SS یا ISO
    trade_price: float
    trade_volume: int
    trade_id: Optional[str] = None      # شناسه یکتا اگر موجود باشد
    aggressor_side: Optional[str] = None  # 'buy'/'sell' یا None (نامشخص)


@dataclass
class MarketSnapshot:
    """یک تصویر کامل از تابلو در یک لحظه - شامل تمام شش گروه فیلد."""

    # ===== گروه F - وضعیت بازار و شناسه =====
    snapshot_id: Optional[int] = None   # شناسه یکتا در DB
    date_jalali: str = ""               # تاریخ شمسی
    timestamp: str = ""                 # ISO format
    tehran_time: str = ""               # HH:MM:SS
    symbol: str = ""
    ins_code: str = ""
    market_phase: str = "continuous"    # MarketPhase value
    symbol_status: str = "allowed"      # allowed/suspended/halted
    source_update_time: str = ""       # آخرین به‌روزرسانی منبع
    data_status: str = "ok"            # ok/missing/partial/error
    fetch_error: str = ""              # توضیح خطا در صورت وجود

    # ===== گروه A - قیمت‌ها =====
    last_price: float = 0.0
    close_price: float = 0.0           # قیمت پایانی
    open_price: float = 0.0            # اولین قیمت روز
    yesterday_price: float = 0.0       # قیمت دیروز (پایه)
    daily_high: float = 0.0
    daily_low: float = 0.0
    min_allowed_price: float = 0.0     # کف مجاز روز
    max_allowed_price: float = 0.0     # سقف مجاز روز

    # ===== گروه B - پنج ردیف سفارش =====
    # بهترین قیمت‌ها (برای راحتی دسترسی)
    best_buy_price: float = 0.0
    best_buy_volume: int = 0
    best_sell_price: float = 0.0
    best_sell_volume: int = 0
    # پنج ردیف کامل
    buy_rows: List[BestLimitRow] = field(default_factory=list)
    sell_rows: List[BestLimitRow] = field(default_factory=list)
    # مجموع تعداد سفارش‌های خرید و فروش (پنج ردیف)
    buy_order_count: int = 0
    sell_order_count: int = 0

    # ===== گروه C - حجم/ارزش/تعداد معاملات تجمعی =====
    total_volume: int = 0              # حجم کل معاملات روز
    total_value: float = 0.0          # ارزش کل معاملات روز
    total_trade_count: int = 0        # تعداد کل معاملات روز
    base_volume: int = 0              # حجم مبنا
    # مقادیر بازه‌ای (محاسبه از تفاضل نمونه‌ها اگر منبع ندهد)
    interval_volume: int = 0          # حجم این ۶۰ ثانیه
    interval_value: float = 0.0        # ارزش این ۶۰ ثانیه
    interval_trade_count: int = 0     # تعداد معامله این ۶۰ ثانیه

    # ===== گروه D - اطلاعات حقیقی/حقوقی (تجمعی روزانه) =====
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

    # ===== شاخص‌های مشتق (محاسبه در collector، نه در موتور) =====
    buyer_power: float = 0.0
    per_capita_buy_real: float = 0.0
    per_capita_sell_real: float = 0.0
    real_money_flow: float = 0.0
    real_money_flow_ratio: float = 0.0
    # مقادیر بازه‌ای حقیقی (محاسبه از تفاضل)
    interval_real_buy_volume: int = 0
    interval_real_sell_volume: int = 0

    # ===== کیفیت داده =====
    data_complete: bool = True
    missing_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
        return d

    def to_flat_dict(self) -> Dict:
        """نسخه مسطح برای ذخیره در SQLite/CSV (پنج ردیف به‌صورت ستون‌های جداگانه)."""
        d = {}
        # همه فیلدها به جز buy_rows/sell_rows (که لیست هستند)
        for k, v in asdict(self).items():
            if k not in ("buy_rows", "sell_rows", "missing_fields"):
                d[k] = v
        # ستون‌های پنج ردیف خرید
        for i, row in enumerate(self.buy_rows[:5], 1):
            d[f"bid_price_{i}"] = row.price
            d[f"bid_volume_{i}"] = row.volume
            d[f"bid_count_{i}"] = row.order_count
        # ستون‌های پنج ردیف فروش
        for i, row in enumerate(self.sell_rows[:5], 1):
            d[f"ask_price_{i}"] = row.price
            d[f"ask_volume_{i}"] = row.volume
            d[f"ask_count_{i}"] = row.order_count
        # پر کردن ردیف‌های مفقود با None
        for i in range(len(self.buy_rows) + 1, 6):
            d[f"bid_price_{i}"] = None
            d[f"bid_volume_{i}"] = None
            d[f"bid_count_{i}"] = None
        for i in range(len(self.sell_rows) + 1, 6):
            d[f"ask_price_{i}"] = None
            d[f"ask_volume_{i}"] = None
            d[f"ask_count_{i}"] = None
        # لیست مفقود به رشته
        d["missing_fields"] = ", ".join(self.missing_fields) if self.missing_fields else ""
        return d


# ---------------------------------------------------------------------------
# کلکتور واقعی - TSETMC
# ---------------------------------------------------------------------------

class MarketDataCollector:
    """دریافت داده از TSETMC برای نماد مشخص شده."""

    def __init__(self, config: Dict):
        self.cfg = config
        self.endpoints = config["tsetmc_endpoints"]
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.endpoints["user_agent"],
            "Accept": "text/plain, */*",
            "Accept-Language": "fa-IR,fa;q=0.9,en;q=0.8",
        })

    def fetch_intraday(self, ins_code: str) -> Optional[Dict]:
        """دریافت داده‌های روز جاری شامل قیمت پایانی، آخرین قیمت، حجم معاملات و پنج ردیف سفارش."""
        url = f"{self.endpoints['instinfo']}?i={ins_code}&c=57+"
        try:
            r = self.session.get(url, timeout=self.endpoints["timeout_seconds"])
            if r.status_code != 200 or not r.text.strip():
                return None
            return self._parse_instinfo(r.text)
        except Exception as e:
            print(f"[collector] خطا در دریافت instinfo: {e}")
            return None

    def fetch_clienttype(self, ins_code: str) -> Optional[Dict]:
        """دریافت اطلاعات خریداران و فروشندگان حقیقی/حقوقی."""
        url = f"{self.endpoints['clienttype']}?i={ins_code}"
        try:
            r = self.session.get(url, timeout=self.endpoints["timeout_seconds"])
            if r.status_code != 200 or not r.text.strip():
                return None
            return self._parse_clienttype(r.text)
        except Exception as e:
            print(f"[collector] خطا در دریافت clienttype: {e}")
            return None

    def _parse_instinfo(self, raw: str) -> Dict:
        """
        Parse خروجی instinfodata.aspx.
        فرمت کلی: بخش‌های جدا شده با @ و خطوط جدا با #.
        بخش پایانی داده‌های روز جاری، بخش‌های دیگر تاریخ معاملات قبلی.
        """
        info = {
            "last_price": 0,
            "close_price": 0,
            "yesterday_price": 0,
            "daily_high": 0,
            "daily_low": 0,
            "trade_volume": 0,
            "trade_value": 0,
            "trade_count": 0,
            "buy_rows": [],
            "sell_rows": [],
        }

        try:
            sections = raw.split("@")
            # بخش ۲ داده روز جاری است
            if len(sections) >= 3:
                daily = sections[2].split(";")[0]
                parts = daily.split(",")
                if len(parts) >= 17:
                    info["close_price"]   = float(parts[0])    # قیمت پایانی
                    info["last_price"]   = float(parts[1])    # آخرین قیمت
                    info["trade_volume"] = int(float(parts[2]))
                    info["trade_value"]  = float(parts[3])
                    info["trade_count"]  = int(float(parts[4]))
                    # parts[5] = تعداد خریداران، parts[6] = تعداد فروشندگان (هر دو)
                    info["yesterday_price"] = float(parts[parts.__len__() - 1]) if len(parts) > 5 else 0

            # بخش ۳ بهترین قیمت‌های خرید و فروش (۵ ردیف)
            if len(sections) >= 4:
                best_limits = sections[3]
                # هر ردیف: قیمت خرید-حجم-تعداد-قیمت فروش-حجم-تعداد
                rows = best_limits.split(";")
                buy_rows, sell_rows = [], []
                for row in rows:
                    if not row.strip():
                        continue
                    cols = row.split("@")
                    if len(cols) >= 2:
                        buy_cols = cols[0].split(",")
                        sell_cols = cols[1].split(",")
                        if len(buy_cols) >= 3:
                            buy_rows.append({
                                "price": int(float(buy_cols[0])),
                                "volume": int(float(buy_cols[1])),
                                "order_count": int(float(buy_cols[2])),
                            })
                        if len(sell_cols) >= 3:
                            sell_rows.append({
                                "price": int(float(sell_cols[0])),
                                "volume": int(float(sell_cols[1])),
                                "order_count": int(float(sell_cols[2])),
                            })
                info["buy_rows"] = buy_rows[:5]
                info["sell_rows"] = sell_rows[:5]
                if buy_rows:
                    info["daily_high"] = max(r["price"] for r in sell_rows + buy_rows)
                    info["daily_low"] = min(r["price"] for r in buy_rows)
        except Exception as e:
            print(f"[collector] خطا در parse instinfo: {e}")
        return info

    def _parse_clienttype(self, raw: str) -> Dict:
        """
        Parse خروجی clienttype.aspx.
        فرمت: buy_count_real,sell_count_real,buy_vol_real,sell_vol_real,
              buy_count_legal,sell_count_legal,buy_vol_legal,sell_vol_legal;... (هر سطر یک روز)
        """
        out = {
            "real_buy_count": 0, "real_sell_count": 0,
            "legal_buy_count": 0, "legal_sell_count": 0,
            "real_buy_volume": 0, "real_sell_volume": 0,
            "legal_buy_volume": 0, "legal_sell_volume": 0,
        }
        try:
            rows = [r for r in raw.strip().split(";") if r.strip()]
            if rows:
                last = rows[-1].split(",")
                if len(last) >= 8:
                    out["real_buy_count"]   = int(float(last[0]))
                    out["real_sell_count"]  = int(float(last[1]))
                    out["real_buy_volume"]  = int(float(last[2]))
                    out["real_sell_volume"] = int(float(last[3]))
                    out["legal_buy_count"]  = int(float(last[4]))
                    out["legal_sell_count"] = int(float(last[5]))
                    out["legal_buy_volume"] = int(float(last[6]))
                    out["legal_sell_volume"]= int(float(last[7]))
        except Exception as e:
            print(f"[collector] خطا در parse clienttype: {e}")
        return out

    def fetch_trades(self, ins_code: str) -> List[Trade]:
        """دریافت معاملات انجام‌شده اخیر (گروه E)."""
        url = f"http://www.tsetmc.com/tsev2/data/tradehistory.aspx?i={ins_code}&a=1"
        try:
            r = self.session.get(url, timeout=self.endpoints["timeout_seconds"])
            if r.status_code != 200 or not r.text.strip():
                return []
            return self._parse_trades(r.text)
        except Exception as e:
            print(f"[collector] خطا در دریافت trades: {e}")
            return []

    def _parse_trades(self, raw: str) -> List[Trade]:
        """Parse خروجی tradehistory.aspx. فرمت: زمان,قیمت,حجم,...;"""
        trades = []
        try:
            rows = [r for r in raw.strip().split(";") if r.strip()]
            for row in rows:
                cols = row.split(",")
                if len(cols) >= 3:
                    trades.append(Trade(
                        trade_time=cols[0],
                        trade_price=float(cols[1]),
                        trade_volume=int(float(cols[2])),
                        trade_id=cols[3] if len(cols) > 3 else None,
                    ))
        except Exception as e:
            print(f"[collector] خطا در parse trades: {e}")
        return trades[-200:]  # آخرین ۲۰۰ معامله

    def collect(self, symbol: str, ins_code: str,
                prev_snap: Optional[MarketSnapshot] = None,
                fetch_trades: bool = True) -> Tuple[Optional[MarketSnapshot], List[Trade]]:
        """دریافت کامل یک نمونه از تابلو + معاملات اخیر برای نماد مشخص شده."""
        inst = self.fetch_intraday(ins_code)
        ct = self.fetch_clienttype(ins_code)
        trades: List[Trade] = self.fetch_trades(ins_code) if fetch_trades else []
        if not inst:
            return None, []

        # ترکیب داده‌ها
        snap = MarketSnapshot(
            timestamp=datetime.now().isoformat(),
            tehran_time=datetime.now().strftime("%H:%M:%S"),
            symbol=symbol,
            ins_code=ins_code,
            market_phase=self._detect_market_phase(),
            source_update_time=datetime.now().isoformat(),
            data_status="ok" if inst else "error",
            last_price=inst.get("last_price", 0),
            close_price=inst.get("close_price", 0),
            yesterday_price=inst.get("yesterday_price", 0),
            open_price=inst.get("open_price", inst.get("yesterday_price", 0)),
            daily_high=inst.get("daily_high", 0),
            daily_low=inst.get("daily_low", 0),
            min_allowed_price=inst.get("min_allowed", inst.get("yesterday_price", 0) * 0.95),
            max_allowed_price=inst.get("max_allowed", inst.get("yesterday_price", 0) * 1.05),
            best_buy_price=inst["buy_rows"][0]["price"] if inst.get("buy_rows") else 0,
            best_buy_volume=inst["buy_rows"][0]["volume"] if inst.get("buy_rows") else 0,
            best_sell_price=inst["sell_rows"][0]["price"] if inst.get("sell_rows") else 0,
            best_sell_volume=inst["sell_rows"][0]["volume"] if inst.get("sell_rows") else 0,
            buy_rows=[BestLimitRow(**r) for r in inst.get("buy_rows", [])],
            sell_rows=[BestLimitRow(**r) for r in inst.get("sell_rows", [])],
            buy_order_count=sum(r.order_count for r in inst.get("buy_rows", [BestLimitRow(0,0,0)])) if inst.get("buy_rows") else 0,
            sell_order_count=sum(r.order_count for r in inst.get("sell_rows", [BestLimitRow(0,0,0)])) if inst.get("sell_rows") else 0,
            total_volume=inst.get("trade_volume", 0),
            total_value=inst.get("trade_value", 0),
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

        # محاسبه مقادیر بازه‌ای (گروه C، D) از تفاضل نمونه قبلی
        if prev_snap is not None:
            snap.interval_volume = max(0, snap.total_volume - prev_snap.total_volume)
            snap.interval_value = max(0, snap.total_value - prev_snap.total_value)
            snap.interval_trade_count = max(0, snap.total_trade_count - prev_snap.total_trade_count)
            snap.interval_real_buy_volume = max(0, snap.real_buy_volume - prev_snap.real_buy_volume)
            snap.interval_real_sell_volume = max(0, snap.real_sell_volume - prev_snap.real_sell_volume)

        # محاسبه شاخص‌های مشتق
        self._compute_derived(snap)
        # علامت‌گذاری کیفیت داده
        self._mark_completeness(snap)
        return snap, trades

    def _detect_market_phase(self) -> str:
        """تشخیص فاز بازار بر اساس زمان تهران."""
        now = datetime.now()
        h, m = now.hour, now.minute
        hm = h * 60 + m
        # ۰۸:۴۵ تا ۰۹:۰۰ پیش‌گشایش
        if 8 * 60 + 45 <= hm < 9 * 60:
            return MarketPhase.PRE_OPEN.value
        # ۰۹:۰۰ تا ۱۲:۳۰ معاملات پیوسته
        elif 9 * 60 <= hm < 12 * 60 + 30:
            return MarketPhase.CONTINUOUS.value
        else:
            return MarketPhase.CLOSED.value

    def _compute_derived(self, s: MarketSnapshot):
        """محاسبه شاخص‌های مشتق روی نمونه."""
        # سرانه خرید و فروش حقیقی
        s.per_capita_buy_real = s.real_buy_volume / max(s.real_buy_count, 1)
        s.per_capita_sell_real = s.real_sell_volume / max(s.real_sell_count, 1)
        # قدرت خریدار = سرانه خرید / سرانه فروش
        s.buyer_power = s.per_capita_buy_real / max(s.per_capita_sell_real, 1e-9)
        # ورود/خروج پول حقیقی = (ارزش خرید حقیقی - ارزش فروش حقیقی)
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

    همچنین معاملات انجام‌شده (گروه E) را در هر دقیقه تولید می‌کند.
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
        # حجم مبنا (پیش‌فرض ۱۰۰۰۰۰ سهم)
        self.base_volume = 100_000
        # شروع از ۰۸:۴۵ (پیش‌گشایش)
        self.start_time = datetime(2024, 11, 9, 8, 45, 0)

    def generate_series(self, num_samples: int = 226) -> Tuple[List[MarketSnapshot], List[Trade]]:
        """
        تولید زنجیره‌ای از نمونه‌های شبیه‌سازی شده + معاملات.

        پیش‌فرض: 226 نمونه = 08:45 تا 12:30 (225 دقیقه + 1 نمونه پایانی)
        هر نمونه 60 ثانیه فاصله دارد.

        خروجی: (snapshots, trades)
          snapshots: نمونه‌های تابلو در فواصل ۶۰ ثانیه
          trades: تمام معاملات انجام‌شده در طول روز
        """
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
        """حالت اولیه سناریو."""
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
            "trade_seq": 0,  # شناسه یکتای معامله
        }

    def _is_pre_open(self, idx: int) -> bool:
        """آیا نمونه در فاز پیش‌گشایش است؟ (idx 0-14 = 08:45-08:59)."""
        return idx < 15

    def _build_snapshot(self, t: datetime, idx: int, total: int, st: Dict) -> Tuple[MarketSnapshot, List[Trade]]:
        """ساخت یک نمونه بر اساس سناریو + تولید معاملات این دقیقه."""
        progress = idx / max(total - 1, 1)
        is_pre_open = self._is_pre_open(idx)
        market_phase = MarketPhase.PRE_OPEN.value if is_pre_open else MarketPhase.CONTINUOUS.value

        # ----- در پیش‌گشایش قیمت ثابت در yesterday_price -----
        if is_pre_open:
            last = self.base_price
            close = self.base_price
        else:
            # ----- پیشرفت قیمت بر اساس سناریو -----
            adjusted_idx = idx - 15  # شروع از 09:00
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
            else:  # mixed
                drop = -(0.005 + 0.035 * adj_progress)
                last = self.base_price * (1 + drop + 0.004 * math.sin(adjusted_idx * 0.4)
                                           + self.rng.gauss(0, 0.002))

            last = max(last, self.base_price * 0.85)
            close = last * (1 + self.rng.gauss(0, 0.0008))
            close = max(close, last * 0.998)
            if self.scenario == "sell_pressure":
                close = max(close, last * 1.001)
            elif self.scenario == "accumulation":
                close = min(close, last * 0.999)

            # اولین قیمت روز
            if st["open_price"] == self.base_price and adjusted_idx == 0:
                st["open_price"] = last

        # سقف و کف روز
        st["high"] = max(st["high"], last, close)
        st["low"] = min(st["low"], last, close)

        # کف و سقف مجاز روز (±۵٪ از قیمت دیروز)
        min_allowed = round(self.base_price * 0.95, 2)
        max_allowed = round(self.base_price * 1.05, 2)

        # ----- پنج ردیف سفارش -----
        best_buy_price = int(last * 0.998)
        best_sell_price = int(last * 1.002)

        if is_pre_open:
            # در پیش‌گشایش سفارش‌ها ثابت‌تر و کمتر
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

        # ----- تولید معاملات این دقیقه (گروه E) -----
        trades_in_minute: List[Trade] = []
        if not is_pre_open:
            # تعداد معاملات این دقیقه
            num_trades = int(self.rng.uniform(20, 60))
            for _ in range(num_trades):
                st["trade_seq"] += 1
                # قیمت معامله بین آخرین قیمت ± ۰.۱٪
                t_price = last * (1 + self.rng.gauss(0, 0.001))
                # حجم هر معامله
                t_vol = int(self.rng.uniform(500, 5000))
                # سمت آغازگر (در شبیه‌سازی ۵۰/۵۰)
                aggressor = "buy" if self.rng.random() < 0.5 else "sell"
                trades_in_minute.append(Trade(
                    trade_time=t.strftime("%H:%M:%S"),
                    trade_price=round(t_price, 2),
                    trade_volume=t_vol,
                    trade_id=f"SIM-{st['trade_seq']:06d}",
                    aggressor_side=aggressor,
                ))

        # ----- حجم/ارزش/تعداد بازه‌ای (گروه C) -----
        if not is_pre_open:
            trade_vol_minute = sum(tr.trade_volume for tr in trades_in_minute)
            trade_val_minute = sum(tr.trade_price * tr.trade_volume for tr in trades_in_minute)
            trade_count_minute = len(trades_in_minute)
        else:
            trade_vol_minute = 0
            trade_val_minute = 0.0
            trade_count_minute = 0

        # ----- پارامترهای سناریو برای اطلاعات حقیقی/حقوقی -----
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

        # شمارش تجمعی متمایز
        new_buyers = max(0, int((end_buy_count / total) * (1 + self.rng.gauss(0, 0.15))))
        new_sellers = max(0, int((end_sell_count / total) * (1 + self.rng.gauss(0, 0.15))))
        # در پیش‌گشایش تعداد کمی سفارش ثبت می‌شود
        if is_pre_open:
            new_buyers = int(new_buyers * 0.3)
            new_sellers = int(new_sellers * 0.3)
        st["cumulative_buy_count"] += new_buyers
        st["cumulative_sell_count"] += new_sellers

        # حجم‌های این دقیقه (با توجه به سناریو)
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

        # ----- تجمیع روزانه -----
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

        # ----- ساخت نمونه -----
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

        # ----- محاسبه مقادیر بازه‌ای حقیقی (گروه D) -----
        if not is_pre_open:
            snap.interval_real_buy_volume = real_buy_vol
            snap.interval_real_sell_volume = real_sell_vol

        # ----- محاسبه شاخص‌های مشتق -----
        snap.per_capita_buy_real = snap.real_buy_volume / max(snap.real_buy_count, 1)
        snap.per_capita_sell_real = snap.real_sell_volume / max(snap.real_sell_count, 1)
        snap.buyer_power = snap.per_capita_buy_real / max(snap.per_capita_sell_real, 1e-9)
        snap.real_buy_value = snap.real_buy_volume * snap.close_price
        snap.real_sell_value = snap.real_sell_volume * snap.close_price
        snap.legal_buy_value = snap.legal_buy_volume * snap.close_price
        snap.legal_sell_value = snap.legal_sell_volume * snap.close_price
        snap.real_money_flow = snap.real_buy_value - snap.real_sell_value
        snap.real_money_flow_ratio = snap.real_money_flow / max(snap.total_value, 1e-9)

        # ----- به‌روزرسانی تاریخچه -----
        st["money_flow_history"].append(snap.real_money_flow)
        st["buyer_power_history"].append(snap.buyer_power)
        st["prev_best_buy_volume"] = snap.best_buy_volume
        st["prev_best_sell_volume"] = snap.best_sell_volume
        st["price_path"].append(last)

        snap.data_complete = True
        return snap, trades_in_minute


# ---------------------------------------------------------------------------
# ذخیره‌سازی نمونه‌ها
# ---------------------------------------------------------------------------

def save_snapshot_json(snapshot: MarketSnapshot, base_dir: Path):
    """ذخیره نمونه خام در پوشه raw_snapshots."""
    base_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{snapshot.symbol}_{snapshot.timestamp.replace(':', '-')}.json"
    path = base_dir / fname
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2, default=str)
    return path


def load_config(config_path: Path) -> Dict:
    """بارگذاری فایل پیکربندی."""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)
