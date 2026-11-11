"""
web_dashboard.py (نسخه ۳.۰ - ساده برای مشاهده داده‌ها)
داشبورد وب برای بررسی داده‌های جمع‌آوری شده.

چیدمان مطابق TSETMC:
  ردیف اول (بالا): حقیقی/حقوقی + قیمت لحظه‌ای + بازه مجاز
  ردیف دوم (پایین): جدول عمق بازار + نمودار قیمت

ویژگی‌ها:
  - بدون نوار نماد فعال (نماد از config)
  - به‌روزرسانی خودکار هر ۵ ثانیه
  - نمایش داده‌های قیمت، حقیقی/حقوقی، عمق بازار، بازه مجاز
  - نمودار قیمت ساده

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
    from flask import Flask, render_template_string, jsonify
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


DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TSE Early Warning - داده‌های جمع‌آوری شده</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Vazirmatn', 'Segoe UI', Tahoma, sans-serif;
            background: #e8ecef;
            color: #2c3e50;
            font-size: 13px;
            padding: 10px;
        }
        .container { max-width: 1400px; margin: 0 auto; }

        /* نوار عنوان مشکی */
        .header-bar {
            background: #1a1a1a;
            color: white;
            padding: 10px 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-radius: 6px 6px 0 0;
            font-size: 14px;
        }
        .header-bar .symbol-name { font-weight: bold; }
        .header-bar .clock {
            font-family: monospace;
            background: #2c5282;
            padding: 4px 10px;
            border-radius: 4px;
            font-size: 13px;
        }

        /* نوار وضعیت */
        .status-bar {
            background: white;
            padding: 8px 15px;
            border-radius: 0 0 6px 6px;
            margin-bottom: 10px;
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

        /* ردیف اول - سه ستون */
        .top-row {
            display: grid;
            grid-template-columns: 1fr 1.4fr 1fr;
            gap: 10px;
            margin-bottom: 10px;
        }

        .card {
            background: white;
            border-radius: 6px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        .card-header {
            background: #4a5568;
            color: white;
            padding: 8px 12px;
            font-size: 13px;
            font-weight: bold;
            text-align: center;
        }

        /* جدول حقیقی/حقوقی */
        .real-legal-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12px;
        }
        .real-legal-table th {
            background: #2c5282;
            color: white;
            padding: 6px 4px;
            text-align: center;
            font-weight: 600;
            font-size: 11px;
        }
        .real-legal-table td {
            padding: 6px 4px;
            text-align: center;
            border-bottom: 1px solid #e2e8f0;
        }
        .real-legal-table .label-col {
            background: #ebf4ff;
            font-weight: bold;
            text-align: right;
            padding-right: 8px;
        }
        .real-legal-table .orange { color: #d97706; font-weight: bold; }

        /* پنل قیمت لحظه‌ای */
        .price-panel { padding: 12px; }
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

        /* بازه مجاز */
        .range-section {
            background: #fff7ed;
            padding: 8px;
            border-radius: 4px;
            margin: 8px 0;
        }
        .range-title {
            font-size: 11px;
            color: #92400e;
            font-weight: bold;
            text-align: center;
            margin-bottom: 6px;
        }
        .range-bar {
            background: #e2e8f0;
            height: 8px;
            border-radius: 4px;
            position: relative;
            margin: 4px 0;
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
        .range-values {
            display: flex;
            justify-content: space-between;
            font-size: 11px;
            margin-top: 4px;
        }

        /* آمار معاملات */
        .stats-row {
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 6px;
            margin-top: 8px;
        }
        .stats-item {
            background: #f8fafc;
            padding: 6px;
            border-radius: 4px;
            text-align: center;
        }
        .stats-label { font-size: 10px; color: #64748b; }
        .stats-value { font-size: 12px; font-weight: bold; color: #1e293b; }

        /* اطلاعات تکمیلی */
        .extra-info {
            margin-top: 10px;
            font-size: 12px;
            padding: 8px;
            background: #f8fafc;
            border-radius: 4px;
        }
        .extra-info-row {
            display: flex;
            justify-content: space-between;
            padding: 4px 0;
            border-bottom: 1px solid #e2e8f0;
        }
        .extra-info-row:last-child { border-bottom: none; }

        /* ردیف دوم */
        .bottom-row {
            display: grid;
            grid-template-columns: 1fr 1.3fr;
            gap: 10px;
            margin-bottom: 10px;
        }
        .chart-card { padding: 10px; }
        .chart-container {
            height: 280px;
            position: relative;
        }

        /* جدول عمق بازار */
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
            font-size: 11px;
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

        /* جدول نمونه‌های اخیر */
        .recent-card { margin-top: 10px; }
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

        .no-data { color: #94a3b8; text-align: center; padding: 15px; font-size: 12px; }
    </style>
</head>
<body>
<div class="container">

    <!-- نوار عنوان مشکی -->
    <div class="header-bar">
        <div class="symbol-name" id="symbolName">در حال بارگذاری...</div>
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
            <span id="newDataBadge" style="display:none;background:#dc2626;color:white;padding:2px 8px;border-radius:3px;font-size:10px;margin-right:8px;font-weight:bold;">NEW</span>
        </div>
        <div>
            آخرین نمونه: <strong id="lastSampleTime">-</strong>
            (<span id="timeAgo">-</span>)
            | تعداد: <strong id="totalCount">0</strong>
            | <span id="pollStatus" style="font-size:10px;color:#94a3b8;">در حال پایش...</span>
        </div>
    </div>

    <!-- ردیف اول: حقیقی/حقوقی + قیمت لحظه‌ای + بازه مجاز -->
    <div class="top-row">

        <!-- سمت راست: جدول حقیقی/حقوقی -->
        <div class="card">
            <div class="card-header">حقیقی / حقوقی</div>
            <table class="real-legal-table">
                <thead>
                    <tr>
                        <th></th>
                        <th>تعداد</th>
                        <th>حجم</th>
                    </tr>
                </thead>
                <tbody id="realLegalTable">
                    <tr><td colspan="3" class="no-data">داده‌ای دریافت نشده</td></tr>
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
                        <div class="price-info-label">بیشترین (بازه روز)</div>
                        <div class="price-info-value" id="dailyHigh" style="color:#16a34a;">-</div>
                    </div>
                    <div class="price-info-item">
                        <div class="price-info-label">کمترین (بازه روز)</div>
                        <div class="price-info-value" id="dailyLow" style="color:#dc2626;">-</div>
                    </div>
                    <div class="price-info-item">
                        <div class="price-info-label">فاز بازار</div>
                        <div class="price-info-value" id="marketPhase">-</div>
                    </div>
                </div>
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

        <!-- سمت چپ: بازه مجاز + اطلاعات تکمیلی -->
        <div class="card">
            <div class="card-header">قیمت مجاز و اطلاعات</div>
            <div class="price-panel">
                <div class="range-section">
                    <div class="range-title">قیمت مجاز روز</div>
                    <div class="range-bar">
                        <div class="range-fill"></div>
                        <div class="range-marker" id="priceMarker" style="left: 50%;"></div>
                    </div>
                    <div class="range-values">
                        <span>کف: <strong id="minAllowed">-</strong></span>
                        <span>سقف: <strong id="maxAllowed">-</strong></span>
                    </div>
                </div>

                <div class="extra-info">
                    <div class="extra-info-row">
                        <span>قدرت خریدار:</span>
                        <strong id="buyerPower">-</strong>
                    </div>
                    <div class="extra-info-row">
                        <span>سرانه خرید حقیقی:</span>
                        <strong id="perCapitaBuy">-</strong>
                    </div>
                    <div class="extra-info-row">
                        <span>سرانه فروش حقیقی:</span>
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
        <div class="card-header">آخرین ۱۵ نمونه جمع‌آوری شده</div>
        <table class="recent-table">
            <thead>
                <tr>
                    <th>زمان</th>
                    <th>فاز</th>
                    <th>آخرین</th>
                    <th>پایانی</th>
                    <th>حجم خرید</th>
                    <th>حجم فروش</th>
                    <th>قدرت خریدار</th>
                    <th>پول حقیقی</th>
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
let lastSnapshotId = 0;       // آخرین snapshot_id که دیده‌ایم
let lastTotalCount = 0;       // آخرین تعداد نمونه‌ها
let lastSampleTimestamp = null; // زمان آخرین نمونه

async function fetchData() {
    try {
        document.getElementById('pollStatus').textContent = 'در حال بررسی...';
        const response = await fetch('/api/data');
        const data = await response.json();

        // بررسی: آیا داده جدیدی هست؟
        const newCount = data.total_snapshots || 0;
        const isNewData = (newCount > lastTotalCount) || (lastTotalCount === 0);

        if (isNewData) {
            // داده جدید! فلش بزن
            if (lastTotalCount > 0) {
                showNewBadge();
            }
            lastTotalCount = newCount;
            updateUI(data);
            document.getElementById('pollStatus').textContent = '✓ به‌روزرسانی شد';
        } else {
            // داده جدیدی نیست
            document.getElementById('pollStatus').textContent = 'منتظر داده جدید...';
        }

        // به‌روزرسانی زمان گذشته
        updateTimeAgo(data);
    } catch (err) {
        console.error('خطا:', err);
        document.getElementById('pollStatus').textContent = '⚠ خطا در ارتباط';
    }
}

function showNewBadge() {
    const badge = document.getElementById('newDataBadge');
    badge.style.display = 'inline-block';
    setTimeout(() => {
        badge.style.display = 'none';
    }, 3000);
}

function updateTimeAgo(data) {
    const snap = data.last_snapshot;
    if (snap && snap.tehran_time) {
        document.getElementById('lastSampleTime').textContent = snap.tehran_time;
        // محاسبه زمان گذشته (تقریبی)
        const now = new Date();
        const [h, m, s] = snap.tehran_time.split(':').map(Number);
        const sampleTime = new Date();
        sampleTime.setHours(h, m, s || 0, 0);
        const diffSec = Math.floor((now - sampleTime) / 1000);
        if (diffSec < 0) diffSec = 0;
        if (diffSec < 60) {
            document.getElementById('timeAgo').textContent = diffSec + ' ثانیه پیش';
        } else if (diffSec < 3600) {
            document.getElementById('timeAgo').textContent = Math.floor(diffSec / 60) + ' دقیقه پیش';
        } else {
            document.getElementById('timeAgo').textContent = Math.floor(diffSec / 3600) + ' ساعت پیش';
        }
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
    if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(2) + ' M ت';
    if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(0) + ' K ت';
    return formatNumber(v) + ' ت';
}

function phaseLabel(p) {
    return {'pre_open':'پیش‌گشایش','continuous':'پیوسته','halted':'متوقف','closed':'بسته'}[p] || p || '-';
}

function updateUI(data) {
    document.getElementById('clock').textContent = data.last_update || '--:--:--';
    document.getElementById('lastUpdate').textContent = data.last_update || '-';
    document.getElementById('totalCount').textContent = data.total_snapshots || 0;

    if (data.symbol) {
        document.getElementById('symbolName').textContent = 'نماد: ' + data.symbol;
    }

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

        // تغییر قیمت
        if (snap.yesterday_price > 0 && snap.last_price > 0) {
            const change = snap.last_price - snap.yesterday_price;
            const changePct = (change / snap.yesterday_price) * 100;
            const sign = change >= 0 ? '+' : '';
            const color = change >= 0 ? '#16a34a' : '#dc2626';
            document.getElementById('priceChange').innerHTML =
                '<span style="color:' + color + '">' + sign + formatNumber(change) +
                ' (' + sign + changePct.toFixed(2) + '%)</span>';
        }

        // بازه مجاز
        document.getElementById('minAllowed').textContent = formatNumber(snap.min_allowed_price);
        document.getElementById('maxAllowed').textContent = formatNumber(snap.max_allowed_price);
        if (snap.min_allowed_price > 0 && snap.max_allowed_price > 0 && snap.last_price > 0) {
            const pct = ((snap.last_price - snap.min_allowed_price) /
                         (snap.max_allowed_price - snap.min_allowed_price)) * 100;
            document.getElementById('priceMarker').style.left = Math.max(0, Math.min(100, pct)) + '%';
        }

        // آمار معاملات
        document.getElementById('totalTradeCount').textContent = formatNumber(snap.total_trade_count);
        document.getElementById('totalVolume').textContent = formatVolume(snap.total_volume);
        document.getElementById('totalValue').textContent = formatMoney(snap.total_value);

        // جدول حقیقی/حقوقی
        const rb = snap.real_buy_count || 0;
        const rs = snap.real_sell_count || 0;
        const lb = snap.legal_buy_count || 0;
        const ls = snap.legal_sell_count || 0;
        const rbv = snap.real_buy_volume || 0;
        const rsv = snap.real_sell_volume || 0;
        const lbv = snap.legal_buy_volume || 0;
        const lsv = snap.legal_sell_volume || 0;

        if (rb > 0 || rs > 0 || lb > 0 || ls > 0) {
            document.getElementById('realLegalTable').innerHTML =
                '<tr><td class="label-col">حقیقی (خرید)</td><td>' + formatNumber(rb) + '</td><td>' + formatVolume(rbv) + '</td></tr>' +
                '<tr><td class="label-col">حقوقی (خرید)</td><td>' + formatNumber(lb) + '</td><td>' + formatVolume(lbv) + '</td></tr>' +
                '<tr><td class="label-col">حقیقی (فروش)</td><td>' + formatNumber(rs) + '</td><td>' + formatVolume(rsv) + '</td></tr>' +
                '<tr><td class="label-col">حقوقی (فروش)</td><td>' + formatNumber(ls) + '</td><td>' + formatVolume(lsv) + '</td></tr>';
        }

        // عمق بازار
        const buyRows = [
            {p: snap.bid_price_1, v: snap.bid_volume_1, c: snap.bid_count_1},
            {p: snap.bid_price_2, v: snap.bid_volume_2, c: snap.bid_count_2},
            {p: snap.bid_price_3, v: snap.bid_volume_3, c: snap.bid_count_3},
            {p: snap.bid_price_4, v: snap.bid_volume_4, c: snap.bid_count_4},
            {p: snap.bid_price_5, v: snap.bid_volume_5, c: snap.bid_count_5},
        ].filter(r => r.p);
        const sellRows = [
            {p: snap.ask_price_1, v: snap.ask_volume_1, c: snap.ask_count_1},
            {p: snap.ask_price_2, v: snap.ask_volume_2, c: snap.ask_count_2},
            {p: snap.ask_price_3, v: snap.ask_volume_3, c: snap.ask_count_3},
            {p: snap.ask_price_4, v: snap.ask_volume_4, c: snap.ask_count_4},
            {p: snap.ask_price_5, v: snap.ask_volume_5, c: snap.ask_count_5},
        ].filter(r => r.p);

        if (buyRows.length > 0 && sellRows.length > 0) {
            let html = '';
            for (let i = 0; i < 5; i++) {
                const b = buyRows[i] || {p:'-', v:'-', c:'-'};
                const s = sellRows[i] || {p:'-', v:'-', c:'-'};
                html += '<tr>' +
                    '<td>' + (b.c || '-') + '</td>' +
                    '<td>' + formatVolume(b.v) + '</td>' +
                    '<td class="price-buy">' + (b.p || '-') + '</td>' +
                    '<td class="price-sell">' + (s.p || '-') + '</td>' +
                    '<td>' + formatVolume(s.v) + '</td>' +
                    '<td>' + (s.c || '-') + '</td>' +
                    '</tr>';
            }
            document.getElementById('orderBookTable').innerHTML = html;
        }

        // اطلاعات تکمیلی
        document.getElementById('buyerPower').textContent = snap.buyer_power ? snap.buyer_power.toFixed(2) : '-';
        document.getElementById('perCapitaBuy').textContent = snap.per_capita_buy_real ? formatVolume(snap.per_capita_buy_real) : '-';
        document.getElementById('perCapitaSell').textContent = snap.per_capita_sell_real ? formatVolume(snap.per_capita_sell_real) : '-';

        const mf = snap.real_money_flow;
        if (mf) {
            const sign = mf >= 0 ? '+' : '';
            const color = mf >= 0 ? '#16a34a' : '#dc2626';
            document.getElementById('moneyFlow').innerHTML =
                '<span style="color:' + color + '">' + sign + formatMoney(mf) + '</span>';
        }
        document.getElementById('completeness').textContent = (snap.completeness_pct || 0) + '%';
    }

    // جدول نمونه‌های اخیر
    if (data.recent_snapshots && data.recent_snapshots.length > 0) {
        let html = '';
        for (const s of data.recent_snapshots) {
            const mf = s.real_money_flow;
            const mfStr = mf ? (mf >= 0 ? '+' + formatVolume(mf) : formatVolume(mf)) : '-';
            const mfColor = mf >= 0 ? '#16a34a' : '#dc2626';
            html += '<tr>' +
                '<td>' + (s.tehran_time || '-') + '</td>' +
                '<td>' + phaseLabel(s.market_phase) + '</td>' +
                '<td>' + formatNumber(s.last_price) + '</td>' +
                '<td>' + formatNumber(s.close_price) + '</td>' +
                '<td>' + formatVolume(s.best_buy_volume) + '</td>' +
                '<td>' + formatVolume(s.best_sell_volume) + '</td>' +
                '<td>' + (s.buyer_power ? s.buyer_power.toFixed(1) : '-') + '</td>' +
                '<td style="color:' + mfColor + '">' + mfStr + '</td>' +
                '<td>' + (s.completeness_pct || 0) + '%</td>' +
                '</tr>';
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

// به‌روزرسانی خودکار هر ۱ ثانیه (بررسی داده جدید)
// فقط وقتی داده جدیدی در بانک هست، UI به‌روزرسانی می‌شود
fetchData();
setInterval(fetchData, 1000);

// به‌روزرسانی زمان گذشته و ساعت هر ۱ ثانیه
setInterval(() => {
    document.getElementById('clock').textContent = new Date().toLocaleTimeString('fa-IR');
    // به‌روزرسانی زمان گذشته
    if (lastTotalCount > 0) {
        const now = new Date();
        // این در fetchData هم انجام می‌شود ولی اینجا هم برای زمان‌های بین polling
    }
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
        # نماد را از پیکربندی بخوان
        symbol = 'نامشخص'
        try:
            config = json.loads((ROOT / "config" / "warning_thresholds.json").read_text(encoding='utf-8'))
            symbol = config["test_symbol"]["name"]
        except Exception:
            pass
        return jsonify({
            'last_update': datetime.now().strftime('%H:%M:%S'),
            'total_snapshots': 0,
            'total_trades': 0,
            'symbol': symbol,
            'last_snapshot': None,
            'recent_snapshots': [],
            'recent_trades': [],
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
               real_money_flow, total_volume, total_value, total_trade_count,
               real_buy_count, real_buy_volume, real_sell_count, real_sell_volume,
               legal_buy_count, legal_buy_volume, legal_sell_count, legal_sell_volume,
               per_capita_buy_real, per_capita_sell_real,
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

    conn.close()

    # نماد را از پیکربندی بخوان
    symbol = 'نامشخص'
    try:
        config = json.loads((ROOT / "config" / "warning_thresholds.json").read_text(encoding='utf-8'))
        symbol = config["test_symbol"]["name"]
    except Exception:
        pass
    if last_snap and last_snap.get('symbol'):
        symbol = last_snap['symbol']

    return jsonify({
        'last_update': datetime.now().strftime('%H:%M:%S'),
        'total_snapshots': total_snapshots,
        'total_trades': total_trades,
        'symbol': symbol,
        'last_snapshot': last_snap,
        'recent_snapshots': recent,
        'recent_trades': [],
    })


def main():
    parser = argparse.ArgumentParser(description='داشبورد وب v3.0')
    parser.add_argument('--port', type=int, default=8050, help='پورت سرور')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='میزبان')
    args = parser.parse_args()

    print("=" * 60)
    print("  TSE Early Warning - Dashboard v3.0")
    print("=" * 60)
    print()
    print(f"  Database: {DB_PATH}")
    print(f"  URL:      http://{args.host}:{args.port}")
    print()
    print("  برای توقف: Ctrl+C")
    print("-" * 60)

    try:
        app.run(host=args.host, port=args.port, debug=False)
    except KeyboardInterrupt:
        print("\n✓ سرور متوقف شد")


if __name__ == '__main__':
    main()
