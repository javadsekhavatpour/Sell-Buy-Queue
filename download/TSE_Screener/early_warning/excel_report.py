"""
excel_report.py
تولید گزارش Excel با چهار شیت:
  1. Dashboard     - وضعیت لحظه‌ای و هشدارها
  2. SellPressure  - شش عامل فشار فروش و امتیازها (به‌مرور زمان)
  3. Accumulation  - شش عامل جمع‌آوری و امتیازها (به‌مرور زمان)
  4. History       - تمام نمونه‌های زمانی و تغییرات

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
from .smart_accumulation import AccumulationResult
from .alert_engine import CombinedState, AlertEvent, AlertLevel


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
        output_path: Path
    ) -> Path:
        """تولید کامل گزارش."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self._build_dashboard(
            symbol, snapshots, sp_results, acc_results,
            combined_states, alert_events
        )
        self._build_sell_pressure_sheet(sp_results)
        self._build_accumulation_sheet(acc_results)
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
            c.font = Font(name="B Nazanin", size=20, bold=True, color="1F4E78")
            c.fill = PatternFill("solid", fgColor=_score_color(last_sp.total_score))
            c.alignment = Alignment(horizontal="center", vertical="center")

            ws.merge_cells(start_row=row, end_row=row+1, start_column=5, end_column=7)
            c = ws.cell(row=row, column=5, value=last_sp.level)
            c.font = Font(name="B Nazanin", size=11, bold=True)
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
            c.font = Font(name="B Nazanin", size=20, bold=True, color="006100")
            c.fill = PatternFill("solid", fgColor=_acc_color(last_acc.total_score))
            c.alignment = Alignment(horizontal="center", vertical="center")

            ws.merge_cells(start_row=row, end_row=row+1, start_column=5, end_column=7)
            c = ws.cell(row=row, column=5, value=last_acc.level)
            c.font = Font(name="B Nazanin", size=11, bold=True)
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
                elif level == AlertLevel.ORANGE:
                    bg = Colors.ORANGE
                    fg = "FFFFFF"
                    msg = last.alert.title
                elif level == AlertLevel.GREEN:
                    bg = Colors.GREEN_ALERT
                    fg = "FFFFFF"
                    msg = last.alert.title
                elif level == AlertLevel.YELLOW:
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
            headers = ["زمان", "سطح", "عنوان", "پیام", "فشار فروش", "جمع‌آوری", "اقدام"]
            for i, h in enumerate(headers, 1):
                c = ws.cell(row=row, column=i, value=h)
                c.font = _header_font()
                c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()
            ws.row_dimensions[row].height = 22

            # ردیف‌های هشدار
            for i, ev in enumerate(alert_events):
                r = 24 + i
                vals = [
                    ev.timestamp,
                    ev.level.value,
                    ev.title,
                    ev.message,
                    f"{ev.sell_pressure_score:.0f}",
                    f"{ev.accumulation_score:.0f}",
                    ev.suggested_action,
                ]
                # رنگ بر اساس سطح
                if ev.level == AlertLevel.RED:
                    bg = Colors.CRITICAL; fg = "FFFFFF"
                elif ev.level == AlertLevel.ORANGE:
                    bg = Colors.ORANGE; fg = "FFFFFF"
                elif ev.level == AlertLevel.GREEN:
                    bg = Colors.GREEN_ALERT; fg = "FFFFFF"
                elif ev.level == AlertLevel.YELLOW:
                    bg = Colors.WARNING; fg = "1F4E78"
                else:
                    bg = Colors.NEUTRAL; fg = "1F4E78"

                for j, v in enumerate(vals, 1):
                    c = ws.cell(row=r, column=j, value=v)
                    c.font = Font(name="B Nazanin", size=10, color=fg,
                                  bold=(j in (2, 3)))
                    c.fill = PatternFill("solid", fgColor=bg if j == 2 else Colors.NEUTRAL)
                    c.alignment = Alignment(horizontal="right", vertical="center", wrap_text=True)
                    c.border = _border()

            # ----- نمودار روند امتیازها -----
            chart_row = 24 + len(alert_events) + 2
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
            for col in (1, 2, 3):
                ws.cell(row=data_start, column=col).fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
                ws.cell(row=data_start, column=col).font = _header_font()
                ws.cell(row=data_start, column=col).alignment = Alignment(horizontal="center")

            for i, (sp, acc) in enumerate(zip(sp_results, acc_results), 1):
                ws.cell(row=data_start + i, column=1, value=i)
                ws.cell(row=data_start + i, column=2, value=round(sp.total_score, 1))
                ws.cell(row=data_start + i, column=3, value=round(acc.total_score, 1))

            # ساخت نمودار خطی
            chart = LineChart()
            chart.title = "روند امتیازها (دابور)"
            chart.style = 12
            chart.y_axis.title = "امتیاز (۰-۱۰۰)"
            chart.x_axis.title = "نمونه زمانی"
            chart.height = 9
            chart.width = 18

            data_ref = Reference(ws, min_col=2, min_row=data_start,
                                  max_col=3, max_row=data_start + len(sp_results))
            cats_ref = Reference(ws, min_col=1, min_row=data_start + 1,
                                  max_row=data_start + len(sp_results))
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)

            ws.add_chart(chart, f"E{chart_row}")

    # -----------------------------------------------------------------
    # شیت ۲: SellPressure
    # -----------------------------------------------------------------
    def _build_sell_pressure_sheet(self, sp_results: List[SellPressureResult]):
        ws = self.wb.create_sheet("SellPressure")
        ws.sheet_view.rightToLeft = True

        # عنوان
        ws.merge_cells("A1:I1")
        c = ws["A1"]
        c.value = "موتور تشخیص فشار فروش - شش شاخص"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        # هدر جدول
        headers = [
            "زمان", "ضعف قدرت خریدار (۲۰)", "خروج پول حقیقی (۲۰)",
            "برتری سرانه فروش (۱۵)", "فاصله منفی آخرین-پایانی (۱۵)",
            "افزایش سرعت عرضه (۱۵)", "تخلیه تقاضا/کف روز (۱۵)",
            "مجموع", "سطح"
        ]
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = _header_font()
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = _border()
        ws.row_dimensions[3].height = 38

        # عرض ستون‌ها
        widths = [12, 16, 16, 16, 16, 16, 16, 10, 18]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        # داده‌ها
        for i, sp in enumerate(sp_results):
            r = 4 + i
            factors = sp.factors
            row_data = [
                sp.snapshot_time,
                round(factors[0].score, 1),
                round(factors[1].score, 1),
                round(factors[2].score, 1),
                round(factors[3].score, 1),
                round(factors[4].score, 1),
                round(factors[5].score, 1),
                round(sp.total_score, 1),
                sp.level,
            ]
            for j, v in enumerate(row_data, 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()
                # رنگ‌دهی به ستون‌های شاخص
                if 2 <= j <= 7 and factors:
                    f = factors[j - 2]
                    if f.normalized >= 0.66:
                        c.fill = PatternFill("solid", fgColor=Colors.DANGER)
                    elif f.normalized >= 0.33:
                        c.fill = PatternFill("solid", fgColor=Colors.WATCH)
                    else:
                        c.fill = PatternFill("solid", fgColor=Colors.NORMAL)
                # رنگ مجموع
                if j == 8:
                    c.fill = PatternFill("solid", fgColor=_score_color(sp.total_score))
                    c.font = Font(name="B Nazanin", size=11, bold=True)
                # رنگ سطح
                if j == 9:
                    c.fill = PatternFill("solid", fgColor=_score_color(sp.total_score))

        # نمودار ستونی برای شاخص‌ها (آخرین نمونه)
        if sp_results:
            last = sp_results[-1]
            chart_data_row = 4 + len(sp_results) + 2
            ws.cell(row=chart_data_row, column=1, value="شاخص").font = _header_font()
            ws.cell(row=chart_data_row, column=2, value="امتیاز").font = _header_font()
            ws.cell(row=chart_data_row, column=3, value="حداکثر").font = _header_font()
            for col in (1, 2, 3):
                ws.cell(row=chart_data_row, column=col).fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
                ws.cell(row=chart_data_row, column=col).font = _header_font()
                ws.cell(row=chart_data_row, column=col).alignment = Alignment(horizontal="center")

            for i, f in enumerate(last.factors):
                r = chart_data_row + 1 + i
                ws.cell(row=r, column=1, value=f.label)
                ws.cell(row=r, column=2, value=round(f.score, 1))
                ws.cell(row=r, column=3, value=f.max_points)

            chart = BarChart()
            chart.type = "bar"
            chart.style = 12
            chart.title = "تجزیه امتیاز فشار فروش (آخرین نمونه)"
            chart.y_axis.title = "شاخص"
            chart.x_axis.title = "امتیاز"
            chart.height = 10
            chart.width = 22
            data_ref = Reference(ws, min_col=2, min_row=chart_data_row,
                                  max_col=3, max_row=chart_data_row + 6)
            cats_ref = Reference(ws, min_col=1, min_row=chart_data_row + 1,
                                  max_row=chart_data_row + 6)
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)
            ws.add_chart(chart, f"K3")

    # -----------------------------------------------------------------
    # شیت ۳: Accumulation
    # -----------------------------------------------------------------
    def _build_accumulation_sheet(self, acc_results: List[AccumulationResult]):
        ws = self.wb.create_sheet("Accumulation")
        ws.sheet_view.rightToLeft = True

        # عنوان
        ws.merge_cells("A1:I1")
        c = ws["A1"]
        c.value = "موتور تشخیص جمع‌آوری سهم - شش شاخص"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        headers = [
            "زمان", "قدرت خرید حقیقی (۲۰)", "ورود پول حقیقی (۲۰)",
            "برتری تعداد خریداران (۱۰)", "جذب عرضه/ماندگاری (۲۰)",
            "مقاومت قیمت (۲۰)", "تداوم خرید (۱۰)",
            "مجموع", "سطح"
        ]
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = _header_font()
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = _border()
        ws.row_dimensions[3].height = 38

        widths = [12, 18, 18, 18, 18, 18, 14, 10, 22]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        for i, acc in enumerate(acc_results):
            r = 4 + i
            factors = acc.factors
            row_data = [
                acc.snapshot_time,
                round(factors[0].score, 1),
                round(factors[1].score, 1),
                round(factors[2].score, 1),
                round(factors[3].score, 1),
                round(factors[4].score, 1),
                round(factors[5].score, 1),
                round(acc.total_score, 1),
                acc.level,
            ]
            for j, v in enumerate(row_data, 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()
                if 2 <= j <= 7:
                    f = factors[j - 2]
                    if f.normalized >= 0.66:
                        c.fill = PatternFill("solid", fgColor=Colors.GREEN_ALERT)
                    elif f.normalized >= 0.33:
                        c.fill = PatternFill("solid", fgColor=Colors.WATCH)
                    else:
                        c.fill = PatternFill("solid", fgColor=Colors.NEUTRAL)
                if j == 8:
                    c.fill = PatternFill("solid", fgColor=_acc_color(acc.total_score))
                    c.font = Font(name="B Nazanin", size=11, bold=True)
                if j == 9:
                    c.fill = PatternFill("solid", fgColor=_acc_color(acc.total_score))

        # نمودار آخرین نمونه
        if acc_results:
            last = acc_results[-1]
            chart_data_row = 4 + len(acc_results) + 2
            ws.cell(row=chart_data_row, column=1, value="شاخص").font = _header_font()
            ws.cell(row=chart_data_row, column=2, value="امتیاز").font = _header_font()
            ws.cell(row=chart_data_row, column=3, value="حداکثر").font = _header_font()
            for col in (1, 2, 3):
                ws.cell(row=chart_data_row, column=col).fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
                ws.cell(row=chart_data_row, column=col).font = _header_font()

            for i, f in enumerate(last.factors):
                r = chart_data_row + 1 + i
                ws.cell(row=r, column=1, value=f.label)
                ws.cell(row=r, column=2, value=round(f.score, 1))
                ws.cell(row=r, column=3, value=f.max_points)

            chart = BarChart()
            chart.type = "bar"
            chart.style = 11
            chart.title = "تجزیه امتیاز جمع‌آوری (آخرین نمونه)"
            chart.y_axis.title = "شاخص"
            chart.x_axis.title = "امتیاز"
            chart.height = 10
            chart.width = 22
            data_ref = Reference(ws, min_col=2, min_row=chart_data_row,
                                  max_col=3, max_row=chart_data_row + 6)
            cats_ref = Reference(ws, min_col=1, min_row=chart_data_row + 1,
                                  max_row=chart_data_row + 6)
            chart.add_data(data_ref, titles_from_data=True)
            chart.set_categories(cats_ref)
            ws.add_chart(chart, f"K3")

    # -----------------------------------------------------------------
    # شیت ۴: History
    # -----------------------------------------------------------------
    def _build_history_sheet(self, snapshots: List, combined_states: List[CombinedState]):
        ws = self.wb.create_sheet("History")
        ws.sheet_view.rightToLeft = True
        ws.freeze_panes = "A4"

        # عنوان
        ws.merge_cells("A1:N1")
        c = ws["A1"]
        c.value = "تاریخچه کامل نمونه‌های زمانی"
        c.font = _title_font()
        c.alignment = Alignment(horizontal="center", vertical="center")
        c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
        ws.row_dimensions[1].height = 26

        headers = [
            "زمان", "آخرین قیمت", "قیمت پایانی", "بهترین خرید", "حجم خرید",
            "بهترین فروش", "حجم فروش", "حجم معاملات", "ارزش معاملات",
            "قدرت خریدار", "ورود/خروج پول حقیقی", "فشار فروش", "جمع‌آوری", "وضعیت"
        ]
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=3, column=i, value=h)
            c.font = _header_font()
            c.fill = PatternFill("solid", fgColor=Colors.HEADER_BG)
            c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            c.border = _border()
        ws.row_dimensions[3].height = 30

        widths = [12, 12, 12, 12, 12, 12, 12, 14, 16, 12, 16, 12, 12, 22]
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

        for i, (snap, state) in enumerate(zip(snapshots, combined_states)):
            r = 4 + i
            money_flow = snap.real_money_flow
            money_label = f"{money_flow/1e9:+.2f} میلیارد"
            if abs(money_flow) < 1e9:
                money_label = f"{money_flow/1e6:+.1f} میلیون"

            row_data = [
                snap.tehran_time,
                snap.last_price,
                snap.close_price,
                snap.best_buy_price,
                snap.best_buy_volume,
                snap.best_sell_price,
                snap.best_sell_volume,
                snap.trade_volume,
                snap.trade_value,
                round(snap.buyer_power, 2),
                money_label,
                round(state.sell_pressure_score, 1),
                round(state.accumulation_score, 1),
                state.combination_label,
            ]
            for j, v in enumerate(row_data, 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font = _body_font()
                c.alignment = Alignment(horizontal="center", vertical="center")
                c.border = _border()

            # رنگ فشار فروش
            ws.cell(row=r, column=12).fill = PatternFill(
                "solid", fgColor=_score_color(state.sell_pressure_score)
            )
            # رنگ جمع‌آوری
            ws.cell(row=r, column=13).fill = PatternFill(
                "solid", fgColor=_acc_color(state.accumulation_score)
            )

        # جدول خلاصه در پایان
        summary_row = 4 + len(snapshots) + 2
        ws.cell(row=summary_row, column=1, value="خلاصه").font = _subtitle_font()
        ws.cell(row=summary_row, column=1).fill = PatternFill("solid", fgColor=Colors.SUBTITLE_BG)
        ws.merge_cells(start_row=summary_row, end_row=summary_row, start_column=1, end_column=4)

        if combined_states:
            max_sp = max(s.sell_pressure_score for s in combined_states)
            max_acc = max(s.accumulation_score for s in combined_states)
            avg_sp = sum(s.sell_pressure_score for s in combined_states) / len(combined_states)
            avg_acc = sum(s.accumulation_score for s in combined_states) / len(combined_states)

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
