"""
data_collector.py
دریافت‌کننده داده‌های تابلو از TSETMC و حالت شبیه‌سازی

دو کلاس اصلی:
  - MarketDataCollector: دریافت واقعی از TSETMC (Windows 10 + requests)
  - SimulationDataCollector: شبیه‌سازی داده برای تست آفلاین موتورها

ساختار MarketSnapshot شامل تمام فیلدهای مورد نیاز دو موتور تحلیلی است.
"""

from __future__ import annotations

import json
import random
import time
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import requests


# ---------------------------------------------------------------------------
# مدل داده - یک نمونه کامل از تابلو در یک لحظه زمانی
# ---------------------------------------------------------------------------

@dataclass
class BestLimitRow:
    """یک ردیف از پنج ردیف اول سفارش خرید یا فروش."""
    price: int
    volume: int
    order_count: int


@dataclass
class MarketSnapshot:
    """یک تصویر کامل از تابلو در یک لحظه."""
    # شناسه
    timestamp: str              # ISO format
    tehran_time: str            # HH:MM:SS
    symbol: str                 # نام نماد
    ins_code: str               # کد TSETMC

    # قیمت‌ها
    last_price: float
    close_price: float          # قیمت پایانی
    yesterday_price: float      # قیمت دیروز (پایه)
    daily_high: float
    daily_low: float

    # بهترین قیمت خرید و فروش + حجم
    best_buy_price: float
    best_buy_volume: int
    best_sell_price: float
    best_sell_volume: int

    # پنج ردیف سفارش خرید و فروش
    buy_rows: List[BestLimitRow] = field(default_factory=list)
    sell_rows: List[BestLimitRow] = field(default_factory=list)

    # تعداد سفارش‌های خرید و فروش
    buy_order_count: int = 0
    sell_order_count: int = 0

    # اطلاعات حقیقی/حقوقی
    real_buy_volume: int = 0
    real_sell_volume: int = 0
    legal_buy_volume: int = 0
    legal_sell_volume: int = 0
    real_buy_count: int = 0       # تعداد خریداران حقیقی
    real_sell_count: int = 0      # تعداد فروشندگان حقیقی
    legal_buy_count: int = 0
    legal_sell_count: int = 0
    real_buy_value: float = 0
    real_sell_value: float = 0

    # معاملات
    trade_volume: int = 0
    trade_value: float = 0
    trade_count: int = 0

    # شاخص‌های مشتق (محاسبه در collector)
    buyer_power: float = 0.0
    per_capita_buy_real: float = 0.0
    per_capita_sell_real: float = 0.0
    real_money_flow: float = 0.0     # ورود/خروج پول حقیقی (مثبت = ورود)
    real_money_flow_ratio: float = 0.0  # نسبت به ارزش معاملات

    # کیفیت داده
    data_complete: bool = True
    missing_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        d = asdict(self)
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

    def collect(self, symbol: str, ins_code: str) -> Optional[MarketSnapshot]:
        """دریافت کامل یک نمونه از تابلو برای نماد مشخص شده."""
        inst = self.fetch_intraday(ins_code)
        ct = self.fetch_clienttype(ins_code)
        if not inst:
            return None

        # ترکیب داده‌ها
        snap = MarketSnapshot(
            timestamp=datetime.now().isoformat(),
            tehran_time=datetime.now().strftime("%H:%M:%S"),
            symbol=symbol,
            ins_code=ins_code,
            last_price=inst.get("last_price", 0),
            close_price=inst.get("close_price", 0),
            yesterday_price=inst.get("yesterday_price", 0),
            daily_high=inst.get("daily_high", 0),
            daily_low=inst.get("daily_low", 0),
            best_buy_price=inst["buy_rows"][0]["price"] if inst.get("buy_rows") else 0,
            best_buy_volume=inst["buy_rows"][0]["volume"] if inst.get("buy_rows") else 0,
            best_sell_price=inst["sell_rows"][0]["price"] if inst.get("sell_rows") else 0,
            best_sell_volume=inst["sell_rows"][0]["volume"] if inst.get("sell_rows") else 0,
            buy_rows=[BestLimitRow(**r) for r in inst.get("buy_rows", [])],
            sell_rows=[BestLimitRow(**r) for r in inst.get("sell_rows", [])],
            buy_order_count=sum(r.order_count for r in inst.get("buy_rows", [BestLimitRow(0,0,0)])) if inst.get("buy_rows") else 0,
            sell_order_count=sum(r.order_count for r in inst.get("sell_rows", [BestLimitRow(0,0,0)])) if inst.get("sell_rows") else 0,
            real_buy_volume=ct.get("real_buy_volume", 0) if ct else 0,
            real_sell_volume=ct.get("real_sell_volume", 0) if ct else 0,
            legal_buy_volume=ct.get("legal_buy_volume", 0) if ct else 0,
            legal_sell_volume=ct.get("legal_sell_volume", 0) if ct else 0,
            real_buy_count=ct.get("real_buy_count", 0) if ct else 0,
            real_sell_count=ct.get("real_sell_count", 0) if ct else 0,
            legal_buy_count=ct.get("legal_buy_count", 0) if ct else 0,
            legal_sell_count=ct.get("legal_sell_count", 0) if ct else 0,
            trade_volume=inst.get("trade_volume", 0),
            trade_value=inst.get("trade_value", 0),
            trade_count=inst.get("trade_count", 0),
        )

        # محاسبه شاخص‌های مشتق
        self._compute_derived(snap)
        # علامت‌گذاری کیفیت داده
        self._mark_completeness(snap)
        return snap

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
        s.real_money_flow = s.real_buy_value - s.real_sell_value
        s.real_money_flow_ratio = s.real_money_flow / max(s.trade_value, 1e-9)

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
        # ساعت شروع بازار
        self.start_time = datetime(2024, 11, 9, 9, 0, 0)

    def generate_series(self, num_samples: int = 150) -> List[MarketSnapshot]:
        """تولید زنجیره‌ای از نمونه‌های شبیه‌سازی شده (پیش‌فرض: ۱۵۰ نمونه = ۲.۵ ساعت)."""
        snapshots: List[MarketSnapshot] = []
        state = self._init_scenario_state()

        for i in range(num_samples):
            t = self.start_time + timedelta(seconds=60 * i)
            snap = self._build_snapshot(t, i, num_samples, state)
            snapshots.append(snap)
        return snapshots

    def _init_scenario_state(self) -> Dict:
        """حالت اولیه سناریو."""
        return {
            "yesterday_price": self.base_price,
            "high": self.base_price,
            "low": self.base_price,
            "accumulated_buy_volume": 0,
            "accumulated_sell_volume": 0,
            "prev_best_buy_volume": 50000,
            "prev_best_sell_volume": 40000,
            "trade_volume_today": 0,
            "trade_value_today": 0,
            "trade_count_today": 0,
            # شمارش تجمعی متمایز (رشد خطی در طول روز)
            "cumulative_buy_count": 0,
            "cumulative_sell_count": 0,
            "money_flow_history": [],   # برای تداوم خرید
            "buyer_power_history": [],
            "price_path": [self.base_price],
        }

    def _build_snapshot(self, t: datetime, idx: int, total: int, st: Dict) -> MarketSnapshot:
        """ساخت یک نمونه بر اساس سناریو."""
        progress = idx / max(total - 1, 1)  # 0 → 1 در طول روز

        # ----- پیشرفت قیمت بر اساس سناریو (کنترل‌شده، حداکثر ۸٪ افت) -----
        if self.scenario == "normal":
            # نوسان ملایم ±۲٪
            last = self.base_price * (1 + 0.005 * math.sin(idx * 0.3) + self.rng.gauss(0, 0.002))
        elif self.scenario == "sell_pressure":
            # افت کنترل‌شده از ۰٪ تا ۸٪ با شتاب در اواخر
            drop = -(0.01 + 0.07 * progress ** 1.3)
            last = self.base_price * (1 + drop + self.rng.gauss(0, 0.002))
        elif self.scenario == "accumulation":
            # قیمت منفی ملایم با مقاومت (۰٪ تا ۳٪ افت)
            drop = -(0.005 + 0.025 * progress)
            last = self.base_price * (1 + drop + self.rng.gauss(0, 0.002))
        else:  # mixed
            # فشار فروش + مقاومت قوی (۰٪ تا ۴٪ افت با نوسان)
            drop = -(0.005 + 0.035 * progress)
            last = self.base_price * (1 + drop + 0.004 * math.sin(idx * 0.4)
                                       + self.rng.gauss(0, 0.002))

        # اطمینان از مثبت ماندن قیمت
        last = max(last, self.base_price * 0.85)  # حداقل ۱۵٪ پایین‌تر از پایه
        close = last * (1 + self.rng.gauss(0, 0.0008))
        close = max(close, last * 0.998)
        # برای سناریوی sell_pressure: آخرین < پایانی (فشار فروش)
        if self.scenario == "sell_pressure":
            close = max(close, last * 1.001)  # پایانی کمی بالاتر از آخرین
        elif self.scenario == "accumulation":
            close = min(close, last * 0.999)  # پایانی کمی پایین‌تر از آخرین (مقاومت)

        # سقف و کف روز
        st["high"] = max(st["high"], last, close)
        st["low"] = min(st["low"], last, close)

        # ----- پنج ردیف سفارش -----
        best_buy_price = int(last * 0.998)
        best_sell_price = int(last * 1.002)

        if self.scenario == "sell_pressure":
            # عرضه به‌سرعت افزایش می‌یابد، تقاضا تخلیه می‌شود
            base_buy_vol = max(2000, int(50000 * (1 - 0.7 * progress)))
            base_sell_vol = int(40000 * (1 + 2.0 * progress))
        elif self.scenario == "accumulation":
            # عرضه زیاد ولی تقاضا پایدار و جذب‌کننده
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

        # ----- اطلاعات حقیقی/حقوقی -----
        # حجم معاملات این دقیقه
        trade_vol_minute = int(self.rng.uniform(80000, 250000))
        trade_val_minute = trade_vol_minute * last

        # ----- پارامترهای سناریو:buyer_count و sell_count به‌صورت تجمعی روزانه -----
        # هدف: در پایان روز به حدود count_end برسیم
        # رشد خطی + نویز، به‌علاوه برخی ورود/خروج تصادفی
        if self.scenario == "sell_pressure":
            # پانیک فروش: فروشندگان خرد زیاد + خریداران اندک + حجم فروش بسیار بالا
            # هدف: قدرت خریدار < ۰.۵، خروج شدید پول، تمامی شاخص‌های فشار فروش فعال
            end_buy_count = 600
            end_sell_count = 2500
            real_buy_share = 0.10   # حجم خرید بسیار کم
            real_sell_share = 0.85  # حجم فروش بسیار بالا
            legal_buy_share = 0.05
            legal_sell_share = 0.10
        elif self.scenario == "accumulation":
            # جمع‌آوری پنهان: خریداران اندک ولی حجیم + فروشندگان خرد
            # هدف: قدرت خریدار > ۸، ورود شدید پول، قیمت مقاومت می‌کند
            end_buy_count = 600
            end_sell_count = 2500
            real_buy_share = 0.80  # حجم خرید بسیار بالا
            real_sell_share = 0.15  # حجم فروش کم
            legal_buy_share = 0.18
            legal_sell_share = 0.10
        elif self.scenario == "mixed":
            # هر دو قوی: خریداران رسمی اندک ولی حجیم در حال جذب، فروشندگان خرد در حال فروش
            # هدف: فشار فروش بالا + جمع‌آوری بالا (وضعیت نارنجی)
            # خروج پول کل (فروش > خرید) ولی قدرت خریدار بالا (هر خریدار حجمی)
            end_buy_count = 200
            end_sell_count = 2500
            real_buy_share = 0.40
            real_sell_share = 0.55
            legal_buy_share = 0.15
            legal_sell_share = 0.15
        else:  # normal
            end_buy_count = 1500
            end_sell_count = 1500
            real_buy_share = 0.45
            real_sell_share = 0.45
            legal_buy_share = 0.15
            legal_sell_share = 0.10

        # رشد خطی شمارش تجمعی (با نویز)
        # افزودن «سرانه رشد» در این دقیقه
        new_buyers = max(1, int((end_buy_count / total) * (1 + self.rng.gauss(0, 0.15))))
        new_sellers = max(1, int((end_sell_count / total) * (1 + self.rng.gauss(0, 0.15))))
        st["cumulative_buy_count"] += new_buyers
        st["cumulative_sell_count"] += new_sellers

        # ----- حجم‌های این دقیقه (با توجه به سناریو) -----
        real_buy_share = max(0.05, real_buy_share + self.rng.gauss(0, 0.03))
        real_sell_share = max(0.05, real_sell_share + self.rng.gauss(0, 0.03))

        real_buy_vol = int(trade_vol_minute * real_buy_share)
        real_sell_vol = int(trade_vol_minute * real_sell_share)
        legal_buy_vol = int(trade_vol_minute * max(0.02, legal_buy_share))
        legal_sell_vol = int(trade_vol_minute * max(0.02, legal_sell_share))

        # ----- تجمیع روزانه -----
        st["trade_volume_today"] += trade_vol_minute
        st["trade_value_today"] += trade_val_minute
        st["trade_count_today"] += int(self.rng.uniform(50, 200))
        st["accumulated_buy_volume"] += real_buy_vol
        st["accumulated_sell_volume"] += real_sell_vol

        # ----- ساخت نمونه -----
        snap = MarketSnapshot(
            timestamp=t.isoformat(),
            tehran_time=t.strftime("%H:%M:%S"),
            symbol=self.symbol,
            ins_code=self.ins_code,
            last_price=round(last, 2),
            close_price=round(close, 2),
            yesterday_price=st["yesterday_price"],
            daily_high=st["high"],
            daily_low=st["low"],
            best_buy_price=buy_rows[0].price,
            best_buy_volume=buy_rows[0].volume,
            best_sell_price=sell_rows[0].price,
            best_sell_volume=sell_rows[0].volume,
            buy_rows=buy_rows,
            sell_rows=sell_rows,
            buy_order_count=sum(r.order_count for r in buy_rows),
            sell_order_count=sum(r.order_count for r in sell_rows),
            real_buy_volume=st["accumulated_buy_volume"],
            real_sell_volume=st["accumulated_sell_volume"],
            legal_buy_volume=int(st["trade_volume_today"] * 0.20),
            legal_sell_volume=int(st["trade_volume_today"] * 0.15),
            real_buy_count=st["cumulative_buy_count"],
            real_sell_count=st["cumulative_sell_count"],
            legal_buy_count=int(st["cumulative_buy_count"] * 0.3),
            legal_sell_count=int(st["cumulative_sell_count"] * 0.3),
            trade_volume=st["trade_volume_today"],
            trade_value=st["trade_value_today"],
            trade_count=st["trade_count_today"],
        )

        # ----- محاسبه شاخص‌های مشتق -----
        snap.per_capita_buy_real = snap.real_buy_volume / max(snap.real_buy_count, 1)
        snap.per_capita_sell_real = snap.real_sell_volume / max(snap.real_sell_count, 1)
        snap.buyer_power = snap.per_capita_buy_real / max(snap.per_capita_sell_real, 1e-9)
        snap.real_buy_value = snap.real_buy_volume * snap.close_price
        snap.real_sell_value = snap.real_sell_volume * snap.close_price
        snap.real_money_flow = snap.real_buy_value - snap.real_sell_value
        snap.real_money_flow_ratio = snap.real_money_flow / max(snap.trade_value, 1e-9)

        # ----- به‌روزرسانی تاریخچه برای تداوم خرید -----
        st["money_flow_history"].append(snap.real_money_flow)
        st["buyer_power_history"].append(snap.buyer_power)
        st["prev_best_buy_volume"] = snap.best_buy_volume
        st["prev_best_sell_volume"] = snap.best_sell_volume
        st["price_path"].append(last)

        snap.data_complete = True
        return snap


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
