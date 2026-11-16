"""
TSE Early Warning Engine
ماژول هشدار زودهنگام بورس تهران — نسخه ۲.۰

دو موتور تحلیلی مستقل (هر کدام ۰-۱۰۰):
  1. Sell Pressure Detector  - موتور فشار فروش (۶ شاخص)
  2. Buy Pressure Detector   - موتور فشار خرید (۶ شاخص آینه‌ای + جذب عرضه)
  3. Alert Engine            - ترکیب دو موتور + tier/classify
"""

__version__ = "2.0.0"
__author__ = "TSE Screener"

from .data_collector import (
    MarketDataCollector, SimulationDataCollector,
    MarketSnapshot, BestLimitRow, Trade, MarketPhase,
)
from .data_validator import DataValidator, DataQualityReport
from .sell_pressure import SellPressureDetector
from .smart_accumulation import BuyPressureDetector, SmartAccumulationDetector
from .alert_engine import AlertEngine, AlertEvent, tier, classify
from .speed_indicators import SpeedIndicatorEngine, SpeedIndicatorsResult
from .excel_report import ExcelReportGenerator
from .storage import MarketDataStorage
from .price_range import (
    load_range_rules, load_symbol_categories,
    get_symbol_category, get_category_percent,
    compute_daily_params, to_jalali,
)
from .isin_checker import (
    parse_range_rules_html,
    get_isin_prefix,
    get_range_percent_by_isin,
    get_symbol_range_from_isin,
    compute_range_from_isin,
)

__all__ = [
    "MarketDataCollector",
    "SimulationDataCollector",
    "MarketSnapshot",
    "BestListRow",
    "Trade",
    "MarketPhase",
    "DataValidator",
    "DataQualityReport",
    "SellPressureDetector",
    "BuyPressureDetector",
    "SmartAccumulationDetector",
    "AlertEngine",
    "AlertEvent",
    "tier",
    "classify",
    "SpeedIndicatorEngine",
    "SpeedIndicatorsResult",
    "ExcelReportGenerator",
    "MarketDataStorage",
    "load_range_rules",
    "load_symbol_categories",
    "get_symbol_category",
    "get_category_percent",
    "compute_daily_params",
    "to_jalali",
    "parse_range_rules_html",
    "get_isin_prefix",
    "get_range_percent_by_isin",
    "get_symbol_range_from_isin",
    "compute_range_from_isin",
]
