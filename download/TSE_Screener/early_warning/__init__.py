"""
TSE Early Warning Engine
ماژول هشدار زودهنگام بورس تهران

دو موتور تحلیلی مستقل:
  1. Sell Pressure Detector  - تشخیص فشار فروش (۰-۱۰۰)
  2. Smart Accumulation Detector - تشخیص جمع‌آوری سهم (۰-۱۰۰)
"""

__version__ = "1.0.0"
__author__ = "TSE Screener"

from .data_collector import MarketDataCollector, SimulationDataCollector
from .data_validator import DataValidator, DataQualityReport
from .sell_pressure import SellPressureDetector
from .smart_accumulation import SmartAccumulationDetector
from .alert_engine import AlertEngine, AlertEvent
from .excel_report import ExcelReportGenerator

__all__ = [
    "MarketDataCollector",
    "SimulationDataCollector",
    "DataValidator",
    "DataQualityReport",
    "SellPressureDetector",
    "SmartAccumulationDetector",
    "AlertEngine",
    "AlertEvent",
    "ExcelReportGenerator",
]
