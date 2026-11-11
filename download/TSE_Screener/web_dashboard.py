"""
web_dashboard.py (نسخه ۲.۱ - دقیقاً مطابق TSETMC)
داشبورد وب زنده با چیدمان و اطلاعات دقیقاً مشابه TSETMC.

چیدمان مطابق TSETMC:
  ردیف اول (بالا):
    - راست: جدول حقیقی/حقوقی (تعداد/حجم/درصد برای خرید و فروش)
    - وسط: پنل قیمت لحظه‌ای + آمار معاملات + نوار بازه مجاز
    - چپ: پنل تغییر مالکیت + NAV
  ردیف دوم (پایین):
    - چپ: نمودار قیمت
    - راست: جدول عمق بازار (۵ ردیف سفارش)

رنگ‌بندی مطابق TSETMC:
  - قرمز/صورتی: آخرین قیمت (در بازار ایران قرمز = نزول)
  - سبز: NAV، قیمت‌های مثبت
  - آبی تیره: هدر جدول حقیقی/حقوقی
  - بنفش کم‌رنگ: هدر جدول عمق بازار

نحوه اجرا:
  python web_dashboard.py
  # سپس مرورگر: http://localhost:8050
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import json
from pathlib import Path
from datetime import datetime

try:
    from flask import Flask, render_template_string, jsonify, request
except ImportError:
    print("❌ کتابخانه Flask نصب نیست.")
    print("   نصب با: pip install flask")
    sys.exit(1)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "early_warning_live.sqlite"

app = Flask(__name__)


# ---------------------------------------------------------------------------
# قالب HTML - دقیقاً مطابق TSETMC
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TSETMC - ریتون</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Vazirmatn', 'Segoe UI', Tahoma, sans-serif;
            background: #d4dadf;
            color: #2c3e50;
            font-size: 12px;
            padding: 8px;
        }
        .container { max-width: 1400px; margin: 0 auto; }

        /* نوار عنوان مشکی - شبیه TSETMC */
        .header-bar {
            background: #1a1a1a;
            color: white;
            padding: 8px 12px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-radius: 4px 4px 0 0;
            font-size: 13px;
        }
        .header-bar .symbol-name { font-weight: bold; }
        .header-bar .clock {
            font-family: monospace;
            background: #2c5282;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 12px;
        }

        /* ردیف اول - سه ستون */
        .top-row {
            display: grid;
            grid-template-columns: 1.1fr 1.4fr 1fr;
            gap: 6px;
            margin-bottom: 6px;
        }

        .card {
            background: white;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .card-header {
            background: #4a5568;
            color: white;
            padding: 5px 10px;
            font-size: 11px;
            font-weight: bold;
            text-align: center;
        }

        /* جدول حقیقی/حقوقی - مطابق TSETMC */
        .real-legal-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }
        .real-legal-table th {
            background: #2c5282;
            color: white;
            padding: 5px 3px;
            text-align: center;
            font-weight: 600;
            font-size: 10px;
        }
        .real-legal-table td {
            padding: 5px 3px;
            text-align: center;
            border-bottom: 1px solid #e2e8f0;
        }
        .real-legal-table .row-header {
            background: #2c5282;
            color: white;
            font-weight: bold;
        }
        .real-legal-table .label-col {
            background: #ebf4ff;
            font-weight: bold;
            text-align: right;
            padding-right: 8px;
        }
        .real-legal-table .orange { color: #d97706; font-weight: bold; }
        .real-legal-table .green { color: #16a34a; font-weight: bold; }

        /* پنل قیمت لحظه‌ای */
        .price-panel { padding: 10px; }
        .last-price-box {
            background: #fee2e2;
            padding: 10px;
            border-radius: 4px;
            text-align: center;
            margin-bottom: 8px;
        }
        .last-price-value {
            font-size: 30px;
            font-weight: bold;
            color: #dc2626;
        }
        .last-price-change {
            font-size: 12px;
            color: #dc2626;
            margin-top: 3px;
        }
        .price-info-row {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 5px;
            margin-bottom: 6px;
        }
        .price-info-item {
            background: #f1f5f9;
            padding: 5px 6px;
            border-radius: 3px;
            text-align: center;
        }
        .price-info-label {
            font-size: 9px;
            color: #64748b;
            margin-bottom: 2px;
        }
        .price-info-value {
            font-size: 12px;
            font-weight: bold;
            color: #1e293b;
        }

        /* نوار بازه مجاز */
        .range-section {
            margin: 6px 0;
            padding: 6px;
            background: #f8fafc;
            border-radius: 3px;
        }
        .range-labels {
            display: flex;
            justify-content: space-between;
            font-size: 10px;
            color: #64748b;
            margin-bottom: 4px;
        }
        .range-bar {
            background: #e2e8f0;
            height: 6px;
            border-radius: 3px;
            position: relative;
        }
        .range-fill {
            background: linear-gradient(90deg, #dc2626 0%, #fbbf24 50%, #16a34a 100%);
            height: 100%;
            border-radius: 3px;
        }
        .range-marker {
            position: absolute;
            top: -3px;
            width: 3px;
            height: 12px;
            background: #1e293b;
            border-radius: 1px;
        }

        /* آمار معاملات */
        .stats-section {
            background: #f8fafc;
            padding: 6px;
            border-radius: 3px;
            margin-top: 6px;
        }
        .stats-row {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 5px;
        }
        .stats-item {
            text-align: center;
            padding: 3px;
            background: white;
            border-radius: 2px;
        }
        .stats-label { font-size: 9px; color: #64748b; }
        .stats-value { font-size: 11px; font-weight: bold; color: #1e293b; }

        /* پنل تغییر مالکیت + NAV */
        .ownership-panel { padding: 8px; }
        .ownership-label {
            font-size: 10px;
            color: #64748b;
            margin-bottom: 6px;
            text-align: center;
        }
        .ownership-buttons {
            display: flex;
            gap: 3px;
            margin-bottom: 8px;
        }
        .ownership-btn {
            flex: 1;
            padding: 4px 2px;
            text-align: center;
            border-radius: 3px;
            font-size: 9px;
            background: #e2e8f0;
            color: #64748b;
        }
        .ownership-btn.active {
            background: #16a34a;
            color: white;
            font-weight: bold;
        }
        .nav-box {
            background: #dcfce7;
            padding: 8px;
            border-radius: 4px;
            text-align: center;
            margin: 8px 0;
        }
        .nav-label { font-size: 10px; color: #16a34a; }
        .nav-value {
            font-size: 20px;
            font-weight: bold;
            color: #16a34a;
            margin: 2px 0;
        }
        .nav-time { font-size: 9px; color: #64748b; }

        .extra-info {
            margin-top: 8px;
            font-size: 10px;
        }
        .extra-info-row {
            display: flex;
            justify-content: space-between;
            padding: 3px 0;
            border-bottom: 1px solid #f1f5f9;
        }

        /* پنل هشدار موتور */
        .alert-bar {
            background: white;
            border-radius: 4px;
            padding: 8px 12px;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .alert-scores { display: flex; gap: 15px; }
        .score-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            min-width: 80px;
        }
        .score-label { font-size: 10px; color: #64748b; }
        .score-value { font-size: 20px; font-weight: bold; }
        .score-value.sp { color: #dc2626; }
        .score-value.acc { color: #16a34a; }
        .score-bar {
            width: 100%;
            height: 4px;
            background: #e2e8f0;
            border-radius: 2px;
            margin-top: 3px;
            overflow: hidden;
        }
        .score-bar-fill-sp { height: 100%; background: #dc2626; transition: width 0.5s; }
        .score-bar-fill-acc { height: 100%; background: #16a34a; transition: width 0.5s; }
        .signal-badge {
            padding: 6px 14px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: bold;
            color: white;
        }
        .signal-normal { background: #64748b; }
        .signal-yellow { background: #f59e0b; }
        .signal-red { background: #dc2626; }
        .signal-green { background: #16a34a; }
        .signal-orange { background: #ea580c; }

        /* ردیف دوم */
        .bottom-row {
            display: grid;
            grid-template-columns: 1fr 1.3fr;
            gap: 6px;
        }
        .chart-card { padding: 8px; height: 320px; }
        .chart-container { height: 250px; position: relative; }

        /* جدول عمق بازار - بنفش کم‌رنگ */
        .orderbook-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }
        .orderbook-table th {
            background: #ede9fe;
            color: #6b21a8;
            padding: 5px 3px;
            text-align: center;
            font-weight: 600;
            border-bottom: 2px solid #c4b5fd;
            font-size: 10px;
        }
        .orderbook-table td {
            padding: 4px 3px;
            text-align: center;
            border-bottom: 1px solid #f1f5f9;
        }
        .orderbook-table .price-buy {
            background: #fef2f2;
            color: #dc2626;
            font-weight: bold;
        }
        .orderbook-table .price-sell {
            background: #dcfce7;
            color: #16a34a;
            font-weight: bold;
        }

        .recent-card { margin-top: 6px; }
        .recent-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 10px;
        }
        .recent-table th {
            background: #4a5568;
            color: white;
            padding: 5px;
            text-align: center;
        }
        .recent-table td {
            padding: 3px 5px;
            text-align: center;
            border-bottom: 1px solid #e2e8f0;
        }
        .recent-table tr:hover { background: #f1f5f9; }

        .status-bar {
            background: white;
            padding: 6px 12px;
            border-radius: 4px;
            margin-bottom: 6px;
            display: flex;
            justify-content: space-between;
            font-size: 11px;
        }
        .live-dot {
            display: inline-block;
            width: 7px;
            height: 7px;
            background: #16a34a;
            border-radius: 50%;
            margin-left: 5px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }
        .no-data { color: #94a3b8; text-align: center; padding: 15px; font-size: 11px; }
    </style>
</head>
<body>
<div class="container">

    <!-- نوار عنوان مشکی -->
    <div class="header-bar">
        <div class="symbol-name">صندوق سرمایه‌گذاری کالای پاسارگاد (ریتون)</div>
        <div>
            <span>ساعت: </span>
            <span class="clock" id="clock">--:--:--</span>
        </div>
    </div>

    <!-- نوار وضعیت -->
    <div class="status-bar">
        <div>
            <span class="live-dot"></span>
            پایش زنده فعال
        </div>
        <div>
            آخرین به‌روزرسانی: <strong id="lastUpdate">-</strong>
            | تعداد نمونه‌ها: <strong id="totalCount">0</strong>
        </div>
    </div>

    <!-- ردیف اول: حقیقی/حقوقی + قیمت لحظه‌ای + تغییر مالکیت -->
    <div class="top-row">

        <!-- سمت راست: جدول حقیقی/حقوقی (مطابق TSETMC) -->
        <div class="card">
            <div class="card-header">حقیقی / حقوقی</div>
            <table class="real-legal-table">
                <thead>
                    <tr>
                        <th></th>
                        <th>تعداد</th>
                        <th>حجم</th>
                        <th>درصد</th>
                    </tr>
                </thead>
                <tbody id="realLegalTable">
                    <tr><td colspan="4" class="no-data">داده‌ای دریافت نشده</td></tr>
                </tbody>
            </table>
        </div>

        <!-- وسط: پنل قیمت لحظه‌ای -->
        <div class="card">
            <div class="card-header">قیمت لحظه‌ای</div>
            <div class="price-panel">
                <div class="last-price-box">
                    <div class="last-price-value" id="lastPrice">-</div>
                    <div class="last-price-change" id="priceChange">-</div>
                </div>
                <div class="price-info-row">
                    <div class="price-info-item">
                        <div class="price-info-label">دیروز</div>
                        <div class="price-info-value" id="yesterdayPrice">-</div>
                    </div>
                    <div class="price-info-item">
                        <div class="price-info-label">اولین</div>
                        <div class="price-info-value" id="openPrice">-</div>
                    </div>
                    <div class="price-info-item">
                        <div class="price-info-label">پایانی</div>
                        <div class="price-info-value" id="closePrice">-</div>
                    </div>
                </div>
                <div class="price-info-row">
                    <div class="price-info-item">
                        <div class="price-info-label">بالاترین</div>
                        <div class="price-info-value" id="dailyHigh" style="color:#16a34a;">-</div>
                    </div>
                    <div class="price-info-item">
                        <div class="price-info-label">پایین‌ترین</div>
                        <div class="price-info-value" id="dailyLow" style="color:#dc2626;">-</div>
                    </div>
                    <div class="price-info-item">
                        <div class="price-info-label">فاز بازار</div>
                        <div class="price-info-value" id="marketPhase">-</div>
                    </div>
                </div>

                <!-- نوار بازه مجاز -->
                <div class="range-section">
                    <div class="range-labels">
                        <span>کف مجاز: <span id="minAllowed">-</span></span>
                        <span>سقف مجاز: <span id="maxAllowed">-</span></span>
                    </div>
                    <div class="range-bar">
                        <div class="range-fill"></div>
                        <div class="range-marker" id="priceMarker" style="left: 50%;"></div>
                    </div>
                </div>

                <!-- آمار معاملات -->
                <div class="stats-section">
                    <div class="stats-row">
                        <div class="stats-item">
                            <div class="stats-label">تعداد معاملات</div>
                            <div class="stats-value" id="totalTradeCount">-</div>
                        </div>
                        <div class="stats-item">
                            <div class="stats-label">حجم معاملات</div>
                            <div class="stats-value" id="totalVolume">-</div>
                        </div>
                        <div class="stats-item">
                            <div class="stats-label">ارزش معاملات</div>
                            <div class="stats-value" id="totalValue">-</div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- سمت چپ: تغییر مالکیت + NAV -->
        <div class="card">
            <div class="card-header">تغییر مالکیت و NAV</div>
            <div class="ownership-panel">
                <div class="ownership-label">احتمال تغییر مالکیت</div>
                <div class="ownership-buttons">
                    <div class="ownership-btn" id="ownLight">سبک</div>
                    <div class="ownership-btn" id="ownSemiLight">نیمه‌سبک</div>
                    <div class="ownership-btn" id="ownNormal">طبیعی</div>
                    <div class="ownership-btn" id="ownHeavy">سنگین</div>
                    <div class="ownership-btn" id="ownVeryHeavy">خیلی سنگین</div>
                </div>

                <div class="nav-box">
                    <div class="nav-label">NAV ابطال</div>
                    <div class="nav-value" id="navValue">-</div>
                    <div class="nav-time" id="navTime">-</div>
                </div>

                <div class="extra-info">
                    <div class="extra-info-row">
                        <span>قدرت خریدار:</span>
                        <strong id="buyerPower">-</strong>
                    </div>
                    <div class="extra-info-row">
                        <span>سرانه خرید:</span>
                        <strong id="perCapitaBuy">-</strong>
                    </div>
                    <div class="extra-info-row">
                        <span>سرانه فروش:</span>
                        <strong id="perCapitaSell">-</strong>
                    </div>
                    <div class="extra-info-row">
                        <span>ورود/خروج پول:</span>
                        <strong id="moneyFlow">-</strong>
                    </div>
                    <div class="extra-info-row">
                        <span>کمال داده:</span>
                        <strong id="completeness">-</strong>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- پنل هشدار موتور -->
    <div class="alert-bar">
        <div class="alert-scores">
            <div class="score-item">
                <div class="score-label">Sell Pressure</div>
                <div class="score-value sp" id="spScore">-</div>
                <div class="score-bar"><div class="score-bar-fill-sp" id="spBar" style="width:0%"></div></div>
            </div>
            <div class="score-item">
                <div class="score-label">Accumulation</div>
                <div class="score-value acc" id="accScore">-</div>
                <div class="score-bar"><div class="score-bar-fill-acc" id="accBar" style="width:0%"></div></div>
            </div>
        </div>
        <div class="signal-badge signal-normal" id="signalBadge">در حال دریافت...</div>
    </div>

    <!-- ردیف دوم: نمودار + عمق بازار -->
    <div class="bottom-row">
        <div class="card chart-card">
            <div class="card-header">نمودار قیمت</div>
            <div class="chart-container">
                <canvas id="priceChart"></canvas>
            </div>
        </div>

        <div class="card">
            <div class="card-header">عمق بازار (۵ ردیف سفارش)</div>
            <table class="orderbook-table">
                <thead>
                    <tr>
                        <th>تعداد خرید</th>
                        <th>حجم خرید</th>
                        <th>قیمت خرید</th>
                        <th>قیمت فروش</th>
                        <th>حجم فروش</th>
                        <th>تعداد فروش</th>
                    </tr>
                </thead>
                <tbody id="orderBookTable">
                    <tr><td colspan="6" class="no-data">داده‌ای دریافت نشده</td></tr>
                </tbody>
            </table>
        </div>
    </div>

    <!-- نمونه‌های اخیر -->
    <div class="card recent-card">
        <div class="card-header">آخرین ۱۵ نمونه</div>
        <table class="recent-table">
            <thead>
                <tr>
                    <th>زمان</th>
                    <th>فاز</th>
                    <th>آخرین</th>
                    <th>پایانی</th>
                    <th>حجم خرید</th>
                    <th>حجم فروش</th>
                    <th>قدرت</th>
                    <th>پول</th>
                    <th>کامل</th>
                </tr>
            </thead>
            <tbody id="recentTable">
                <tr><td colspan="9" class="no-data">داده‌ای دریافت نشده</td></tr>
            </tbody>
        </table>
    </div>

</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>
let priceChart = null;

async function fetchData() {
    try {
        const response = await fetch('/api/data');
        const data = await response.json();
        updateUI(data);
    } catch (err) {
        console.error('خطا:', err);
    }
}

function formatNumber(v) {
    if (v === null || v === undefined || v === 0) return '-';
    return Number(v).toLocaleString('fa-IR');
}

function formatVolume(v) {
    if (!v || v === 0) return '-';
    if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(2) + ' B';
    if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1) + ' M';
    if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(0) + ' K';
    return formatNumber(v);
}

function formatMoney(v) {
    if (!v || v === 0) return '-';
    if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(2) + ' M تومان';
    if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(0) + ' K تومان';
    return formatNumber(v) + ' تومان';
}

function phaseLabel(p) {
    return {'pre_open':'پیش‌گشایش','continuous':'پیوسته','halted':'متوقف','closed':'بسته'}[p] || p || '-';
}

function updateUI(data) {
    document.getElementById('clock').textContent = data.last_update || '--:--:--';
    document.getElementById('lastUpdate').textContent = data.last_update || '-';
    document.getElementById('totalCount').textContent = data.total_snapshots || 0;

    const snap = data.last_snapshot;

    if (snap) {
        // قیمت‌ها
        document.getElementById('lastPrice').textContent = formatNumber(snap.last_price);
        document.getElementById('yesterdayPrice').textContent = formatNumber(snap.yesterday_price);
        document.getElementById('openPrice').textContent = formatNumber(snap.open_price);
        document.getElementById('closePrice').textContent = formatNumber(snap.close_price);
        document.getElementById('dailyHigh').textContent = formatNumber(snap.daily_high);
        document.getElementById('dailyLow').textContent = formatNumber(snap.daily_low);
        document.getElementById('marketPhase').textContent = phaseLabel(snap.market_phase);
        document.getElementById('minAllowed').textContent = formatNumber(snap.min_allowed_price);
        document.getElementById('maxAllowed').textContent = formatNumber(snap.max_allowed_price);

        // تغییر قیمت
        if (snap.yesterday_price > 0 && snap.last_price > 0) {
            const change = snap.last_price - snap.yesterday_price;
            const changePct = (change / snap.yesterday_price) * 100;
            const sign = change >= 0 ? '+' : '';
            const color = change >= 0 ? '#16a34a' : '#dc2626';
            document.getElementById('priceChange').innerHTML =
                `<span style="color:${color}">${sign}${formatNumber(change)} (${sign}${changePct.toFixed(2)}%)</span>`;
        }

        // نوار بازه مجاز
        if (snap.min_allowed_price > 0 && snap.max_allowed_price > 0 && snap.last_price > 0) {
            const pct = ((snap.last_price - snap.min_allowed_price) /
                         (snap.max_allowed_price - snap.min_allowed_price)) * 100;
            document.getElementById('priceMarker').style.left = Math.max(0, Math.min(100, pct)) + '%';
        }

        // آمار معاملات
        document.getElementById('totalTradeCount').textContent = formatNumber(snap.total_trade_count);
        document.getElementById('totalVolume').textContent = formatVolume(snap.total_volume);
        document.getElementById('totalValue').textContent = formatMoney(snap.total_value);

        // جدول حقیقی/حقوقی (مطابق TSETMC)
        const rb = snap.real_buy_count || 0;
        const rs = snap.real_sell_count || 0;
        const lb = snap.legal_buy_count || 0;
        const ls = snap.legal_sell_count || 0;
        const rbv = snap.real_buy_volume || 0;
        const rsv = snap.real_sell_volume || 0;
        const lbv = snap.legal_buy_volume || 0;
        const lsv = snap.legal_sell_volume || 0;
        const totalBuyVol = rbv + lbv;
        const totalSellVol = rsv + lsv;

        if (rb > 0 || rs > 0 || lb > 0 || ls > 0) {
            const rbPct = totalBuyVol > 0 ? (rbv/totalBuyVol*100).toFixed(1) : '0';
            const lbPct = totalBuyVol > 0 ? (lbv/totalBuyVol*100).toFixed(1) : '0';
            const rsPct = totalSellVol > 0 ? (rsv/totalSellVol*100).toFixed(1) : '0';
            const lsPct = totalSellVol > 0 ? (lsv/totalSellVol*100).toFixed(1) : '0';

            document.getElementById('realLegalTable').innerHTML = `
                <tr class="row-header">
                    <td class="label-col">حقیقی (خرید)</td>
                    <td>${formatNumber(rb)}</td>
                    <td>${formatVolume(rbv)}</td>
                    <td class="orange">${rbPct}%</td>
                </tr>
                <tr class="row-header">
                    <td class="label-col">حقوقی (خرید)</td>
                    <td>${formatNumber(lb)}</td>
                    <td>${formatVolume(lbv)}</td>
                    <td class="orange">${lbPct}%</td>
                </tr>
                <tr class="row-header">
                    <td class="label-col">حقیقی (فروش)</td>
                    <td>${formatNumber(rs)}</td>
                    <td>${formatVolume(rsv)}</td>
                    <td class="orange">${rsPct}%</td>
                </tr>
                <tr class="row-header">
                    <td class="label-col">حقوقی (فروش)</td>
                    <td>${formatNumber(ls)}</td>
                    <td>${formatVolume(lsv)}</td>
                    <td class="orange">${lsPct}%</td>
                </tr>
            `;
        }

        // عمق بازار
        const buyRows = [
            {price: snap.bid_price_1, vol: snap.bid_volume_1, count: snap.bid_count_1},
            {price: snap.bid_price_2, vol: snap.bid_volume_2, count: snap.bid_count_2},
            {price: snap.bid_price_3, vol: snap.bid_volume_3, count: snap.bid_count_3},
            {price: snap.bid_price_4, vol: snap.bid_volume_4, count: snap.bid_count_4},
            {price: snap.bid_price_5, vol: snap.bid_volume_5, count: snap.bid_count_5},
        ].filter(r => r.price);
        const sellRows = [
            {price: snap.ask_price_1, vol: snap.ask_volume_1, count: snap.ask_count_1},
            {price: snap.ask_price_2, vol: snap.ask_volume_2, count: snap.ask_count_2},
            {price: snap.ask_price_3, vol: snap.ask_volume_3, count: snap.ask_count_3},
            {price: snap.ask_price_4, vol: snap.ask_volume_4, count: snap.ask_count_4},
            {price: snap.ask_price_5, vol: snap.ask_volume_5, count: snap.ask_count_5},
        ].filter(r => r.price);

        if (buyRows.length > 0 && sellRows.length > 0) {
            let html = '';
            for (let i = 0; i < 5; i++) {
                const b = buyRows[i] || {price:'-', vol:'-', count:'-'};
                const s = sellRows[i] || {price:'-', vol:'-', count:'-'};
                html += `<tr>
                    <td>${b.count || '-'}</td>
                    <td>${formatVolume(b.vol)}</td>
                    <td class="price-buy">${b.price || '-'}</td>
                    <td class="price-sell">${s.price || '-'}</td>
                    <td>${formatVolume(s.vol)}</td>
                    <td>${s.count || '-'}</td>
                </tr>`;
            }
            document.getElementById('orderBookTable').innerHTML = html;
        }

        // اطلاعات تکمیلی
        document.getElementById('buyerPower').textContent =
            snap.buyer_power ? snap.buyer_power.toFixed(2) : '-';
        document.getElementById('perCapitaBuy').textContent =
            snap.per_capita_buy_real ? formatVolume(snap.per_capita_buy_real) : '-';
        document.getElementById('perCapitaSell').textContent =
            snap.per_capita_sell_real ? formatVolume(snap.per_capita_sell_real) : '-';
        const mf = snap.real_money_flow;
        if (mf) {
            const sign = mf >= 0 ? '+' : '';
            const color = mf >= 0 ? '#16a34a' : '#dc2626';
            document.getElementById('moneyFlow').innerHTML =
                `<span style="color:${color}">${sign}${formatMoney(mf)}</span>`;
        }
        document.getElementById('completeness').textContent =
            (data.last_snapshot.completeness_pct || 0) + '%';
    }

    // امتیازها
    const sp = data.sell_pressure;
    const acc = data.accumulation;
    if (sp) {
        document.getElementById('spScore').textContent = sp.score.toFixed(0);
        document.getElementById('spBar').style.width = sp.score + '%';
    }
    if (acc) {
        document.getElementById('accScore').textContent = acc.score.toFixed(0);
        document.getElementById('accBar').style.width = acc.score + '%';
    }

    // سیگنال
    const sig = data.signal;
    const badge = document.getElementById('signalBadge');
    badge.textContent = sig.message;
    badge.className = 'signal-badge ' + sig.css_class;

    // جدول نمونه‌های اخیر
    if (data.recent_snapshots && data.recent_snapshots.length > 0) {
        let html = '';
        for (const s of data.recent_snapshots) {
            const mf = s.real_money_flow;
            const mfStr = mf ? (mf >= 0 ? '+' + formatVolume(mf) : formatVolume(mf)) : '-';
            const mfColor = mf >= 0 ? '#16a34a' : '#dc2626';
            html += `<tr>
                <td>${s.tehran_time || '-'}</td>
                <td>${phaseLabel(s.market_phase)}</td>
                <td>${formatNumber(s.last_price)}</td>
                <td>${formatNumber(s.close_price)}</td>
                <td>${formatVolume(s.best_buy_volume)}</td>
                <td>${formatVolume(s.best_sell_volume)}</td>
                <td>${s.buyer_power ? s.buyer_power.toFixed(1) : '-'}</td>
                <td style="color:${mfColor}">${mfStr}</td>
                <td>${s.completeness_pct || 0}%</td>
            </tr>`;
        }
        document.getElementById('recentTable').innerHTML = html;
    }

    // نمودار
    if (data.recent_snapshots && data.recent_snapshots.length > 0) {
        updateChart(data.recent_snapshots);
    }
}

function updateChart(snaps) {
    const reversed = [...snaps].reverse();
    const labels = reversed.map(s => s.tehran_time || '');
    const prices = reversed.map(s => s.last_price || 0);
    const closes = reversed.map(s => s.close_price || 0);

    const ctx = document.getElementById('priceChart').getContext('2d');
    if (priceChart) {
        priceChart.data.labels = labels;
        priceChart.data.datasets[0].data = prices;
        priceChart.data.datasets[1].data = closes;
        priceChart.update('none');
    } else {
        priceChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: labels,
                datasets: [
                    {
                        label: 'آخرین قیمت',
                        data: prices,
                        borderColor: '#dc2626',
                        backgroundColor: 'rgba(220, 38, 38, 0.1)',
                        borderWidth: 2,
                        tension: 0.3,
                        fill: false,
                    },
                    {
                        label: 'قیمت پایانی',
                        data: closes,
                        borderColor: '#2c5282',
                        backgroundColor: 'rgba(44, 82, 130, 0.1)',
                        borderWidth: 2,
                        tension: 0.3,
                        fill: false,
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {position: 'top', labels: {font: {size: 10}}}
                },
                scales: {
                    y: {ticks: {font: {size: 9}}},
                    x: {ticks: {font: {size: 8}, maxRotation: 0}}
                }
            }
        });
    }
}

fetchData();
setInterval(fetchData, 5000);
setInterval(() => {
    document.getElementById('clock').textContent = new Date().toLocaleTimeString('fa-IR');
}, 1000);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# توابع کمکی
# ---------------------------------------------------------------------------

def get_db_conn():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def compute_completeness(snap_dict):
    if not snap_dict:
        return 0
    critical_fields = [
        'last_price', 'close_price',
        'best_buy_price', 'best_buy_volume',
        'best_sell_price', 'best_sell_volume',
        'total_volume', 'total_value',
    ]
    optional_fields = [
        'real_buy_count', 'real_buy_volume',
        'real_sell_count', 'real_sell_volume',
        'legal_buy_count', 'legal_sell_count',
        'buyer_power', 'real_money_flow',
        'buy_order_count', 'sell_order_count',
    ]
    is_pre_open = snap_dict.get('market_phase') == 'pre_open'
    critical_filled = 0
    for f in critical_fields:
        if is_pre_open and f in ('total_volume', 'total_value'):
            critical_filled += 1
            continue
        v = snap_dict.get(f)
        if v is not None and v != 0:
            critical_filled += 1
    optional_filled = 0
    for f in optional_fields:
        v = snap_dict.get(f)
        if v is not None and v != 0:
            optional_filled += 1
    pct = 80 * (critical_filled / len(critical_fields)) + 20 * (optional_filled / len(optional_fields))
    return int(min(100, max(0, pct)))


def compute_scores(snap_dict):
    if not snap_dict:
        return None, None
    sp_score = 0
    if snap_dict.get('buyer_power') and snap_dict['buyer_power'] < 1:
        sp_score += 20 * (1 - snap_dict['buyer_power']) / 0.5
    if snap_dict.get('real_money_flow_ratio') and snap_dict['real_money_flow_ratio'] < 0:
        sp_score += 20 * min(1, -snap_dict['real_money_flow_ratio'] / 0.05)
    if snap_dict.get('last_price') and snap_dict.get('close_price') and snap_dict['close_price'] > 0:
        gap = (snap_dict['last_price'] - snap_dict['close_price']) / snap_dict['close_price']
        if gap < 0:
            sp_score += 15 * min(1, -gap / 0.02)
    sp_score = min(100, max(0, sp_score))

    acc_score = 0
    if snap_dict.get('buyer_power') and snap_dict['buyer_power'] > 1:
        acc_score += 20 * min(1, (snap_dict['buyer_power'] - 1) / 0.5)
    if snap_dict.get('real_money_flow_ratio') and snap_dict['real_money_flow_ratio'] > 0:
        acc_score += 20 * min(1, snap_dict['real_money_flow_ratio'] / 0.05)
    acc_score = min(100, max(0, acc_score))

    def sp_level(s):
        if s <= 24: return "عادی"
        if s <= 34: return "مراقبت"
        if s <= 49: return "هشدار زودهنگام"
        if s <= 64: return "فشار فروش بالا"
        if s <= 79: return "خطر صف فروش"
        return "وضعیت بحرانی"

    def acc_level(s):
        if s <= 24: return "نشانه ندارد"
        if s <= 39: return "احتمال اولیه"
        if s <= 59: return "جمع‌آوری قابل توجه"
        if s <= 79: return "جمع‌آوری قوی"
        return "جمع‌آوری بسیار قوی"

    return (
        {'score': sp_score, 'level': sp_level(sp_score)},
        {'score': acc_score, 'level': acc_level(acc_score)}
    )


def determine_signal(sp, acc):
    if not sp or not acc:
        return {'message': 'در حال دریافت...', 'css_class': 'signal-normal'}
    sp_score = sp['score']
    acc_score = acc['score']
    if sp_score >= 50 and acc_score < 40:
        return {'message': '🔴 هشدار قرمز - ریسک خروج', 'css_class': 'signal-red'}
    if sp_score >= 50 and acc_score >= 40:
        return {'message': '🟠 جذب + فشار هم‌زمان', 'css_class': 'signal-orange'}
    if acc_score >= 40:
        return {'message': '🟢 هشدار سبز - جذب عرضه', 'css_class': 'signal-green'}
    if sp_score >= 35:
        return {'message': '🟡 هشدار زرد - ضعف تقاضا', 'css_class': 'signal-yellow'}
    return {'message': 'وضعیت عادی - ادامه پایش', 'css_class': 'signal-normal'}


# ---------------------------------------------------------------------------
# API و Routeها
# ---------------------------------------------------------------------------

@app.route('/')
def dashboard():
    return render_template_string(DASHBOARD_HTML)


@app.route('/api/data')
def api_data():
    conn = get_db_conn()
    if conn is None:
        return jsonify({
            'last_update': datetime.now().strftime('%H:%M:%S'),
            'total_snapshots': 0,
            'total_trades': 0,
            'symbol': 'ریتون',
            'last_snapshot': None,
            'recent_snapshots': [],
            'recent_trades': [],
            'alerts': [],
            'sell_pressure': None,
            'accumulation': None,
            'signal': {'message': 'پایگاه داده یافت نشد', 'css_class': 'signal-normal'},
        })

    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM snapshots")
    total_snapshots = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trades")
    total_trades = cur.fetchone()[0]

    cur.execute("SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1")
    last_row = cur.fetchone()
    last_snap = dict(last_row) if last_row else None
    if last_snap:
        last_snap['completeness_pct'] = compute_completeness(last_snap)

    cur.execute("""
        SELECT tehran_time, market_phase, last_price, close_price,
               best_buy_volume, best_sell_volume, buyer_power,
               real_money_flow, data_complete, total_volume, total_value,
               total_trade_count, best_buy_price, best_sell_price,
               real_buy_count, real_buy_volume, real_sell_count, real_sell_volume,
               legal_buy_count, legal_buy_volume, legal_sell_count, legal_sell_volume,
               per_capita_buy_real, per_capita_sell_real, buy_order_count, sell_order_count,
               bid_price_1, bid_volume_1, bid_count_1,
               bid_price_2, bid_volume_2, bid_count_2,
               bid_price_3, bid_volume_3, bid_count_3,
               bid_price_4, bid_volume_4, bid_count_4,
               bid_price_5, bid_volume_5, bid_count_5,
               ask_price_1, ask_volume_1, ask_count_1,
               ask_price_2, ask_volume_2, ask_count_2,
               ask_price_3, ask_volume_3, ask_count_3,
               ask_price_4, ask_volume_4, ask_count_4,
               ask_price_5, ask_volume_5, ask_count_5
        FROM snapshots ORDER BY timestamp DESC LIMIT 15
    """)
    recent = [dict(r) for r in cur.fetchall()]
    for r in recent:
        r['completeness_pct'] = compute_completeness(r)

    sp, acc = compute_scores(last_snap)
    signal = determine_signal(sp, acc)
    conn.close()

    return jsonify({
        'last_update': datetime.now().strftime('%H:%M:%S'),
        'total_snapshots': total_snapshots,
        'total_trades': total_trades,
        'symbol': last_snap.get('symbol', 'ریتون') if last_snap else 'ریتون',
        'last_snapshot': last_snap,
        'recent_snapshots': recent,
        'recent_trades': [],
        'alerts': [],
        'sell_pressure': sp,
        'accumulation': acc,
        'signal': signal,
    })


def main():
    parser = argparse.ArgumentParser(description='TSE Early Warning Dashboard v2.1')
    parser.add_argument('--port', type=int, default=8050, help='پورت سرور')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='میزبان')
    args = parser.parse_args()

    print("=" * 60)
    print("  TSE Early Warning - Dashboard v2.1 (TSETMC Style)")
    print("=" * 60)
    print()
    print(f"📊 Database: {DB_PATH}")
    print(f"🌐 URL:       http://{args.host}:{args.port}")
    print()
    print("  مرورگر را باز کنید و به آدرس بالا بروید")
    print("  صفحه هر ۵ ثانیه خودکار به‌روزرسانی می‌شود")
    print()
    print("  برای توقف: Ctrl+C")
    print("-" * 60)

    try:
        app.run(host=args.host, port=args.port, debug=False)
    except KeyboardInterrupt:
        print("\n✓ سرور متوقف شد")


if __name__ == '__main__':
    main()
