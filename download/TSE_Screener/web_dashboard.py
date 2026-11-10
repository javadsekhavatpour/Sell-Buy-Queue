"""
web_dashboard.py
داشبورد وب زنده برای مشاهده داده‌های جمع‌آوری‌شده در مرورگر.

این اسکریپت یک سرور وب محلی راه‌اندازی می‌کند که هر ۵ ثانیه داده‌های
SQLite را به‌صورت خودکار به‌روزرسانی می‌کند. با این روش:
  ✓ مشکل فونت فارسی در کنسول Windows حل می‌شود
  ✓ می‌توانید داده‌ها را در مرورگر ببینید
  ✓ نمودارهای زنده از امتیازها و قیمت‌ها
  ✓ جدول هشدارها و رویدادها
  ✓ نمایش معاملات اخیر

نحوه اجرا:
  python web_dashboard.py
  # سپس مرورگر را باز کنید: http://localhost:8050

  # یا با پورت دلخواه:
  python web_dashboard.py --port 8000

نیازمندی: pip install flask
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    from flask import Flask, render_template_string, jsonify, request
except ImportError:
    print("❌ کتابخانه Flask نصب نیست.")
    print("   نصب با: pip install flask")
    sys.exit(1)

# تنظیم encoding برای Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "early_warning_live.sqlite"

app = Flask(__name__)


# ---------------------------------------------------------------------------
# قالب HTML داشبورد
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>TSE Early Warning - داشبورد زنده</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Vazirmatn', 'Segoe UI', Tahoma, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
            color: #2c3e50;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
        }
        header {
            background: linear-gradient(135deg, #1F4E78 0%, #2E75B6 100%);
            color: white;
            padding: 25px 30px;
        }
        header h1 { font-size: 24px; margin-bottom: 5px; }
        header .meta { font-size: 14px; opacity: 0.9; }
        .status-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: #f8f9fa;
            padding: 15px 30px;
            border-bottom: 1px solid #e9ecef;
        }
        .status-item {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 14px;
        }
        .status-dot {
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #28a745;
            animation: pulse 2s infinite;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(1.2); }
        }
        .last-update { color: #6c757d; font-size: 13px; }

        .dashboard {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            padding: 30px;
        }
        .card {
            background: white;
            border-radius: 12px;
            padding: 20px;
            border: 2px solid #e9ecef;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }
        .card.full-width { grid-column: 1 / -1; }
        .card-title {
            font-size: 16px;
            font-weight: bold;
            color: #1F4E78;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 2px solid #f0f0f0;
        }
        .score-display {
            display: flex;
            align-items: center;
            justify-content: space-around;
            gap: 20px;
        }
        .score-card {
            flex: 1;
            text-align: center;
            padding: 20px;
            border-radius: 10px;
            color: white;
        }
        .score-card.sell-pressure {
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a52 100%);
        }
        .score-card.accumulation {
            background: linear-gradient(135deg, #4caf50 0%, #2e7d32 100%);
        }
        .score-value {
            font-size: 48px;
            font-weight: bold;
            margin: 10px 0;
        }
        .score-label {
            font-size: 14px;
            opacity: 0.9;
        }
        .score-level {
            font-size: 16px;
            margin-top: 5px;
            font-weight: bold;
        }

        .signal-box {
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            font-size: 18px;
            font-weight: bold;
            margin-top: 15px;
        }
        .signal-normal { background: #f8f9fa; color: #6c757d; }
        .signal-yellow { background: #ffc107; color: #856404; }
        .signal-red { background: #dc3545; color: white; }
        .signal-green { background: #28a745; color: white; }
        .signal-orange { background: #fd7e14; color: white; }

        .data-row {
            display: flex;
            justify-content: space-between;
            padding: 8px 0;
            border-bottom: 1px solid #f0f0f0;
            font-size: 14px;
        }
        .data-row:last-child { border-bottom: none; }
        .data-label { color: #6c757d; }
        .data-value { font-weight: bold; }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        th {
            background: #1F4E78;
            color: white;
            padding: 10px;
            text-align: center;
            font-weight: bold;
        }
        td {
            padding: 8px 10px;
            text-align: center;
            border-bottom: 1px solid #e9ecef;
        }
        tr:nth-child(even) { background: #f8f9fa; }
        tr:hover { background: #e9ecef; }

        .phase-tag {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: bold;
        }
        .phase-continuous { background: #d4edda; color: #155724; }
        .phase-pre_open { background: #fff3cd; color: #856404; }
        .phase-halted { background: #f8d7da; color: #721c24; }

        .alert-row { background: #fff3cd !important; }
        .alert-row-red { background: #f8d7da !important; }
        .alert-row-green { background: #d4edda !important; }

        .no-data {
            text-align: center;
            padding: 40px;
            color: #6c757d;
            font-size: 16px;
        }
        .footer {
            padding: 20px 30px;
            text-align: center;
            color: #6c757d;
            font-size: 13px;
            background: #f8f9fa;
        }
        .auto-refresh-note {
            font-size: 12px;
            color: #6c757d;
            margin-top: 5px;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📊 TSE Early Warning Engine - داشبورد زنده</h1>
            <div class="meta">نماد: <span id="symbol">ریتون</span> | پایگاه داده: early_warning_live.sqlite</div>
        </header>

        <div class="status-bar">
            <div class="status-item">
                <div class="status-dot"></div>
                <span>پایش زنده فعال</span>
            </div>
            <div class="status-item">
                <span>آخرین به‌روزرسانی:</span>
                <span class="last-update" id="lastUpdate">-</span>
            </div>
            <div class="status-item">
                <span>تعداد نمونه‌ها: <strong id="totalCount">0</strong></span>
            </div>
        </div>

        <div class="dashboard">
            <!-- امتیازها -->
            <div class="card">
                <div class="card-title">🎯 امتیازهای موتور تحلیلی</div>
                <div class="score-display">
                    <div class="score-card sell-pressure">
                        <div class="score-label">Sell Pressure</div>
                        <div class="score-value" id="spScore">-</div>
                        <div class="score-level" id="spLevel">-</div>
                    </div>
                    <div class="score-card accumulation">
                        <div class="score-label">Accumulation</div>
                        <div class="score-value" id="accScore">-</div>
                        <div class="score-level" id="accLevel">-</div>
                    </div>
                </div>
                <div class="signal-box signal-normal" id="signalBox">
                    وضعیت عادی - ادامه پایش
                </div>
            </div>

            <!-- اطلاعات آخرین نمونه -->
            <div class="card">
                <div class="card-title">📋 آخرین نمونه تابلو</div>
                <div id="lastSnapshot">
                    <div class="no-data">هنوز داده‌ای دریافت نشده</div>
                </div>
            </div>

            <!-- نمونه‌های اخیر -->
            <div class="card full-width">
                <div class="card-title">🕐 آخرین ۱۵ نمونه</div>
                <div id="recentTable">
                    <div class="no-data">هنوز داده‌ای دریافت نشده</div>
                </div>
            </div>

            <!-- معاملات اخیر -->
            <div class="card full-width">
                <div class="card-title">📈 آخرین ۲۰ معامله</div>
                <div id="tradesTable">
                    <div class="no-data">هنوز معامله‌ای دریافت نشده</div>
                </div>
            </div>

            <!-- رویدادهای هشدار -->
            <div class="card full-width">
                <div class="card-title">🚨 رویدادهای هشدار</div>
                <div id="alertsTable">
                    <div class="no-data">هیچ هشداری صادر نشده</div>
                </div>
            </div>
        </div>

        <div class="footer">
            <div>TSE Early Warning Engine v1.1 - داشبورد زنده</div>
            <div class="auto-refresh-note">صفحه هر ۵ ثانیه به‌صورت خودکار به‌روزرسانی می‌شود</div>
        </div>
    </div>

    <script>
        async function fetchData() {
            try {
                const response = await fetch('/api/data');
                const data = await response.json();
                updateUI(data);
            } catch (err) {
                console.error('خطا در دریافت داده:', err);
            }
        }

        function updateUI(data) {
            document.getElementById('lastUpdate').textContent = data.last_update;
            document.getElementById('totalCount').textContent = data.total_snapshots;
            document.getElementById('symbol').textContent = data.symbol || 'ریتون';

            // امتیازها
            const sp = data.sell_pressure;
            const acc = data.accumulation;
            document.getElementById('spScore').textContent = sp ? sp.score.toFixed(0) : '-';
            document.getElementById('spLevel').textContent = sp ? sp.level : '-';
            document.getElementById('accScore').textContent = acc ? acc.score.toFixed(0) : '-';
            document.getElementById('accLevel').textContent = acc ? acc.level : '-';

            // سیگنال
            const sig = data.signal;
            const sigBox = document.getElementById('signalBox');
            sigBox.textContent = sig.message;
            sigBox.className = 'signal-box ' + sig.css_class;

            // آخرین نمونه
            const lastSnap = data.last_snapshot;
            if (lastSnap) {
                document.getElementById('lastSnapshot').innerHTML = buildSnapshotTable(lastSnap);
            }

            // نمونه‌های اخیر
            if (data.recent_snapshots && data.recent_snapshots.length > 0) {
                document.getElementById('recentTable').innerHTML = buildRecentTable(data.recent_snapshots);
            }

            // معاملات
            if (data.recent_trades && data.recent_trades.length > 0) {
                document.getElementById('tradesTable').innerHTML = buildTradesTable(data.recent_trades);
            }

            // هشدارها
            if (data.alerts && data.alerts.length > 0) {
                document.getElementById('alertsTable').innerHTML = buildAlertsTable(data.alerts);
            }
        }

        function phaseLabel(p) {
            const labels = {
                'pre_open': 'پیش‌گشایش',
                'continuous': 'پیوسته',
                'halted': 'متوقف',
                'closed': 'بسته'
            };
            return labels[p] || p;
        }

        function phaseClass(p) {
            return 'phase-' + (p || 'continuous');
        }

        function formatMoney(v) {
            if (v === null || v === undefined || v === 0) return '<span style="color:#999">—</span>';
            if (Math.abs(v) >= 1e9) return (v/1e9).toFixed(2) + ' میلیارد تومان';
            if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(1) + ' میلیون تومان';
            return v.toLocaleString('fa-IR') + ' تومان';
        }

        function formatVolume(v) {
            if (v === null || v === undefined || v === 0) return '<span style="color:#999">—</span>';
            if (Math.abs(v) >= 1e6) return (v/1e6).toFixed(2) + ' میلیون سهم';
            if (Math.abs(v) >= 1e3) return (v/1e3).toFixed(1) + ' هزار سهم';
            return v.toLocaleString('fa-IR') + ' سهم';
        }

        function formatPrice(v) {
            if (v === null || v === undefined || v === 0) return '<span style="color:#999">—</span>';
            return v.toLocaleString('fa-IR') + ' تومان';
        }

        function formatNumber(v, decimals) {
            if (v === null || v === undefined || v === 0) return '<span style="color:#999">—</span>';
            return Number(v).toFixed(decimals || 2);
        }

        function completenessColor(pct) {
            if (pct >= 80) return 'color: #28a745; font-weight: bold;';
            if (pct >= 50) return 'color: #ffc107; font-weight: bold;';
            return 'color: #dc3545; font-weight: bold;';
        }

        function buildSnapshotTable(s) {
            const moneyFlow = s.real_money_flow;
            const moneyColor = moneyFlow > 0 ? 'color: #28a745;' :
                              (moneyFlow < 0 ? 'color: #dc3545;' : 'color: #6c757d;');

            return `
                <div class="data-row">
                    <span class="data-label">⏰ زمان نمونه</span>
                    <span class="data-value">${s.tehran_time || '-'}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">📍 فاز بازار</span>
                    <span class="data-value"><span class="phase-tag ${phaseClass(s.market_phase)}">${phaseLabel(s.market_phase)}</span></span>
                </div>
                <div class="data-row">
                    <span class="data-label">💰 آخرین قیمت</span>
                    <span class="data-value">${formatPrice(s.last_price)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">💎 قیمت پایانی</span>
                    <span class="data-value">${formatPrice(s.close_price)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">📊 اولین قیمت روز</span>
                    <span class="data-value">${formatPrice(s.open_price)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">⬆️ بالاترین روز</span>
                    <span class="data-value">${formatPrice(s.daily_high)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">⬇️ پایین‌ترین روز</span>
                    <span class="data-value">${formatPrice(s.daily_low)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">📈 حجم کل معاملات</span>
                    <span class="data-value">${formatVolume(s.total_volume)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">💵 ارزش کل معاملات</span>
                    <span class="data-value">${formatMoney(s.total_value)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">🛒 بهترین خرید (حجم)</span>
                    <span class="data-value">${formatVolume(s.best_buy_volume)} <span style="color:#6c757d">@ ${formatPrice(s.best_buy_price)}</span></span>
                </div>
                <div class="data-row">
                    <span class="data-label">🏷️ بهترین فروش (حجم)</span>
                    <span class="data-value">${formatVolume(s.best_sell_volume)} <span style="color:#6c757d">@ ${formatPrice(s.best_sell_price)}</span></span>
                </div>
                <div class="data-row">
                    <span class="data-label">💪 قدرت خریدار</span>
                    <span class="data-value">${formatNumber(s.buyer_power, 2)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">💵 ورود/خروج پول حقیقی</span>
                    <span class="data-value" style="${moneyColor}">${formatMoney(s.real_money_flow)}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">👥 خریداران حقیقی</span>
                    <span class="data-value">${(s.real_buy_count || 0).toLocaleString('fa-IR')}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">👥 فروشندگان حقیقی</span>
                    <span class="data-value">${(s.real_sell_count || 0).toLocaleString('fa-IR')}</span>
                </div>
                <div class="data-row">
                    <span class="data-label">✓ کمال داده</span>
                    <span class="data-value" style="${completenessColor(s.completeness_pct)}">${s.completeness_pct || 0}٪</span>
                </div>
            `;
        }

        function buildRecentTable(snaps) {
            if (!snaps || snaps.length === 0) return '<div class="no-data">داده‌ای موجود نیست</div>';
            let html = `
                <table>
                    <thead>
                        <tr>
                            <th>زمان</th>
                            <th>فاز</th>
                            <th>آخرین قیمت</th>
                            <th>پایانی</th>
                            <th>حجم بهترین خرید</th>
                            <th>حجم بهترین فروش</th>
                            <th>قدرت خریدار</th>
                            <th>پول حقیقی</th>
                            <th>کمال</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            for (const s of snaps) {
                const money = s.real_money_flow ? formatMoney(s.real_money_flow) : '-';
                html += `
                    <tr>
                        <td>${s.tehran_time || '-'}</td>
                        <td><span class="phase-tag ${phaseClass(s.market_phase)}">${phaseLabel(s.market_phase)}</span></td>
                        <td>${(s.last_price || 0).toLocaleString('fa-IR')}</td>
                        <td>${(s.close_price || 0).toLocaleString('fa-IR')}</td>
                        <td>${(s.best_buy_volume || 0).toLocaleString('fa-IR')}</td>
                        <td>${(s.best_sell_volume || 0).toLocaleString('fa-IR')}</td>
                        <td>${(s.buyer_power || 0).toFixed(2)}</td>
                        <td>${money}</td>
                        <td>${s.completeness_pct || 0}%</td>
                    </tr>
                `;
            }
            html += '</tbody></table>';
            return html;
        }

        function buildTradesTable(trades) {
            if (!trades || trades.length === 0) return '<div class="no-data">معامله‌ای موجود نیست</div>';
            let html = `
                <table>
                    <thead>
                        <tr>
                            <th>زمان</th>
                            <th>قیمت</th>
                            <th>حجم</th>
                            <th>شناسه</th>
                            <th>سمت آغازگر</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            for (const t of trades) {
                const sideLabel = t.aggressor_side === 'buy' ? '🟢 خرید' : (t.aggressor_side === 'sell' ? '🔴 فروش' : 'نامشخص');
                const sideColor = t.aggressor_side === 'buy' ? 'color: #28a745;' : (t.aggressor_side === 'sell' ? 'color: #dc3545;' : '');
                html += `
                    <tr>
                        <td>${t.trade_time || '-'}</td>
                        <td>${(t.trade_price || 0).toLocaleString('fa-IR')}</td>
                        <td>${(t.trade_volume || 0).toLocaleString('fa-IR')}</td>
                        <td>${t.trade_id || '-'}</td>
                        <td style="${sideColor}; font-weight: bold;">${sideLabel}</td>
                    </tr>
                `;
            }
            html += '</tbody></table>';
            return html;
        }

        function buildAlertsTable(alerts) {
            if (!alerts || alerts.length === 0) return '<div class="no-data">هیچ هشداری صادر نشده</div>';
            let html = `
                <table>
                    <thead>
                        <tr>
                            <th>زمان</th>
                            <th>سطح</th>
                            <th>عنوان</th>
                            <th>فشار فروش</th>
                            <th>جمع‌آوری</th>
                        </tr>
                    </thead>
                    <tbody>
            `;
            for (const a of alerts) {
                const rowClass = a.level && a.level.includes('قرمز') ? 'alert-row-red' :
                                  a.level && a.level.includes('سبز') ? 'alert-row-green' :
                                  'alert-row';
                html += `
                    <tr class="${rowClass}">
                        <td>${a.timestamp || '-'}</td>
                        <td><strong>${a.level || '-'}</strong></td>
                        <td>${a.title || '-'}</td>
                        <td>${a.sell_pressure_score || 0}</td>
                        <td>${a.accumulation_score || 0}</td>
                    </tr>
                `;
            }
            html += '</tbody></table>';
            return html;
        }

        // به‌روزرسانی خودکار هر ۵ ثانیه
        fetchData();
        setInterval(fetchData, 5000);
    </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# توابع کمکی برای دریافت داده از SQLite
# ---------------------------------------------------------------------------

def get_db_conn():
    if not DB_PATH.exists():
        return None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def compute_completeness(snap_dict):
    """
    محاسبه درصد کمال داده یک نمونه.
    بر اساس فیلدهای حیاتی (CRITICAL) و اختیاری (OPTIONAL).
    """
    if not snap_dict:
        return 0

    # فیلدهای حیاتی (هر کدام ۸ امتیاز = ۸۰٪ از ۱۰۰٪)
    critical_fields = [
        'last_price', 'close_price',
        'best_buy_price', 'best_buy_volume',
        'best_sell_price', 'best_sell_volume',
        'total_volume', 'total_value',
    ]
    # فیلدهای اختیاری (هر کدام ۲ امتیاز = ۲۰٪ از ۱۰۰٪)
    optional_fields = [
        'real_buy_count', 'real_buy_volume',
        'real_sell_count', 'real_sell_volume',
        'legal_buy_count', 'legal_sell_count',
        'buyer_power', 'real_money_flow',
        'buy_order_count', 'sell_order_count',
    ]

    # در پیش‌گشایش، حجم/ارزش معاملات هنوز صفر است -> نادیده بگیر
    is_pre_open = snap_dict.get('market_phase') == 'pre_open'

    critical_filled = 0
    for f in critical_fields:
        if is_pre_open and f in ('total_volume', 'total_value'):
            critical_filled += 1  # در پیش‌گشایش این فیلدها صفرند ولی مشکلی نیست
            continue
        v = snap_dict.get(f)
        if v is not None and v != 0:
            critical_filled += 1

    optional_filled = 0
    for f in optional_fields:
        v = snap_dict.get(f)
        if v is not None and v != 0:
            optional_filled += 1

    # درصد: ۸۰٪ حیاتی + ۲۰٪ اختیاری
    pct = 80 * (critical_filled / len(critical_fields)) + 20 * (optional_filled / len(optional_fields))
    return int(min(100, max(0, pct)))


def compute_scores(snap_dict):
    """محاسبه ساده امتیازها برای نمایش (بدون اجرای کامل موتورها)."""
    if not snap_dict:
        return None, None

    # Sell Pressure تقریبی
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

    # Accumulation تقریبی
    acc_score = 0
    if snap_dict.get('buyer_power') and snap_dict['buyer_power'] > 1:
        acc_score += 20 * min(1, (snap_dict['buyer_power'] - 1) / 0.5)
    if snap_dict.get('real_money_flow_ratio') and snap_dict['real_money_flow_ratio'] > 0:
        acc_score += 20 * min(1, snap_dict['real_money_flow_ratio'] / 0.05)
    acc_score = min(100, max(0, acc_score))

    # سطوح
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
    """تعیین سیگنال نهایی."""
    if not sp or not acc:
        return {'message': 'در حال دریافت داده...', 'css_class': 'signal-normal'}

    sp_score = sp['score']
    acc_score = acc['score']

    if sp_score >= 50 and acc_score < 40:
        return {
            'message': '🔴 هشدار قرمز - ریسک خروج: فشار فروش در حال تشدید است',
            'css_class': 'signal-red'
        }
    if sp_score >= 50 and acc_score >= 40:
        return {
            'message': '🟠 جذب عرضه + فشار فروش هم‌زمان - خروج عجولانه توصیه نمی‌شود',
            'css_class': 'signal-orange'
        }
    if acc_score >= 40:
        return {
            'message': '🟢 هشدار سبز - خریداران قدرتمند در حال جذب عرضه',
            'css_class': 'signal-green'
        }
    if sp_score >= 35:
        return {
            'message': '🟡 هشدار زرد - نشانه‌های اولیه ضعف تقاضا',
            'css_class': 'signal-yellow'
        }
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

    # خلاصه
    cur.execute("SELECT COUNT(*) FROM snapshots")
    total_snapshots = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trades")
    total_trades = cur.fetchone()[0]

    # آخرین نمونه
    cur.execute("""
        SELECT * FROM snapshots ORDER BY timestamp DESC LIMIT 1
    """)
    last_row = cur.fetchone()
    last_snap = dict(last_row) if last_row else None

    # محاسبه کمال داده با تابع صحیح
    if last_snap:
        last_snap['completeness_pct'] = compute_completeness(last_snap)

    # نمونه‌های اخیر (۱۵ نمونه)
    cur.execute("""
        SELECT tehran_time, market_phase, last_price, close_price,
               best_buy_volume, best_sell_volume, buyer_power,
               real_money_flow, data_complete, total_volume, total_value,
               best_buy_price, best_sell_price, real_buy_count, real_buy_volume,
               real_sell_count, real_sell_volume, buy_order_count, sell_order_count
        FROM snapshots ORDER BY timestamp DESC LIMIT 15
    """)
    recent = [dict(r) for r in cur.fetchall()]
    # محاسبه کمال برای هر نمونه
    for r in recent:
        r['completeness_pct'] = compute_completeness(r)

    # معاملات اخیر
    cur.execute("""
        SELECT trade_time, trade_price, trade_volume, trade_id, aggressor_side
        FROM trades ORDER BY trade_id_row DESC LIMIT 20
    """)
    trades = [dict(r) for r in cur.fetchall()]

    # محاسبه امتیازها
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
        'alerts': [],  # هشدارها از موتور alert_engine می‌آیند - در نسخه ساده فعلی خالی
        'sell_pressure': sp,
        'accumulation': acc,
        'signal': signal,
    })


@app.route('/api/snapshots')
def api_snapshots():
    """API برای دریافت همه نمونه‌ها."""
    conn = get_db_conn()
    if conn is None:
        return jsonify({'snapshots': []})

    cur = conn.cursor()
    cur.execute("SELECT * FROM snapshots ORDER BY timestamp ASC")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'snapshots': rows, 'count': len(rows)})


@app.route('/api/trades')
def api_trades():
    """API برای دریافت معاملات."""
    conn = get_db_conn()
    if conn is None:
        return jsonify({'trades': []})

    cur = conn.cursor()
    limit = request.args.get('limit', 100, type=int)
    cur.execute(f"SELECT * FROM trades ORDER BY trade_id_row DESC LIMIT {limit}")
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return jsonify({'trades': rows, 'count': len(rows)})


# ---------------------------------------------------------------------------
# اجرای اصلی
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description='داشبورد وب TSE Early Warning')
    parser.add_argument('--port', type=int, default=8050, help='پورت سرور (پیش‌فرض: 8050)')
    parser.add_argument('--host', type=str, default='127.0.0.1', help='میزبان (پیش‌فرض: localhost)')
    args = parser.parse_args()

    print("=" * 60)
    print("  TSE Early Warning - داشبورد وب زنده")
    print("=" * 60)
    print()
    print(f"📊 پایگاه داده: {DB_PATH}")
    print(f"🌐 آدرس:        http://{args.host}:{args.port}")
    print()
    print("  مرورگر را باز کنید و به آدرس بالا بروید")
    print("  صفحه هر ۵ ثانیه به‌صورت خودکار به‌روزرسانی می‌شود")
    print()
    print("  برای توقف: Ctrl+C را فشار دهید")
    print("-" * 60)

    try:
        app.run(host=args.host, port=args.port, debug=False)
    except KeyboardInterrupt:
        print("\n✓ سرور متوقف شد")


if __name__ == '__main__':
    main()
