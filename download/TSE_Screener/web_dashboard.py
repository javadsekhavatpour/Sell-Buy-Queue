"""
web_dashboard.py (نسخه ۲.۰ - شبیه TSETMC)
داشبورد وب زنده با چیدمان و رنگ‌بندی مشابه TSETMC.

طراحی:
  ردیف اول (بالا):
    - راست: جدول حقیقی/حقوقی (آبی تیره)
    - وسط: پنل قیمت لحظه‌ای (آخرین معامله، بازه مجاز، حجم/ارزش)
    - چپ: تغییر مالکیت و NAV
  ردیف دوم (پایین):
    - چپ: نمودار قیمت
    - راست: جدول عمق بازار (۵ ردیف سفارش)

رنگ‌بندی TSETMC:
  - قرمز/صورتی: قیمت‌های منفی
  - سبز: مثبت
  - آبی تیره: هدر حقیقی/حقوقی
  - بنفش کم‌رنگ: هدر جدول سفارش‌ها
  - خاکستری: پس‌زمینه

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
from typing import Optional, Any

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
# قالب HTML - شبیه TSETMC
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TSE Early Warning - ریتون</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Vazirmatn', 'Segoe UI', Tahoma, sans-serif;
            background: #e8ecef;
            color: #2c3e50;
            font-size: 13px;
            padding: 10px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        /* نوار عنوان مشکی - شبیه TSETMC */
        .header-bar {
            background: #1a1a1a;
            color: white;
            padding: 10px 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-radius: 6px 6px 0 0;
        }
        .header-bar .symbol-name {
            font-size: 15px;
            font-weight: bold;
        }
        .header-bar .clock {
            font-family: monospace;
            font-size: 14px;
            background: #2c5282;
            padding: 4px 10px;
            border-radius: 4px;
        }

        /* ردیف اول - سه ستون */
        .top-row {
            display: grid;
            grid-template-columns: 1fr 1.5fr 1fr;
            gap: 8px;
            margin-bottom: 8px;
        }

        /* کارت‌ها */
        .card {
            background: white;
            border-radius: 6px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .card-header {
            background: #4a5568;
            color: white;
            padding: 6px 10px;
            font-size: 12px;
            font-weight: bold;
            text-align: center;
        }

        /* جدول حقیقی/حقوقی - آبی تیره */
        .real-legal-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }
        .real-legal-table th {
            background: #2c5282;
            color: white;
            padding: 6px 4px;
            text-align: center;
            font-weight: 600;
        }
        .real-legal-table td {
            padding: 6px 4px;
            text-align: center;
            border-bottom: 1px solid #e2e8f0;
        }
        .real-legal-table tr.header-row td {
            background: #2c5282;
            color: white;
            font-weight: bold;
        }
        .real-legal-table .orange { color: #d97706; font-weight: bold; }
        .real-legal-table .green { color: #16a34a; font-weight: bold; }

        /* پنل قیمت لحظه‌ای */
        .price-panel {
            padding: 12px;
        }
        .last-price-box {
            background: #fee2e2;
            padding: 12px;
            border-radius: 6px;
            text-align: center;
            margin-bottom: 10px;
        }
        .last-price-value {
            font-size: 32px;
            font-weight: bold;
            color: #dc2626;
        }
        .last-price-change {
            font-size: 13px;
            color: #dc2626;
            margin-top: 4px;
        }
        .price-info-row {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 6px;
            margin-bottom: 8px;
        }
        .price-info-item {
            background: #f1f5f9;
            padding: 6px 8px;
            border-radius: 4px;
            text-align: center;
        }
        .price-info-label {
            font-size: 10px;
            color: #64748b;
            margin-bottom: 2px;
        }
        .price-info-value {
            font-size: 13px;
            font-weight: bold;
            color: #1e293b;
        }
        .range-bar {
            background: #e2e8f0;
            height: 8px;
            border-radius: 4px;
            margin: 8px 0;
            position: relative;
        }
        .range-fill {
            background: linear-gradient(90deg, #dc2626 0%, #fbbf24 50%, #16a34a 100%);
            height: 100%;
            border-radius: 4px;
        }
        .range-marker {
            position: absolute;
            top: -3px;
            width: 4px;
            height: 14px;
            background: #1e293b;
            border-radius: 2px;
        }
        .range-labels {
            display: flex;
            justify-content: space-between;
            font-size: 10px;
            color: #64748b;
        }

        /* پنل تغییر مالکیت */
        .ownership-panel {
            padding: 10px;
        }
        .ownership-label {
            font-size: 11px;
            color: #64748b;
            margin-bottom: 8px;
            text-align: center;
        }
        .ownership-buttons {
            display: flex;
            gap: 4px;
            margin-bottom: 12px;
        }
        .ownership-btn {
            flex: 1;
            padding: 6px 4px;
            text-align: center;
            border-radius: 4px;
            font-size: 10px;
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
            margin-top: 10px;
        }
        .nav-label {
            font-size: 10px;
            color: #16a34a;
        }
        .nav-value {
            font-size: 18px;
            font-weight: bold;
            color: #16a34a;
        }
        .nav-time {
            font-size: 10px;
            color: #64748b;
            margin-top: 2px;
        }

        /* ردیف دوم - نمودار و عمق بازار */
        .bottom-row {
            display: grid;
            grid-template-columns: 1fr 1.3fr;
            gap: 8px;
        }
        .chart-card {
            padding: 10px;
            height: 350px;
        }
        .chart-container {
            height: 280px;
            position: relative;
        }

        /* جدول عمق بازار - بنفش کم‌رنگ */
        .orderbook-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }
        .orderbook-table th {
            background: #ede9fe;
            color: #6b21a8;
            padding: 6px 4px;
            text-align: center;
            font-weight: 600;
            border-bottom: 2px solid #c4b5fd;
        }
        .orderbook-table td {
            padding: 5px 4px;
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
        .orderbook-table .vol-bar {
            position: relative;
        }
        .vol-bar-buy {
            background: rgba(220, 38, 38, 0.1);
            position: absolute;
            left: 0;
            top: 0;
            height: 100%;
            border-radius: 2px;
        }
        .vol-bar-sell {
            background: rgba(22, 163, 74, 0.1);
            position: absolute;
            right: 0;
            top: 0;
            height: 100%;
            border-radius: 2px;
        }

        /* پنل هشدار موتور */
        .alert-bar {
            background: white;
            border-radius: 6px;
            padding: 10px 15px;
            margin-top: 8px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .alert-scores {
            display: flex;
            gap: 15px;
        }
        .score-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            min-width: 80px;
        }
        .score-label {
            font-size: 10px;
            color: #64748b;
        }
        .score-value {
            font-size: 22px;
            font-weight: bold;
        }
        .score-value.sp { color: #dc2626; }
        .score-value.acc { color: #16a34a; }
        .score-bar {
            width: 100%;
            height: 4px;
            background: #e2e8f0;
            border-radius: 2px;
            margin-top: 4px;
            overflow: hidden;
        }
        .score-bar-fill-sp {
            height: 100%;
            background: #dc2626;
            transition: width 0.5s;
        }
        .score-bar-fill-acc {
            height: 100%;
            background: #16a34a;
            transition: width 0.5s;
        }
        .signal-badge {
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: bold;
            color: white;
        }
        .signal-normal { background: #64748b; }
        .signal-yellow { background: #f59e0b; }
        .signal-red { background: #dc2626; }
        .signal-green { background: #16a34a; }
        .signal-orange { background: #ea580c; }

        /* جدول نمونه‌های اخیر */
        .recent-card {
            margin-top: 8px;
        }
        .recent-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 11px;
        }
        .recent-table th {
            background: #4a5568;
            color: white;
            padding: 6px;
            text-align: center;
        }
        .recent-table td {
            padding: 4px 6px;
            text-align: center;
            border-bottom: 1px solid #e2e8f0;
        }
        .recent-table tr:hover { background: #f1f5f9; }

        .status-bar {
            background: white;
            padding: 8px 15px;
            border-radius: 6px;
            margin-bottom: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            font-size: 12px;
        }
        .live-dot {
            display: inline-block;
            width: 8px;
            height: 8px;
            background: #16a34a;
            border-radius: 50%;
            margin-left: 6px;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        .no-data { color: #94a3b8; text-align: center; padding: 20px; }
    </style>
</head>
<body>
<div class="container">

    <!-- نوار عنوان مشکی -->
    <div class="header-bar">
        <div class="symbol-name">صندوق سرمایه‌گذاری کالای پاسارگاد (ریتون)</div>
        <div>
            <span>زمان: </span>
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

        <!-- سمت راست: جدول حقیقی/حقوقی -->
        <div class="card">
            <div class="card-header">حقیقی / حقوقی</div>
            <table class="real-legal-table">
                <thead>
                    <tr>
                        <th></th>
                        <th>حجم</th>
                        <th>ارزش</th>
                        <th>تعداد</th>
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
                        <div class="price-info-label">فاز</div>
                        <div class="price-info-value" id="marketPhase">-</div>
                    </div>
                </div>
                <!-- نوار بازه مجاز -->
                <div class="range-labels">
                    <span>کف مجاز: <span id="minAllowed">-</span></span>
                    <span>سقف مجاز: <span id="maxAllowed">-</span></span>
                </div>
                <div class="range-bar">
                    <div class="range-fill"></div>
                    <div class="range-marker" id="priceMarker" style="left: 50%;"></div>
                </div>
                <div class="price-info-row">
                    <div class="price-info-item">
                        <div class="price-info-label">حجم معاملات</div>
                        <div class="price-info-value" id="totalVolume">-</div>
                    </div>
                    <div class="price-info-item">
                        <div class="price-info-label">ارزش معاملات</div>
                        <div class="price-info-value" id="totalValue">-</div>
                    </div>
                    <div class="price-info-item">
                        <div class="price-info-label">تعداد معامله</div>
                        <div class="price-info-value" id="totalTradeCount">-</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- سمت چپ: تغییر مالکیت و NAV -->
        <div class="card">
            <div class="card-header">تغییر مالکیت و NAV</div>
            <div class="ownership-panel">
                <div class="ownership-label">احتمال تغییر مالکیت (میانگین حجم فروش)</div>
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
                <div style="margin-top: 10px; font-size: 11px;">
                    <div style="display:flex; justify-content:space-between; padding: 4px 0;">
                        <span>قدرت خریدار:</span>
                        <strong id="buyerPower">-</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; padding: 4px 0;">
                        <span>ورود/خروج پول:</span>
                        <strong id="moneyFlow">-</strong>
                    </div>
                    <div style="display:flex; justify-content:space-between; padding: 4px 0;">
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
        <div class="signal-badge signal-normal" id="signalBadge">در حال دریافت داده...</div>
    </div>

    <!-- ردیف دوم: نمودار + عمق بازار -->
    <div class="bottom-row">
        <!-- نمودار -->
        <div class="card chart-card">
            <div class="card-header">نمودار قیمت</div>
            <div class="chart-container">
                <canvas id="priceChart"></canvas>
            </div>
        </div>

        <!-- عمق بازار -->
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
        console.error('خطا در دریافت داده:', err);
    }
}

function formatNumber(v, decimals) {
    if (v === null || v === undefined || v === 0) return '-';
    decimals = decimals || 0;
    return Number(v).toLocaleString('fa-IR', {minimumFractionDigits: 0, maximumFractionDigits: decimals});
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
    return {'pre_open':'پیش‌گشایش','continuous':'پیوسته','halted':'متوقف','closed':'بسته'}[p] || p;
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

        // حجم و ارزش
        document.getElementById('totalVolume').textContent = formatVolume(snap.total_volume);
        document.getElementById('totalValue').textContent = formatMoney(snap.total_value);
        document.getElementById('totalTradeCount').textContent = formatNumber(snap.total_trade_count);

        // جدول حقیقی/حقوقی
        if (snap.real_buy_count > 0 || snap.real_sell_count > 0) {
            document.getElementById('realLegalTable').innerHTML = `
                <tr class="header-row"><td colspan="4">حقیقی</td></tr>
                <tr>
                    <td>خرید</td>
                    <td>${formatVolume(snap.real_buy_volume)}</td>
                    <td>${formatMoney(snap.real_buy_value)}</td>
                    <td>${formatNumber(snap.real_buy_count)}</td>
                </tr>
                <tr>
                    <td>فروش</td>
                    <td>${formatVolume(snap.real_sell_volume)}</td>
                    <td>${formatMoney(snap.real_sell_value)}</td>
                    <td>${formatNumber(snap.real_sell_count)}</td>
                </tr>
                <tr class="header-row"><td colspan="4">حقوقی</td></tr>
                <tr>
                    <td>خرید</td>
                    <td>${formatVolume(snap.legal_buy_volume)}</td>
                    <td>${formatMoney(snap.legal_buy_value)}</td>
                    <td>${formatNumber(snap.legal_buy_count)}</td>
                </tr>
                <tr>
                    <td>فروش</td>
                    <td>${formatVolume(snap.legal_sell_volume)}</td>
                    <td>${formatMoney(snap.legal_sell_value)}</td>
                    <td>${formatNumber(snap.legal_sell_count)}</td>
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
            const maxVol = Math.max(...buyRows.map(r=>r.vol), ...sellRows.map(r=>r.vol));
            let html = '';
            for (let i = 0; i < 5; i++) {
                const b = buyRows[i] || {price:'-', vol:'-', count:'-'};
                const s = sellRows[i] || {price:'-', vol:'-', count:'-'};
                const bVolPct = b.vol && maxVol ? (b.vol / maxVol * 100) : 0;
                const sVolPct = s.vol && maxVol ? (s.vol / maxVol * 100) : 0;
                html += `<tr>
                    <td>${b.count || '-'}</td>
                    <td class="vol-bar" style="position:relative;">
                        <div class="vol-bar-buy" style="width:${bVolPct}%"></div>
                        <span style="position:relative;">${formatVolume(b.vol)}</span>
                    </td>
                    <td class="price-buy">${b.price || '-'}</td>
                    <td class="price-sell">${s.price || '-'}</td>
                    <td class="vol-bar" style="position:relative;">
                        <div class="vol-bar-sell" style="width:${sVolPct}%"></div>
                        <span style="position:relative;">${formatVolume(s.vol)}</span>
                    </td>
                    <td>${s.count || '-'}</td>
                </tr>`;
            }
            document.getElementById('orderBookTable').innerHTML = html;
        }

        // اطلاعات تکمیلی
        document.getElementById('buyerPower').textContent =
            snap.buyer_power ? snap.buyer_power.toFixed(2) : '-';
        const mf = snap.real_money_flow;
        if (mf) {
            const sign = mf >= 0 ? '+' : '';
            const color = mf >= 0 ? '#16a34a' : '#dc2626';
            document.getElementById('moneyFlow').innerHTML =
                `<span style="color:${color}">${sign}${formatMoney(mf)}</span>`;
        }
        document.getElementById('completeness').textContent =
            (data.last_snapshot.completeness_pct || 0) + '%';

        // NAV (در صورت وجود)
        if (snap.nav_value) {
            document.getElementById('navValue').textContent = formatNumber(snap.nav_value);
            document.getElementById('navTime').textContent = snap.nav_time || '-';
        }
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

    // به‌روزرسانی نمودار
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
                    legend: {
                        position: 'top',
                        labels: {font: {size: 11}}
                    }
                },
                scales: {
                    y: {ticks: {font: {size: 10}}},
                    x: {ticks: {font: {size: 9}, maxRotation: 0}}
                }
            }
        });
    }
}

// به‌روزرسانی خودکار هر ۵ ثانیه
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
               best_buy_price, best_sell_price, real_buy_count, real_buy_volume,
               real_sell_count, real_sell_volume, buy_order_count, sell_order_count,
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

    cur.execute("""
        SELECT trade_time, trade_price, trade_volume, trade_id, aggressor_side
        FROM trades ORDER BY trade_id_row DESC LIMIT 20
    """)
    trades = [dict(r) for r in cur.fetchall()]

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
        'recent_trades': trades,
        'alerts': [],
        'sell_pressure': sp,
        'accumulation': acc,
        'signal': signal,
    })


@app.route('/api/snapshots')
def api_snapshots():
    conn = get_db_conn()
    if conn is None:
        return jsonify({'snapshots': []})
    cur = conn.cursor()
    cur.execute("SELECT * FROM snapshots ORDER BY timestamp ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'snapshots': rows, 'count': len(rows)})


def main():
    parser = argparse.ArgumentParser(description='داشبورد وب TSE Early Warning v2.0')
    parser.add_argument('--port', type=int, default=8050, help='پورت سرور')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='میزبان')
    args = parser.parse_args()

    print("=" * 60)
    print("  TSE Early Warning - Dashboard v2.0 (TSETMC Style)")
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
