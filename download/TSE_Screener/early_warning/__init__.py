"""
TSE Early Warning Engine
ماژول هشدار زودهنگام بورس تهران

سه موتور تحلیلی مستقل:
  1. Sell Pressure Detector  - تشخیص فشار فروش (۰-۱۰۰)
  2. Smart Accumulation Detector - تشخیص جمع‌آوری سهم (۰-۱۰۰)
  3. Speed Indicator Engine - شاخص‌های سرعتی نردبان سفارش‌ها (بعد سوم؛
     تأیید/ارتقای زودهنگام هشدار زرد به قرمز)
"""

__version__ = "1.2.0"
__author__ = "TSE Screener"

from .data_collector import (
    MarketDataCollector, SimulationDataCollector,
    MarketSnapshot, BestLimitRow, Trade, MarketPhase,
)
from .data_validator import DataValidator, DataQualityReport
from .sell_pressure import SellPressureDetector
from .smart_accumulation import SmartAccumulationDetector
from .alert_engine import AlertEngine, AlertEvent
from .speed_indicators import SpeedIndicatorEngine, SpeedIndicatorsResult
from .excel_report import ExcelReportGenerator
from .storage import MarketDataStorage
from .price_range import (
    load_range_rules, load_symbol_categories,
    get_symbol_category, get_category_percent,
    compute_daily_params, to_jalali,
)

__all__ = [
    "MarketDataCollector",
    "SimulationDataCollector",
    "MarketSnapshot",
    "BestLimitRow",
    "Trade",
    "MarketPhase",
    "DataValidator",
    "DataQualityReport",
    "SellPressureDetector",
    "SmartAccumulationDetector",
    "AlertEngine",
    "AlertEvent",
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
]
