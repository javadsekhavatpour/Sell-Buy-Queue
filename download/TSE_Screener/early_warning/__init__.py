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
]
