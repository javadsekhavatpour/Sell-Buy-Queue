"""
excel_report.py
تولید گزارش Excel با هشت شیت:
  1. Dashboard     - وضعیت لحظه‌ای و هشدارها
  2. SellPressure  - شش عامل فشار فروش و امتیازها (به‌مرور زمان)
  3. Accumulation  - شش عامل جمع‌آوری و امتیازها (به‌مرور زمان)
  4. 5min_Trend    - تجمیع ۵دقیقه‌ای: روند سیگنال vs حرکت قیمت همان بازه
  5. Snapshots     - تمام نمونه‌های خام تابلو (گروه‌های A-D و F)
  6. Trades        - معاملات انجام‌شده (گروه E)
  7. Metadata      - مشخصات نماد، بازه زمانی، وضعیت بازار
  8. History       - خلاصه روند زمانی

ستون «Δ30ث قیمت٪» (حرکت اخیر قیمت نسبت به نمونهٔ قبلی) در شیت‌های
SellPressure/Accumulation/History/Dashboard اضافه شده است؛ این معیاری است که
امتیاز فشار فروش/جمع‌آوری با آن همخوان است (نه با «٪ نوسان لحظه‌ای» که نسبت به
قیمت دیروز محاسبه می‌شود).

نماد: دابور (نمونه آزمایشی)
"""

from __future__ import annotations

from typing import List, Dict, Optional
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import (
    Font, Alignment, PatternFill, Border, Side, NamedStyle
)
from openpyxl.utils import get_column_letter
from openpyxl.chart import LineChart, BarChart, Reference
from openpyxl.chart.label import DataLabelList

from .sell_pressure import SellPressureResult
from .smart_accumulation import BuyPressureResult, AccumulationResult   # AccumulationResult = alias
from .alert_engine import CombinedState, AlertEvent, AlertLevel
from .data_collector import MarketSnapshot, Trade


# ----- پالت رنگ -----
class Colors:
    HEADER_BG = "1F4E78"       # آبی تیره هدر
    HEADER_FG = "FFFFFF"
    TITLE_BG = "2E75B6"         # آبی متوسط عنوان
    SUBTITLE_BG = "DDEBF7"
    NORMAL = "C6EFCE"          # سبز روشن
    WATCH = "FFEB9C"          # زرد روشن
    WARNING = "FFC000"         # نارنجی
    DANGER = "FF6B6B"          # قرمز روشن
    CRITICAL = "C00000"        # قرمز تیره
    GREEN_ALERT = "92D050"    # سبز هشدار
    ORANGE = "ED7D31"          # نارنجی هشدار ترکیبی
    NEUTRAL = "F2F2F2"         # خاکستری روشن
    ALERT_BG = "FFF2CC"        # پس‌زمینه پیام هشدار
    BORDER = "BFBFBF"


# ----- استایل‌های مشترک -----
def _border():
    side = Side(style="thin", color=Colors.BORDER)
    return Border(left=side, right=side, top=side, bottom=side)


def _header_font():
    return Font(name="B Nazanin", size=11, bold=True, color=Colors.HEADER_FG)


def _body_font():
    return Font(name="B Nazanin", size=10)


def _title_font():
    return Font(name="B Nazanin", size=14, bold=True, color=Colors.HEADER_FG)


def _subtitle_font():
    return Font(name="B Nazanin", size=11, bold=True, color="1F4E78")


def _score_color(score: float) -> str:
    """رنگ بر اساس امتیاز فشار فروش."""
    if score <= 24:  return Colors.NORMAL
    if score <= 34:  return Colors.WATCH
    if score <= 49:  return Colors.WARNING
    if score <= 64:  return Colors.DANGER
    if score <= 79:  return Colors.CRITICAL
    return Colors.CRITICAL


def _acc_color(score: float) -> str:
    """رنگ بر اساس امتیاز جمع‌آوری."""
    if score <= 24:  return Colors.NEUTRAL
    if score <= 39:  return Colors.WATCH
    if score <= 59:  return Colors.GREEN_ALERT
    if score <= 79:  return "00B050"
    return "006100"


def _delta_30s_pct(snap, prev_snap) -> Optional[float]:
    """تغییر درصدی آخرین قیمت نسبت به نمونهٔ قبلی (۳۰ثانیه).

    این معیار «حرکت اخیر قیمت» است — برخلاف «٪ نوسان لحظه‌ای» که نسبت به
    قیمت دیروز محاسبه می‌شود. امتیاز فشار فروش/جمع‌آوری با این ستون همخوان است،
    نه با ٪ نسبت‌به‌دیروز (چون sell_score از دلتای ۳۰ثانیه‌ای جریان سفارش ساخته
    می‌شود).

    فیلتر داده خراب: |Δ| > 20٪ یا قیمت صفر → None.
    """
    if not prev_snap or not snap:
        return None
    if not prev_snap.last_price or not snap.last_price:
        return None
    d = (snap.last_price - prev_snap.last_price) / prev_snap.last_price * 100
    if abs(d) > 20:
        return None
    return round(d, 2)


def _delta_color(d) -> str:
    """رنگ بر اساس جهت حرکت اخیر قیمت (Δ30ث)."""
    if d is None:
        return Colors.NEUTRAL
    if d < -0.1:   # افت قیمت → قرمز
        return Colors.DANGER
    if d > 0.1:    # رشد قیمت → سبز
        return Colors.GREEN_ALERT
    return Colors.NEUTRAL   # تخت


# ----- ردیف نام فیلد انگلیسی (زیر هدر فارسی) -----
EN_ROW_BG = "DDEBF7"
EN_ROW_FG = "1F4E78"


def _write_en_field_row(ws, header_row: int, field_names):
    """نام انگلیسی فیلدها را در ردیف header_row+1 با استایل متمایز می‌نویسد.

    داده‌ها باید از ردیف header_row+2 آغاز شوند (یعنی هدر فارسی در header_row،
    نام انگلیسی در header_row+1، داده از header_row+2).
    """
    en_row = header_row + 1
    for i, en in enumerate(field_names, 1):
        c = ws.cell(row=en_row, column=i, value=en)
        c.font = Font(name="B Nazanin", size=9, color=EN_ROW_FG)
        c.fill = PatternFill("solid", fgColor=EN_ROW_BG)
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.border = _border()
    ws.row_dimensions[en_row].height = 18
    return en_row


# نام فیلدهای انگلیسی هر شیت (به‌ترتیب ستون‌های هدر فارسی)
SELL_FACTOR_FIELDS = ["sell_breadth", "sell_flow", "sell_ticket",
                      "sell_price", "sell_supply", "sell_lower"]
BUY_FACTOR_FIELDS = ["buy_breadth", "buy_flow", "buy_ticket",
                     "buy_price", "buy_absorption", "buy_support"]

BUYSELLPRESSURE_FA = [
    "زمان",
    "ضعف قدرت خریدار (۲۰)", "خروج پول حقیقی (۲۰)", "برتری سرانه فروش (۱۵)",
    "فاصله منفی آخرین-پایانی (۱۵)", "افزایش سرعت عرضه (۱۵)", "تخلیه تقاضا/کف روز (۱۵)",
    "قدرت خرید حقیقی (۲۰)", "ورود پول حقیقی (۲۰)", "برتری تعداد خریداران (۱۰)",
    "جذب عرضه/ماندگاری (۲۰)", "مقاومت قیمت (۲۰)", "تداوم خرید (۱۰)",
    "مجموع فشار فروش", "سطح فشار فروش", "مجموع جمع‌آوری", "سطح جمع‌آوری",
    "امتیاز کلی", "Δ30ث قیمت٪", "٪ نوسان لحظه‌ای", "٪ نوسان پایانی",
    "فشار فروش تجمعی ۵دقیقه", "فشار خرید تجمعی ۵دقیقه",
    "فشار فروش تجمعی ۱۵دقیقه", "فشار خرید تجمعی ۱۵دقیقه",
]
BUYSELLPRESSURE_EN = [
    "snapshot_time",
    *SELL_FACTOR_FIELDS, *BUY_FACTOR_FIELDS,
    "sell_total_score", "sell_level", "buy_total_score", "buy_level",
    "overall_score", "delta_30s_pct", "pct_last", "pct_close",
    "sell_cum_5min", "buy_cum_5min", "sell_cum_15min", "buy_cum_15min",
]
BUYSELLPRESSURE_WIDTHS = [12] + [14]*12 + [11]*4 + [11, 11, 12, 12] + [14]*4

HISTORY_EN = ["snapshot_time", "last_price", "close_price", "best_bid", "bid_volume",
              "best_ask", "ask_volume", "total_volume", "total_value", "buyer_power",
              "ind_money_flow", "sell_pressure", "accumulation", "status",
              "delta_30s_pct", "pct_last", "pct_close"]

SNAPSHOTS_EN = [
    "date_jalali", "tehran_time", "symbol", "market_phase", "symbol_status",
    "data_status", "fetch_error",
    "last_price", "close_price", "open_price", "yesterday_price",
    "daily_high", "daily_low", "min_allowed_price", "max_allowed_price",
    "best_bid", "bid_volume", "best_ask", "ask_volume",
    "buy_order_count", "sell_order_count",
    "bid_price_1", "bid_vol_1", "bid_count_1", "bid_price_2", "bid_vol_2", "bid_count_2",
    "bid_price_3", "bid_vol_3", "bid_count_3", "bid_price_4", "bid_vol_4", "bid_count_4",
    "bid_price_5", "bid_vol_5", "bid_count_5",
    "ask_price_1", "ask_vol_1", "ask_count_1", "ask_price_2", "ask_vol_2", "ask_count_2",
    "ask_price_3", "ask_vol_3", "ask_count_3", "ask_price_4", "ask_vol_4", "ask_count_4",
    "ask_price_5", "ask_vol_5", "ask_count_5",
    "total_volume", "total_value", "total_trade_count", "base_volume",
    "interval_volume", "interval_value", "interval_trade_count",
    "real_buy_count", "real_buy_volume", "real_buy_value",
    "real_sell_count", "real_sell_volume", "real_sell_value",
    "legal_buy_count", "legal_buy_volume", "legal_buy_value",
    "legal_sell_count", "legal_sell_volume", "legal_sell_value",
    "interval_real_buy_volume", "interval_real_sell_volume",
    "buyer_power", "per_capita_buy", "per_capita_sell",
    "real_money_flow", "real_money_flow_ratio",
    "data_complete", "missing_fields", "pct_last", "pct_close",
]

TRADES_EN = ["row_num", "trade_time", "trade_price", "trade_volume", "trade_id",
             "aggressor_side", "pct_last", "pct_close"]

TREND5_EN = ["bucket", "n", "start_price", "end_price", "delta_5min_pct",
             "avg_sell", "avg_buy", "net_signal", "max_sell", "volume", "alignment",
             "pct_last", "pct_close"]

DASH_ALERT_EN = ["timestamp", "level", "title", "message", "sell_score",
                 "buy_score", "classification", "suggested_action"]
DASH_TREND_EN = ["sample_idx", "sell_total_score", "buy_total_score",
                 "pct_last", "pct_close", "delta_30s_pct"]

METADATA_EN = ["symbol", "source", "ins_code", "date_jalali", "start_time", "end_time",
               "total_samples", "complete_samples", "error_samples", "symbol_status",
               "phase_distribution", "open_price", "last_price_eod", "close_price_eod",
               "yesterday_price", "pct_last_eod", "pct_close_eod", "min_allowed_price",
               "max_allowed_price", "daily_high", "daily_low", "total_volume",
               "total_value", "total_trade_count", "base_volume", "price_unit",
               "volume_unit", "data_source", "sampling_interval", "engine_version"]


class ExcelReportGenerator:
    """تولید گزارش Excel چهار شیت."""

    def __init__(self, config: Dict):
        self.cfg = config
        self.wb = Workbook()
        # اولین شیت Dashboard است، بقیه ساخته می‌شوند
        self.ws_dashboard = self.wb.active
        self.ws_dashboard.title = "Dashboard"

    def generate(
        self,
        symbol: str,
        snapshots: List,
        sp_results: List[SellPressureResult],
        acc_results: List[AccumulationResult],
        combined_states: List[CombinedState],
        alert_events: List[AlertEvent],
        output_path: Path,
        trades: Optional[List[Trade]] = None,
        source: str = "زنده (Live)"
    ) -> Path:
        """تولید کامل گزارش با هشت شیت.

        پارامتر source: منبع داده را در شیت Metadata مشخص می‌کند
        (مثلاً «شبیه‌سازی (Sim)» یا «زنده (Live)»).
        """
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._build_dashboard(
            symbol, snapshots, sp_results, acc_results,
            combined_states, alert_events
        )
        # فشار فروش و فشار خرید در یک شیت دوطرفه (BuySellPressure) — شیت جدا حذف شد
        self._build_buysell_pressure_sheet(sp_results, acc_results, snapshots)
        self._build_5min_trend_sheet(sp_results, acc_results, snapshots)
        self._build_snapshots_sheet(snapshots)
        if trades:
            yesterday_price = snapshots[-1].yesterday_price if snapshots else 0
            self._build_trades_sheet(trades, symbol, yesterday_price)
        self._build_metadata_sheet(snapshots, symbol, source)
        self._build_history_sheet(snapshots, combined_states)

        self.wb.save(str(output_path))
        return output_path

    # -----------------------------------------------------------------
    # شیت ۱: Dashboard
    # -----------------------------------------------------------------
    def _build_dashboard(
        self,
        symbol: str,
        snapshots: List,
        sp_results: List[SellPressureResult],
        acc_results: List[AccumulationResult],
        combined_states: List[CombinedState],
        alert_events: List[AlertEvent]
    ):
        ws = self.ws_dashboard
        ws.sheet_view.rightToLeft = True

        # عرض ستون‌ها
        for col, w in zip("ABCDEFG", [22, 18, 18, 18, 18, 18, 18]):
            ws.column_dimensions[col].width = w

        # عنوان اصلی
        ws.merge_cells("A1:G1")
        c = ws["A1"]
        c.value = "داشبورد هشدار معاملات - TSE Early Warning Engine"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 28

        # زیرعنوان نماد
        ws.merge_cells("A2:G2")
        c = ws["A2"]
        c.value = f"نماد: {symbol}  |  نسخه گزارش: ۱.۰"
        c.font = _subtitle_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
        ws.row_dimensions[2].height = 22

        # ----- وضعیت لحظه‌ای -----
        if combined_states:
            last = combined_states[-1]
            last_sp = sp_results[-1]
            last_acc = acc_results[-1]

            row = 4
            ws.merge_cells(start_row=row, end_row=row, start_column=1, end_column=7)
            c = ws.cell(row=row, column=1, value="وضعیت لحظه‌ای (آخرین نمونه)")
            c.font = _subtitle_font()
            c.fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[row].height = 22

            row = 5
            ws.cell(row=row, column=1, value="زمان آخرین نمونه:").font = _body_font()
            ws.cell(row=row, column=2, value=last.timestamp).font = _body_font()
            ws.cell(row=row, column=3, value="آخرین قیمت:").font = _body_font()
            ws.cell(row=row, column=4, value=snapshots[-1].last_price).font = _body_font()
            ws.cell(row=row, column=5, value="قیمت پایانی:").font = _body_font()
            ws.cell(row=row, column=6, value=snapshots[-1].close_price).font = _body_font()

            # امتیاز فشار فروش
            row = 7
            ws.merge_cells(start_row=row, end_row=row+1, start_column=1, end_column=1)
            c = ws.cell(row=row, column=1, value="Sell Pressure")
            c.font = Font(name="B Nazanin", size=12, bold=True, color=Colors.HEADER_FG)
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")

            ws.merge_cells(start_row=row, end_row=row+1, start_column=2, end_column=4)
            c = ws.cell(row=row, column=2, value=f"{last_sp.total_score:.0f} / 100")
            # اگر امتیاز بالا (>= 50) متن سفید، وگرنه تیره
            sp_text_color = "FFFFFF" if last_sp.total_score >= 50 else "1F4E78"
            c.font = Font(name="B Nazanin", size=20, bold=True, color=sp_text_color)
            c.fill = PatternFill("solid", fgColor=_score_color(last_sp.total_score))
            c.alignment = Alignment(horizontal="center", vertical="center")

            ws.merge_cells(start_row=row, end_row=row+1, start_column=5, end_column=7)
            c = ws.cell(row=row, column=5, value=last_sp.level)
            c.font = Font(name="B Nazanin", size=11, bold=True, color=sp_text_color)
            c.fill = PatternFill("solid", fgColor=_score_color(last_sp.total_score))
            c.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[row].height = 24
            ws.row_dimensions[row+1].height = 24

            # امتیاز جمع‌آوری
            row = 10
            ws.merge_cells(start_row=row, end_row=row+1, start_column=1, end_column=1)
            c = ws.cell(row=row, column=1, value="Accumulation")
            c.font = Font(name="B Nazanin", size=12, bold=True, color=Colors.HEADER_FG)
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")

            ws.merge_cells(start_row=row, end_row=row+1, start_column=2, end_column=4)
            c = ws.cell(row=row, column=2, value=f"{last_acc.total_score:.0f} / 100")
            # اگر امتیاز قوی (>= 40) متن سفید، وگرنه سبز تیره
            acc_text_color = "FFFFFF" if last_acc.total_score >= 40 else "006100"
            c.font = Font(name="B Nazanin", size=20, bold=True, color=acc_text_color)
            c.fill = PatternFill("solid", fgColor=_acc_color(last_acc.total_score))
            c.alignment = Alignment(horizontal="center", vertical="center")

            ws.merge_cells(start_row=row, end_row=row+1, start_column=5, end_column=7)
            c = ws.cell(row=row, column=5, value=last_acc.level)
            c.font = Font(name="B Nazanin", size=11, bold=True, color=acc_text_color)
            c.fill = PatternFill("solid", fgColor=_acc_color(last_acc.total_score))
            c.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[row].height = 24
            ws.row_dimensions[row+1].height = 24

            # سیگنال نهایی
            row = 13
            ws.merge_cells(start_row=row, end_row=row, start_column=1, end_column=7)
            c = ws.cell(row=row, column=1, value="سیگنال نهایی")
            c.font = _subtitle_font()
            c.fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[row].height = 22

            row = 14
            ws.merge_cells(start_row=row, end_row=row+2, start_column=1, end_column=7)
            # رنگ و پیام سیگنال
            if last.alert:
                level = last.alert.level
                if level == AlertLevel.RED:
                    bg = Colors.CRITICAL
                    fg = "FFFFFF"
                    msg = last.alert.title
                elif level == AlertLevel.PURPLE:
                    bg = Colors.ORANGE
                    fg = "FFFFFF"
                    msg = last.alert.title
                elif level == AlertLevel.GREEN:
                    bg = Colors.GREEN_ALERT
                    fg = "FFFFFF"
                    msg = last.alert.title
                elif level == AlertLevel.EARLY_SELL:
                    bg = Colors.WARNING
                    fg = "1F4E78"
                    msg = last.alert.title
                elif level == AlertLevel.EARLY_BUY:
                    bg = Colors.GREEN_ALERT
                    fg = "1F4E78"
                    msg = last.alert.title
                elif level == AlertLevel.WATCH:
                    bg = Colors.WARNING
                    fg = "1F4E78"
                    msg = last.alert.title
                else:
                    bg = Colors.NEUTRAL
                    fg = "1F4E78"
                    msg = "وضعیت عادی"
            else:
                bg = Colors.NEUTRAL
                fg = "1F4E78"
                msg = "وضعیت عادی - ادامه پایش"

            c = ws.cell(row=row, column=1, value=msg)
            c.font = Font(name="B Nazanin", size=14, bold=True, color=fg)
            c.fill = PatternFill("solid", fgColor=bg)
            c.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[row].height = 30

            # توضیح هشدار
            row = 17
            ws.merge_cells(start_row=row, end_row=row, start_column=1, end_column=7)
            c = ws.cell(row=row, column=1, value="توضیح سیگنال:")
            c.font = _subtitle_font()
            c.fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")

            row = 18
            ws.merge_cells(start_row=row, end_row=row+2, start_column=1, end_column=7)
            c = ws.cell(row=row, column=1, value=last.interpretation)
            c.font = Font(name="B Nazanin", size=11)
            c.fill = PatternFill("solid", fgColor=Colors.ALERT_BG)
            c.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
            c.border = _border()
            ws.row_dimensions[row].height = 22
            ws.row_dimensions[row+1].height = 22
            ws.row_dimensions[row+2].height = 22

            # ----- رویدادهای هشدار -----
            row = 22
            ws.merge_cells(start_row=row, end_row=row, start_column=1, end_column=7)
            c = ws.cell(row=row, column=1, value=f"رویدادهای هشدار ({len(alert_events)} مورد)")
            c.font = _subtitle_font()
            c.fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")

            # هدر جدول هشدارها
            row = 23
            headers = ["زمان", "سطح", "عنوان", "پیام", "فشار فروش", "جمع‌آوری", "طبقه‌بندی", "اقدام پیشنهادی"]
            for i, h in enumerate(headers, 1):
                c = ws.cell(row=row, column=i, value=h)
                c.font = _header_font()
                c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()
            ws.row_dimensions[row].height = 22
            _write_en_field_row(ws, row, DASH_ALERT_EN)

            # ردیف‌های هشدار
            for i, ev in enumerate(alert_events):
                r = 25 + i
                vals = [
                    ev.timestamp,
                    ev.level.value,
                    ev.title,
                    ev.message,
                    f"{ev.sell_score:.0f}",
                    f"{ev.buy_score:.0f}",
                    ev.classification,
                    ev.suggested_action,
                ]
                # رنگ بر اساس سطح
                if ev.level == AlertLevel.RED:
                    bg = Colors.CRITICAL; fg = "FFFFFF"
                elif ev.level == AlertLevel.PURPLE:
                    bg = Colors.ORANGE; fg = "FFFFFF"
                elif ev.level == AlertLevel.GREEN:
                    bg = Colors.GREEN_ALERT; fg = "FFFFFF"
                elif ev.level == AlertLevel.EARLY_SELL:
                    bg = Colors.WARNING; fg = "1F4E78"
                elif ev.level == AlertLevel.EARLY_BUY:
                    bg = Colors.GREEN_ALERT; fg = "1F4E78"
                elif ev.level == AlertLevel.WATCH:
                    bg = Colors.WARNING; fg = "1F4E78"
                else:
                    bg = Colors.NEUTRAL; fg = "1F4E78"

                for j, v in enumerate(vals, 1):
                    c = ws.cell(row=r, column=j, value=v)
                    # فقط ستون «سطح» (j==2) رنگ‌دار باشد با متن روشن؛
                    # سایر ستون‌ها متن تیره روی پس‌زمینه خنثی
                    if j == 2:
                        c.font = Font(name="B Nazanin", size=10, color=fg, bold=True)
                        c.fill = PatternFill("solid", fgColor=bg)
                    else:
                        c.font = Font(name="B Nazanin", size=10, color="1F4E78",
                                      bold=(j == 3))
                        c.fill = PatternFill("solid", fgColor=Colors.NEUTRAL)
                    c.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
                    c.border = _border()

            # ----- نمودار روند امتیازها -----
            chart_row = 25 + len(alert_events) + 2
            ws.merge_cells(start_row=chart_row, end_row=chart_row, start_column=1, end_column=7)
            c = ws.cell(row=chart_row, column=1, value="روند امتیاز فشار فروش و جمع‌آوری")
            c.font = _subtitle_font()
            c.fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")

            # داده‌های نمودار را در یک ناحیه کمکی قرار می‌دهیم
            data_start = chart_row + 2
            ws.cell(row=data_start, column=1, value="نمونه").font = _header_font()
            ws.cell(row=data_start, column=2, value="فشار فروش").font = _header_font()
            ws.cell(row=data_start, column=3, value="جمع‌آوری").font = _header_font()
            # درصد نوسان قیمت (نسبت به قیمت دیروز) — مشابه شیت Snapshots (در انتهای جدول)
            ws.cell(row=data_start, column=4, value="٪ نوسان لحظه‌ای").font = _header_font()
            ws.cell(row=data_start, column=5, value="٪ نوسان پایانی").font = _header_font()
            # حرکت اخیر قیمت (Δ30ث) — معیاری که امتیازها با آن همخوان است
            ws.cell(row=data_start, column=6, value="Δ30ث قیمت٪").font = _header_font()
            for col in (1, 2, 3, 4, 5, 6):
                ws.cell(row=data_start, column=col).fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
                ws.cell(row=data_start, column=col).font = _header_font()
                ws.cell(row=data_start, column=col).alignment = Alignment(horizontal="center")
            _write_en_field_row(ws, data_start, DASH_TREND_EN)

            for i, (sp, acc) in enumerate(zip(sp_results, acc_results), 1):
                ws.cell(row=data_start + 1 + i, column=1, value=i)
                ws.cell(row=data_start + 1 + i, column=2, value=round(sp.total_score, 1))
                ws.cell(row=data_start + 1 + i, column=3, value=round(acc.total_score, 1))
                # snapshot متناظر با این نمونه (برای محاسبه درصد نوسان)
                snap = snapshots[i - 1] if i - 1 < len(snapshots) else None
                prev_snap = snapshots[i - 2] if i - 2 >= 0 and (i - 2) < len(snapshots) else None
                yest = snap.yesterday_price if snap else 0
                pct_last = (round((snap.last_price - yest) / yest * 100, 2)
                            if snap and yest else None)
                pct_close = (round((snap.close_price - yest) / yest * 100, 2)
                             if snap and yest else None)
                delta_30s = _delta_30s_pct(snap, prev_snap)
                ws.cell(row=data_start + 1 + i, column=4, value=pct_last)
                ws.cell(row=data_start + 1 + i, column=5, value=pct_close)
                dcell = ws.cell(row=data_start + 1 + i, column=6, value=delta_30s)
                dcell.fill = PatternFill("solid", fgColor=_delta_color(delta_30s))

            # ساخت نمودار خطی
            chart = LineChart()
            chart.title = "روند امتیازها (دابور)"
            chart.style = 12
            chart.y_axis.title = "امتیاز (۰-۱۰۰)"
            chart.x_axis.title = "نمونه زمانی"
            chart.height = 9
            chart.width = 18

            data_ref = Reference(ws, min_col=2, min_row=data_start,
                                  max_col=3, max_row=data_start + 1 + len(sp_results))
            cats_ref = Reference(ws, min_col=1, min_row=data_start + 2,
                                  max_row=data_start + 1 + len(sp_results))
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)

            ws.add_chart(chart, f"E{chart_row}")

    # -----------------------------------------------------------------
    # شیت ۲: BuySellPressure (دوطرفه — ادغام فشار فروش و فشار خرید)
    # -----------------------------------------------------------------
    def _build_buysell_pressure_sheet(self, sp_results: List[SellPressureResult],
                                      acc_results: List[AccumulationResult],
                                      snapshots: List):
        """فشار فروش و فشار خرید در یک شیت، کنار هم.
        ستون‌ها: زمان، ۶ شاخص فروش، ۶ شاخص خرید، مجموع/سطح هر سمت، امتیاز کلی،
        Δ30ث، ٪ نوسان لحظه‌ای/پایانی، و تجمعی ۵/۱۵ دقیقه هر دو سمت.
        ردیف ۳: هدر فارسی، ردیف ۴: نام فیلد انگلیسی، داده از ردیف ۵.
        """
        from datetime import datetime as _dt
        ws = self.wb.create_sheet("BuySellPressure")
        ws.sheet_view.rightToLeft = True

        n_cols = len(BUYSELLPRESSURE_FA)
        # عنوان
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
        c = ws["A1"]
        c.value = "موتور تشخیص فشار خرید و فروش (دوطرفه) — شش شاخص هر سمت"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        # ردیف ۳: هدر فارسی
        for i, h in enumerate(BUYSELLPRESSURE_FA, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = _header_font()
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = _border()
        ws.row_dimensions[3].height = 40
        # ردیف ۴: نام فیلد انگلیسی
        _write_en_field_row(ws, 3, BUYSELLPRESSURE_EN)
        for i, w in enumerate(BUYSELLPRESSURE_WIDTHS, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.freeze_panes = "B5"

        # زمان‌ها برای تجمعی پنجره‌ای (۵/۱۵ دقیقه)
        def _to_sec(t):
            try:
                d = _dt.strptime(str(t).split()[-1][:8], "%H:%M:%S")
                return d.hour * 3600 + d.minute * 60 + d.second
            except Exception:
                return None
        sp_sec = [_to_sec(r.snapshot_time) for r in sp_results]
        acc_sec = [_to_sec(r.snapshot_time) for r in acc_results]

        def _window_avg(results, secs, idx, window_sec):
            t0 = secs[idx]
            if t0 is None:
                return None
            picked = [results[j].total_score for j in range(idx + 1)
                      if secs[j] is not None and (t0 - secs[j]) <= window_sec]
            return round(sum(picked) / len(picked), 1) if picked else None

        n = max(len(sp_results), len(acc_results))
        for i in range(n):
            sp = sp_results[i] if i < len(sp_results) else None
            acc = acc_results[i] if i < len(acc_results) else None
            snap = snapshots[i] if i < len(snapshots) else None
            prev_snap = snapshots[i - 1] if i > 0 and (i - 1) < len(snapshots) else None

            sp_total = sp.total_score if sp else None
            acc_total = acc.total_score if acc else None
            overall = None
            if sp_total is not None and acc_total is not None:
                overall = round(min(max(50 + 0.5 * (acc_total - sp_total), 0), 100), 1)

            yest = snap.yesterday_price if snap else 0
            pct_last = (round((snap.last_price - yest) / yest * 100, 2) if snap and yest else None)
            pct_close = (round((snap.close_price - yest) / yest * 100, 2) if snap and yest else None)
            delta_30s = _delta_30s_pct(snap, prev_snap)

            sell_cum5 = _window_avg(sp_results, sp_sec, i, 300)
            buy_cum5 = _window_avg(acc_results, acc_sec, i, 300)
            sell_cum15 = _window_avg(sp_results, sp_sec, i, 900)
            buy_cum15 = _window_avg(acc_results, acc_sec, i, 900)

            row_data = [sp.snapshot_time if sp else (acc.snapshot_time if acc else None)]
            for k in range(6):
                row_data.append(round(sp.factors[k].score, 1) if sp and len(sp.factors) > k else None)
            for k in range(6):
                row_data.append(round(acc.factors[k].score, 1) if acc and len(acc.factors) > k else None)
            row_data += [
                round(sp_total, 1) if sp_total is not None else None,
                sp.level if sp else None,
                round(acc_total, 1) if acc_total is not None else None,
                acc.level if acc else None,
                overall, delta_30s, pct_last, pct_close,
                sell_cum5, buy_cum5, sell_cum15, buy_cum15,
            ]

            r = 5 + i
            for j, v in enumerate(row_data, 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()
                # ستون‌های شاخص فشار فروش (۲..۷)
                if 2 <= j <= 7 and sp and len(sp.factors) >= j - 1:
                    f = sp.factors[j - 2]
                    c.fill = PatternFill("solid", fgColor=(
                        Colors.DANGER if f.normalized >= 0.66 else
                        Colors.WATCH if f.normalized >= 0.33 else Colors.NORMAL))
                # ستون‌های شاخص فشار خرید (۸..۱۳)
                elif 8 <= j <= 13 and acc and len(acc.factors) >= j - 7:
                    f = acc.factors[j - 8]
                    c.fill = PatternFill("solid", fgColor=(
                        Colors.GREEN_ALERT if f.normalized >= 0.66 else
                        Colors.WATCH if f.normalized >= 0.33 else Colors.NEUTRAL))
                elif j == 14 and sp_total is not None:    # مجموع فشار فروش
                    c.fill = PatternFill("solid", fgColor=_score_color(sp_total))
                    c.font = Font(name="B Nazanin", size=11, bold=True)
                elif j == 15 and sp_total is not None:     # سطح فشار فروش
                    c.fill = PatternFill("solid", fgColor=_score_color(sp_total))
                elif j == 16 and acc_total is not None:    # مجموع جمع‌آوری
                    c.fill = PatternFill("solid", fgColor=_acc_color(acc_total))
                    c.font = Font(name="B Nazanin", size=11, bold=True)
                elif j == 17 and acc_total is not None:    # سطح جمع‌آوری
                    c.fill = PatternFill("solid", fgColor=_acc_color(acc_total))
                elif j == 18 and overall is not None:      # امتیاز کلی
                    col = _score_color(overall) if overall < 50 else _acc_color(overall)
                    c.fill = PatternFill("solid", fgColor=col)
                    c.font = Font(name="B Nazanin", size=11, bold=True)
                elif j == 19:                              # Δ30ث
                    c.fill = PatternFill("solid", fgColor=_delta_color(delta_30s))
                elif j in (20, 21):                        # ٪ نوسان لحظه‌ای/پایانی
                    c.fill = PatternFill("solid", fgColor=_delta_color(v))

        # نمودار ستونی: تجزیهٔ امتیاز دو طرف (آخرین نمونه)
        if sp_results or acc_results:
            chart_data_row = 5 + n + 2
            ws.cell(row=chart_data_row, column=1, value="شاخص").font = _header_font()
            ws.cell(row=chart_data_row, column=2, value="امتیاز").font = _header_font()
            ws.cell(row=chart_data_row, column=3, value="حداکثر").font = _header_font()
            for col in (1, 2, 3):
                ws.cell(row=chart_data_row, column=col).fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
                ws.cell(row=chart_data_row, column=col).font = _header_font()
                ws.cell(row=chart_data_row, column=col).alignment = Alignment(horizontal="center")
            last_sp = sp_results[-1] if sp_results else None
            last_acc = acc_results[-1] if acc_results else None
            rows_chart = []
            if last_sp:
                for f in last_sp.factors:
                    rows_chart.append((f.label, round(f.score, 1), f.max_points))
            if last_acc:
                for f in last_acc.factors:
                    rows_chart.append((f.label, round(f.score, 1), f.max_points))
            for k, (lab, sc, mx) in enumerate(rows_chart):
                rr = chart_data_row + 1 + k
                ws.cell(row=rr, column=1, value=lab)
                ws.cell(row=rr, column=2, value=sc)
                ws.cell(row=rr, column=3, value=mx)
            chart = BarChart()
            chart.type = "bar"; chart.style = 12
            chart.title = "تجزیهٔ امتیاز فشار فروش و خرید (آخرین نمونه)"
            chart.y_axis.title = "شاخص"; chart.x_axis.title = "امتیاز"
            chart.height = 12; chart.width = 24
            kk = max(len(rows_chart), 1)
            data_ref = Reference(ws, min_col=2, min_row=chart_data_row,
                                 max_col=3, max_row=chart_data_row + kk)
            cats_ref = Reference(ws, min_col=1, min_row=chart_data_row + 1,
                                 max_row=chart_data_row + kk)
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)
            ws.add_chart(chart, f"{get_column_letter(n_cols + 2)}3")


    # -----------------------------------------------------------------
    # شیت ۳.۵: 5min Trend (تجمیع ۵دقیقه‌ای — روند سیگنال vs حرکت قیمت)
    # -----------------------------------------------------------------
    def _build_5min_trend_sheet(self, sp_results: List[SellPressureResult],
                                acc_results: List[AccumulationResult],
                                snapshots: List):
        """تجمیع نمونه‌های ۳۰ثانیه‌ای در بازه‌های ۵دقیقه‌ای.

        هر ردیف = یک بازهٔ ۵دقیقه‌ای با:
          - قیمت ابتدا/انتها و Δقیمت همان بازه (نه نسبت به دیروز)
          - میانگین فشار فروش/جمع‌آوری و net = جمع‌آوری − فشار فروش
          - نشانگر همخوانی جهت net با Δقیمت

        این نما نویز ۳۰ثانیه‌ای را هموار می‌کند و چون هم سیگنال و هم قیمت در
        همان پنجرهٔ ۵دقیقه‌ای سنجیده می‌شوند، مقایسهٔ روند معنادار می‌شود.
        """
        import statistics as _st
        from datetime import datetime as _dt

        ws = self.wb.create_sheet("5min_Trend")
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "A5"

        # عنوان
        ws.merge_cells("A1:M1")
        c = ws["A1"]
        c.value = "روند تجمیع‌شدهٔ ۵دقیقه‌ای — سیگنال vs حرکت قیمت"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        # توضیح
        ws.merge_cells("A2:M2")
        c = ws["A2"]
        c.value = ("Δقیمت٪ = تغییر قیمت درون همان بازهٔ ۵دقیقه‌ای (نه نسبت به دیروز). "
                   "net = جمع‌آوری − فشار فروش. همخوانی ✓ یعنی جهت net با جهت Δقیمت سازگار است.")
        c.font = Font(name="B Nazanin", size=9, color="333333")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.row_dimensions[2].height = 18

        headers = [
            "بازه", "n", "قیمت ابتدا", "قیمت انتها",
            "Δقیمت ۵دقیقه٪", "avg فشار فروش", "avg جمع‌آوری",
            "net سیگنال", "بیشینه فشار", "حجم معاملات", "همخوانی",
            "٪ نوسان لحظه‌ای", "٪ نوسان پایانی",
        ]
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = _header_font()
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = _border()
        ws.row_dimensions[3].height = 34
        _write_en_field_row(ws, 3, TREND5_EN)

        widths = [14, 5, 11, 11, 13, 13, 12, 10, 11, 14, 9, 9, 9]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        # تجمیع در bucketهای ۵دقیقه‌ای
        def _to_sec(t):
            try:
                d = _dt.strptime(str(t), "%H:%M:%S")
                return d.hour * 3600 + d.minute * 60 + d.second
            except Exception:
                return None

        buckets = {}  # bucket_id -> list of indices
        n = min(len(snapshots), len(sp_results), len(acc_results))
        for idx in range(n):
            s = _to_sec(snapshots[idx].tehran_time)
            if s is None:
                continue
            buckets.setdefault(s // 300, []).append(idx)

        aligned = 0
        total = 0
        r = 5
        for b in sorted(buckets):
            idxs = buckets[b]
            grp_snaps = [snapshots[i] for i in idxs]
            start_price = grp_snaps[0].last_price
            end_price = grp_snaps[-1].last_price
            if start_price and end_price and start_price > 0:
                dpct = round((end_price - start_price) / start_price * 100, 2)
            else:
                dpct = None
            sells = [sp_results[i].total_score for i in idxs]
            buys = [acc_results[i].total_score for i in idxs]
            asell = round(_st.mean(sells), 1) if sells else 0.0
            abuy = round(_st.mean(buys), 1) if buys else 0.0
            net = round(abuy - asell, 1)
            mxsell = round(max(sells), 1) if sells else 0.0
            # حجم معاملات بازه = تفاضل حجم تجمعی (آخر − اول)؛ اگر ریست شد، آخرین
            vols = [s.total_volume for s in grp_snaps if s.total_volume]
            if len(vols) >= 2 and vols[-1] >= vols[0]:
                vol_traded = vols[-1] - vols[0]
            elif vols:
                vol_traded = vols[-1]
            else:
                vol_traded = 0

            # همخوانی جهت net با جهت Δقیمت
            if dpct is None or abs(dpct) <= 0.1:
                flag = "─"
                total += 1
            elif (dpct > 0.1 and net > 0) or (dpct < -0.1 and net < 0):
                flag = "✓"
                aligned += 1
                total += 1
            else:
                flag = "✗"
                total += 1

            t0 = str(grp_snaps[0].tehran_time)[:5]
            t1 = str(grp_snaps[-1].tehran_time)[:5]
            end_snap = grp_snaps[-1]
            yest_e = end_snap.yesterday_price
            pct_last_b = (round((end_snap.last_price - yest_e) / yest_e * 100, 2)
                          if yest_e else None)
            pct_close_b = (round((end_snap.close_price - yest_e) / yest_e * 100, 2)
                           if yest_e else None)
            row_data = [
                f"{t0}-{t1}", len(idxs), start_price, end_price,
                dpct, asell, abuy, net, mxsell, vol_traded, flag,
                pct_last_b, pct_close_b,
            ]
            for j, v in enumerate(row_data, 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()
            # رنگ Δقیمت (ستون ۵)
            if dpct is not None:
                dcol = (Colors.DANGER if dpct < -0.1
                        else (Colors.GREEN_ALERT if dpct > 0.1 else Colors.NEUTRAL))
                ws.cell(row=r, column=5).fill = PatternFill("solid", fgColor=dcol)
            # رنگ net (ستون ۸)
            ncol = (Colors.DANGER if net < -5
                    else (Colors.GREEN_ALERT if net > 5 else Colors.NEUTRAL))
            ws.cell(row=r, column=8).fill = PatternFill("solid", fgColor=ncol)
            # رنگ avg فشار فروش (ستون ۶) و avg جمع‌آوری (ستون ۷)
            ws.cell(row=r, column=6).fill = PatternFill("solid", fgColor=_score_color(asell))
            ws.cell(row=r, column=7).fill = PatternFill("solid", fgColor=_acc_color(abuy))
            # رنگ ٪ نوسان لحظه‌ای/پایانی (ستون‌های ۱۲ و ۱۳)
            for pct_col in (12, 13):
                v = ws.cell(row=r, column=pct_col).value
                if v is None:
                    continue
                ws.cell(row=r, column=pct_col).fill = PatternFill(
                    "solid",
                    fgColor=(Colors.GREEN_ALERT if v > 0 else
                             Colors.DANGER if v < 0 else Colors.NEUTRAL))
            r += 1

        # خلاصه
        if total:
            sr = r + 1
            ws.merge_cells(start_row=sr, end_row=sr, start_column=1, end_column=13)
            c = ws.cell(row=sr, column=1, value="خلاصه")
            c.font = _subtitle_font()
            c.fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")
            notes = [
                f"بازه‌های ۵دقیقه‌ای: {total}",
                f"همخوانی net با جهت Δقیمت: {aligned}/{total} = {aligned/total*100:.0f}٪",
                "نکته: امتیاز فشار فروش/جمع‌آوری با Δ30ث (حرکت اخیر قیمت) همخوان است، "
                "نه با «٪ نوسان لحظه‌ای» (نسبت به دیروز). ستون Δ30ث قیمت در شیت‌های "
                "SellPressure/Accumulation/History این همخوانی را در سطح نمونه نشان می‌دهد.",
            ]
            for i, note in enumerate(notes):
                rr = sr + 1 + i
                ws.merge_cells(start_row=rr, end_row=rr, start_column=1, end_column=13)
                c = ws.cell(row=rr, column=1, value=note)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)

    # -----------------------------------------------------------------
    # شیت ۴: History
    # -----------------------------------------------------------------
    def _build_history_sheet(self, snapshots: List, combined_states: List[CombinedState]):
        ws = self.wb.create_sheet("History")
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "A5"

        # عنوان
        ws.merge_cells("A1:Q1")
        c = ws["A1"]
        c.value = "تاریخچه کامل نمونه‌های زمانی"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        headers = [
            "زمان", "آخرین قیمت", "قیمت پایانی",
            "بهترین خرید", "حجم خرید",
            "بهترین فروش", "حجم فروش", "حجم معاملات", "ارزش معاملات",
            "قدرت خریدار", "ورود/خروج پول حقیقی", "فشار فروش", "جمع‌آوری", "وضعیت",
            # حرکت اخیر قیمت (Δ30ث) — معیاری که sell_score/buy_score با آن همخوان است
            "Δ30ث قیمت٪",
            # درصد نوسان قیمت (نسبت به قیمت دیروز) — در انتهای جدول
            "٪ نوسان لحظه‌ای", "٪ نوسان پایانی",
        ]
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = _header_font()
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = _border()
        ws.row_dimensions[3].height = 30
        _write_en_field_row(ws, 3, HISTORY_EN)

        widths = [12, 12, 12, 12, 12, 12, 12, 14, 16, 12, 16, 12, 12, 22, 10, 9, 9]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        for i, (snap, state) in enumerate(zip(snapshots, combined_states)):
            r = 5 + i
            money_flow = snap.real_money_flow
            money_label = f"{money_flow/1e9:+.2f} میلیارد"
            if abs(money_flow) < 1e9:
                money_label = f"{money_flow/1e6:+.1f} میلیون"
            yest = snap.yesterday_price
            pct_last = (round((snap.last_price - yest) / yest * 100, 2) if yest else None)
            pct_close = (round((snap.close_price - yest) / yest * 100, 2) if yest else None)
            prev_snap = snapshots[i - 1] if i > 0 else None
            delta_30s = _delta_30s_pct(snap, prev_snap)

            row_data = [
                snap.tehran_time,
                snap.last_price,
                snap.close_price,
                snap.best_buy_price,
                snap.best_buy_volume,
                snap.best_sell_price,
                snap.best_sell_volume,
                snap.total_volume,
                snap.total_value,
                round(snap.buyer_power, 2),
                money_label,
                round(state.sell_score, 1),
                round(state.buy_score, 1),
                state.combination_label,
                delta_30s,
                pct_last, pct_close,
            ]
            for j, v in enumerate(row_data, 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()

            # رنگ فشار فروش (ستون ۱۲)
            ws.cell(row=r, column=12).fill = PatternFill(
                "solid", fgColor=_score_color(state.sell_score)
            )
            # رنگ فشار خرید (ستون ۱۳)
            ws.cell(row=r, column=13).fill = PatternFill(
                "solid", fgColor=_acc_color(state.buy_score)
            )
            # رنگ Δ30ث قیمت (ستون ۱۵) — قرمز=افت، سبز=رشد
            ws.cell(row=r, column=15).fill = PatternFill(
                "solid", fgColor=_delta_color(delta_30s)
            )

        # جدول خلاصه در پایان
        summary_row = 5 + len(snapshots) + 2
        ws.cell(row=summary_row, column=1, value="خلاصه").font = _subtitle_font()
        ws.cell(row=summary_row, column=1).fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
        ws.merge_cells(start_row=summary_row, end_row=summary_row, start_column=1, end_column=4)

        if combined_states:
            max_sp = max(s.sell_score for s in combined_states)
            max_acc = max(s.buy_score for s in combined_states)
            avg_sp = sum(s.sell_score for s in combined_states) / len(combined_states)
            avg_acc = sum(s.buy_score for s in combined_states) / len(combined_states)

            summary_data = [
                ("بیشینه فشار فروش", round(max_sp, 1)),
                ("میانگین فشار فروش", round(avg_sp, 1)),
                ("بیشینه جمع‌آوری", round(max_acc, 1)),
                ("میانگین جمع‌آوری", round(avg_acc, 1)),
                ("تعداد نمونه‌ها", len(snapshots)),
            ]
            for i, (k, v) in enumerate(summary_data):
                r = summary_row + 1 + i
                ws.cell(row=r, column=1, value=k).font = _body_font()
                ws.cell(row=r, column=2, value=v).font = _body_font()
                ws.cell(row=r, column=1).border = _border()
                ws.cell(row=r, column=2).border = _border()

    # -----------------------------------------------------------------
    # شیت ۴: Snapshots (داده خام - گروه‌های A تا D و F)
    # -----------------------------------------------------------------
    def _build_snapshots_sheet(self, snapshots: List[MarketSnapshot]):
        ws = self.wb.create_sheet("Snapshots")
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "B5"

        # عنوان
        ws.merge_cells("A1:BL1")
        c = ws["A1"]
        c.value = "Snapshots - داده خام تابلو (هر ۶۰ ثانیه یک ردیف)"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        # هدر جدول - شامل تمام فیلدهای گروه A تا D و F
        headers = [
            # گروه F - وضعیت بازار
            "تاریخ شمسی", "زمان دقیق", "نماد", "فاز بازار", "وضعیت نماد",
            "وضعیت داده", "خطای دریافت",
            # گروه A - قیمت‌ها
            "آخرین قیمت", "قیمت پایانی", "اولین قیمت", "قیمت دیروز",
            "بالاترین روز", "پایین‌ترین روز", "کف مجاز", "سقف مجاز",
            # گروه B - بهترین قیمت و مجموع
            "بهترین خرید", "حجم خرید", "بهترین فروش", "حجم فروش",
            "تعداد سفارش خرید", "تعداد سفارش فروش",
            # پنج ردیف خرید
            "bid_price_1", "bid_vol_1", "bid_count_1",
            "bid_price_2", "bid_vol_2", "bid_count_2",
            "bid_price_3", "bid_vol_3", "bid_count_3",
            "bid_price_4", "bid_vol_4", "bid_count_4",
            "bid_price_5", "bid_vol_5", "bid_count_5",
            # پنج ردیف فروش
            "ask_price_1", "ask_vol_1", "ask_count_1",
            "ask_price_2", "ask_vol_2", "ask_count_2",
            "ask_price_3", "ask_vol_3", "ask_count_3",
            "ask_price_4", "ask_vol_4", "ask_count_4",
            "ask_price_5", "ask_vol_5", "ask_count_5",
            # گروه C - تجمعی
            "حجم کل", "ارزش کل", "تعداد معامله کل", "حجم مبنا",
            "حجم بازه", "ارزش بازه", "تعداد بازه",
            # گروه D - حقیقی/حقوقی
            "خریداران حقیقی", "حجم خرید حقیقی", "ارزش خرید حقیقی",
            "فروشندگان حقیقی", "حجم فروش حقیقی", "ارزش فروش حقیقی",
            "خریداران حقوقی", "حجم خرید حقوقی", "ارزش خرید حقوقی",
            "فروشندگان حقوقی", "حجم فروش حقوقی", "ارزش فروش حقوقی",
            "حجم خرید حقیقی بازه", "حجم فروش حقیقی بازه",
            # شاخص‌های مشتق
            "قدرت خریدار", "سرانه خرید", "سرانه فروش",
            "ورود/خروج پول حقیقی", "نسبت پول حقیقی",
            # کیفیت داده
            "داده کامل", "فیلدهای مفقود",
            # درصد نوسان قیمت (نسبت به قیمت دیروز) — در انتهای جدول
            "٪ نوسان لحظه‌ای", "٪ نوسان پایانی",
        ]
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = _header_font()
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = _border()
        ws.row_dimensions[3].height = 32
        _write_en_field_row(ws, 3, SNAPSHOTS_EN)

        # عرض ستون‌ها - ستون‌های اصلی پهن‌تر
        col_widths = [11, 9, 7, 8, 8, 8, 10,
                       10, 10, 10, 10, 10, 10, 10, 10,
                       10, 10, 10, 10, 10, 10,
                       9, 8, 7, 9, 8, 7, 9, 8, 7, 9, 8, 7, 9, 8, 7,
                       9, 8, 7, 9, 8, 7, 9, 8, 7, 9, 8, 7, 9, 8, 7,
                       12, 14, 10, 10,
                       10, 12, 8,
                       10, 10, 12, 10, 10, 12,
                       10, 10, 12, 10, 10, 12,
                       12, 12,
                       10, 10, 10, 14, 10,
                       8, 12,
                       9, 9]  # ٪ نوسان لحظه‌ای و پایانی (در انتهای جدول)
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        # داده‌ها
        phase_label_map = {
            "pre_open": "پیش‌گشایش",
            "continuous": "پیوسته",
            "halted": "متوقف",
            "suspended": "ممنوع",
            "closed": "بسته",
        }
        for i, snap in enumerate(snapshots):
            r = 5 + i
            bid_prices = [row.price for row in snap.buy_rows]
            bid_volumes = [row.volume for row in snap.buy_rows]
            bid_counts = [row.order_count for row in snap.buy_rows]
            ask_prices = [row.price for row in snap.sell_rows]
            ask_volumes = [row.volume for row in snap.sell_rows]
            ask_counts = [row.order_count for row in snap.sell_rows]

            # پنج ردیف را به ۵ مقدار گسترش بدهیم (با None اگر کمتر از ۵ ردیف موجود است)
            def _pad(lst, n=5):
                return (lst + [None] * n)[:n]

            row_data = [
                snap.date_jalali, snap.tehran_time, snap.symbol,
                phase_label_map.get(snap.market_phase, snap.market_phase),
                snap.symbol_status, snap.data_status, snap.fetch_error,
                snap.last_price, snap.close_price, snap.open_price, snap.yesterday_price,
                snap.daily_high, snap.daily_low, snap.min_allowed_price, snap.max_allowed_price,
                snap.best_buy_price, snap.best_buy_volume, snap.best_sell_price, snap.best_sell_volume,
                snap.buy_order_count, snap.sell_order_count,
                *(_pad(bid_prices) + _pad(bid_volumes) + _pad(bid_counts)),
                *(_pad(ask_prices) + _pad(ask_volumes) + _pad(ask_counts)),
                snap.total_volume, snap.total_value, snap.total_trade_count, snap.base_volume,
                snap.interval_volume, snap.interval_value, snap.interval_trade_count,
                snap.real_buy_count, snap.real_buy_volume, snap.real_buy_value,
                snap.real_sell_count, snap.real_sell_volume, snap.real_sell_value,
                snap.legal_buy_count, snap.legal_buy_volume, snap.legal_buy_value,
                snap.legal_sell_count, snap.legal_sell_volume, snap.legal_sell_value,
                snap.interval_real_buy_volume, snap.interval_real_sell_volume,
                round(snap.buyer_power, 2), round(snap.per_capita_buy_real, 1),
                round(snap.per_capita_sell_real, 1),
                round(snap.real_money_flow, 0), round(snap.real_money_flow_ratio, 4),
                "بله" if snap.data_complete else "خیر",
                ", ".join(snap.missing_fields) if snap.missing_fields else "",
                # درصد نوسان قیمت نسبت به قیمت دیروز (در انتهای جدول)
                round((snap.last_price - snap.yesterday_price) / snap.yesterday_price * 100, 2)
                    if snap.yesterday_price else None,
                round((snap.close_price - snap.yesterday_price) / snap.yesterday_price * 100, 2)
                    if snap.yesterday_price else None,
            ]
            for j, v in enumerate(row_data, 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()

            # رنگ‌دهی بر اساس فاز بازار
            phase = snap.market_phase
            phase_color = {
                "pre_open": "FFE4B5",     # نارنجی کمرنگ
                "continuous": "F2F2F2",    # خاکستری روشن
                "halted": "FFC000",        # نارنجی
                "suspended": "C00000",     # قرمز
                "closed": "BFBFBF",        # خاکستری
            }.get(phase, "F2F2F2")
            ws.cell(row=r, column=4).fill = PatternFill("solid", fgColor=phase_color)

            # رنگ‌دهی بر اساس data_status
            if snap.data_status != "ok":
                ws.cell(row=r, column=6).fill = PatternFill("solid", fgColor=Colors.WARNING)
            # رنگ‌دهی ورود/خروج پول (ستون بعد از شیفت ۲ ستونی = ۶۶)
            if snap.real_money_flow > 0:
                ws.cell(row=r, column=66).fill = PatternFill("solid", fgColor=Colors.NORMAL)
            elif snap.real_money_flow < 0:
                ws.cell(row=r, column=66).fill = PatternFill("solid", fgColor=Colors.DANGER)

            # رنگ‌دهی درصد نوسان (ستون ۱۶ = لحظه‌ای، ۱۷ = پایانی)
            for pct_col in (16, 17):
                v = ws.cell(row=r, column=pct_col).value
                if v is None:
                    continue
                if v > 0:
                    ws.cell(row=r, column=pct_col).fill = PatternFill("solid", fgColor=Colors.NORMAL)
                elif v < 0:
                    ws.cell(row=r, column=pct_col).fill = PatternFill("solid", fgColor=Colors.DANGER)

    # -----------------------------------------------------------------
    # شیت ۵: Trades (گروه E - معاملات انجام‌شده)
    # -----------------------------------------------------------------
    def _build_trades_sheet(self, trades: List[Trade], symbol: str,
                             yesterday_price: float = 0):
        ws = self.wb.create_sheet("Trades")
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "B5"

        # عنوان
        ws.merge_cells("A1:H1")
        c = ws["A1"]
        c.value = f"Trades - معاملات انجام‌شده نماد {symbol}"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        # هدر
        headers = ["ردیف", "زمان معامله", "قیمت معامله",
                   "حجم معامله", "شناسه معامله", "سمت آغازگر",
                   # درصد نوسان قیمت (نسبت به قیمت دیروز) — مشابه شیت Snapshots (در انتهای جدول)
                   "٪ نوسان لحظه‌ای", "٪ نوسان پایانی"]
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = _header_font()
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = _border()
        ws.row_dimensions[3].height = 24
        _write_en_field_row(ws, 3, TRADES_EN)

        widths = [7, 12, 14, 12, 18, 12, 9, 9]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        # داده‌ها
        for i, tr in enumerate(trades):
            r = 5 + i
            aggressor_label = {"buy": "خرید", "sell": "فروش"}.get(
                tr.aggressor_side, "نامشخص"
            )
            # درصد نوسان قیمت معامله نسبت به قیمت دیروز
            pct = (round((tr.trade_price - yesterday_price) / yesterday_price * 100, 2)
                   if yesterday_price else None)
            row_data = [
                i + 1,
                tr.trade_time,
                tr.trade_price,
                tr.trade_volume,
                tr.trade_id,
                aggressor_label,
                pct, pct,  # معامله یک قیمت دارد → هر دو ستون یکسان
            ]
            for j, v in enumerate(row_data, 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()
            # رنگ سمت آغازگر (ستون ۶)
            if tr.aggressor_side == "buy":
                ws.cell(row=r, column=6).fill = PatternFill("solid", fgColor=Colors.NORMAL)
            elif tr.aggressor_side == "sell":
                ws.cell(row=r, column=6).fill = PatternFill("solid", fgColor=Colors.DANGER)

        # خلاصه پایانی
        if trades:
            summary_row = 5 + len(trades) + 2
            ws.cell(row=summary_row, column=1, value="خلاصه").font = _subtitle_font()
            ws.cell(row=summary_row, column=1).fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
            ws.merge_cells(start_row=summary_row, end_row=summary_row, start_column=1, end_column=8)

            total_vol = sum(t.trade_volume for t in trades)
            total_val = sum(t.trade_price * t.trade_volume for t in trades)
            avg_price = total_val / max(total_vol, 1)
            buy_count = sum(1 for t in trades if t.aggressor_side == "buy")
            sell_count = sum(1 for t in trades if t.aggressor_side == "sell")

            summary_data = [
                ("تعداد کل معاملات", len(trades)),
                ("حجم کل", total_vol),
                ("ارزش کل", round(total_val, 0)),
                ("میانگین قیمت", round(avg_price, 2)),
                ("معاملات خرید آغازگر", buy_count),
                ("معاملات فروش آغازگر", sell_count),
            ]
            for i, (k, v) in enumerate(summary_data):
                r = summary_row + 1 + i
                ws.cell(row=r, column=1, value=k).font = _body_font()
                ws.cell(row=r, column=2, value=v).font = _body_font()
                ws.cell(row=r, column=1).border = _border()
                ws.cell(row=r, column=2).border = _border()

    # -----------------------------------------------------------------
    # شیت ۶: Metadata
    # -----------------------------------------------------------------
    def _build_metadata_sheet(self, snapshots: List[MarketSnapshot], symbol: str,
                              source: str = "زنده (Live)"):
        ws = self.wb.create_sheet("Metadata")
        ws.sheet_view.rightToLeft = True

        # عرض ستون‌ها
        for col, w in zip("ABC", [30, 26, 60]):
            ws.column_dimensions[col].width = w

        # عنوان
        ws.merge_cells("A1:C1")
        c = ws["A1"]
        c.value = "Metadata - مشخصات نماد و جلسه معاملاتی"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        # هدر: فارسی | نام فیلد انگلیسی | مقدار
        for i, h in enumerate(["فیلد (فارسی)", "نام فیلد (English)", "مقدار"], 1):
            hc = ws.cell(row=2, column=i, value=h)
            hc.font = _header_font()
            hc.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            hc.alignment = Alignment(horizontal="center", vertical="center")
            hc.border = _border()
        ws.row_dimensions[2].height = 22

        # محاسبه خلاصه
        if snapshots:
            first = snapshots[0]
            last = snapshots[-1]
            phases = {}
            for s in snapshots:
                phases[s.market_phase] = phases.get(s.market_phase, 0) + 1
            phase_summary = "؛ ".join(f"{p}: {n} نمونه" for p, n in phases.items())
            errors = sum(1 for s in snapshots if s.data_status != "ok")
            complete_count = sum(1 for s in snapshots if s.data_complete)

            # درصد نوسان قیمت پایان روز (نسبت به قیمت دیروز)
            yest = last.yesterday_price
            pct_last_eod = round((last.last_price - yest) / yest * 100, 2) if yest else None
            pct_close_eod = round((last.close_price - yest) / yest * 100, 2) if yest else None

            meta_data = [
                ("نماد", symbol),
                ("نوع گزارش (Source)", source),
                ("کد ابزار TSETMC", first.ins_code),
                ("تاریخ شمسی", first.date_jalali),
                ("زمان شروع پایش", first.tehran_time),
                ("زمان پایان پایش", last.tehran_time),
                ("تعداد کل نمونه‌ها", len(snapshots)),
                ("نمونه‌های کامل", complete_count),
                ("نمونه‌های دارای خطا", errors),
                ("وضعیت نماد", last.symbol_status),
                ("فازهای بازار (توزیع)", phase_summary),
                ("اولین قیمت روز", first.open_price),
                ("آخرین قیمت پایان روز", last.last_price),
                ("قیمت پایانی پایان روز", last.close_price),
                ("قیمت دیروز (پایه)", last.yesterday_price),
                ("درصد نوسان قیمت لحظه‌ای (پایان روز)", pct_last_eod),
                ("درصد نوسان قیمت پایانی (پایان روز)", pct_close_eod),
                ("کف مجاز روز", last.min_allowed_price),
                ("سقف مجاز روز", last.max_allowed_price),
                ("بالاترین قیمت روز", last.daily_high),
                ("پایین‌ترین قیمت روز", last.daily_low),
                ("حجم کل معاملات روز", last.total_volume),
                ("ارزش کل معاملات روز", round(last.total_value, 0)),
                ("تعداد کل معاملات روز", last.total_trade_count),
                ("حجم مبنا", last.base_volume),
                ("واحد قیمت", "تومان (هر سهم)"),
                ("واحد حجم", "سهم (تعداد)"),
                ("منبع داده", "TSETMC - tsetmc.com"),
                ("بازه نمونه‌برداری", "۶۰ ثانیه"),
                ("نسخه موتور", "1.0"),
            ]
        else:
            meta_data = [("نماد", symbol), ("وضعیت", "داده‌ای ثبت نشده")]

        for i, (k, v) in enumerate(meta_data, 1):
            r = 2 + i
            en = METADATA_EN[i - 1] if i - 1 < len(METADATA_EN) else ""
            c = ws.cell(row=r, column=1, value=k)
            c.font = _subtitle_font()
            c.fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
            c.alignment = Alignment(horizontal="right", vertical="center")
            c.border = _border()

            c = ws.cell(row=r, column=2, value=en)
            c.font = Font(name="B Nazanin", size=9, color=EN_ROW_FG)
            c.fill = PatternFill("solid", fgColor=EN_ROW_BG)
            c.alignment = Alignment(horizontal="center", vertical="center")
            c.border = _border()

            c = ws.cell(row=r, column=3, value=str(v))
            c.font = _body_font()
            c.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
            c.border = _border()
