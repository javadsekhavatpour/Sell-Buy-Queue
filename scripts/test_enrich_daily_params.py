#!/usr/bin/env python3
"""تست: پر کردن فیلدهای خالی snapshot از daily_params با تاریخ روز"""
import sys, tempfile, sqlite3
from pathlib import Path
sys.path.insert(0, '.')

from early_warning.storage import MarketDataStorage
from early_warning.data_collector import MarketSnapshot
from early_warning.price_range import to_jalali
from datetime import date

passed = failed = 0
def check(name, cond, detail=''):
    global passed, failed
    if cond: passed += 1; print(f'  ✓ {name}')
    else: failed += 1; print(f'  ✗ {name}  {detail}')

today_j = to_jalali(date.today())
print(f'تاریخ امروز: {today_j}')
print('='*60)

with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp)/'test.sqlite'
    st = MarketDataStorage(db)

    # ۱. درج daily_params برای امروز
    st.upsert_daily_params({
        'date_jalali': today_j, 'symbol': 'اهرم', 'ins_code': '123',
        'category': 'صندوق اهرمی', 'range_percent': 6.0,
        'yesterday_price': 93450.0, 'first_price': None,
        'min_allowed_price': 87843.0, 'max_allowed_price': 99057.0,
        'computed_at': '2026-11-14',
    })

    # ۲. درج snapshot با فیلدهای خالی (شبیه snapshot قدیمی)
    snap_empty = MarketSnapshot(
        timestamp='2026-11-14T09:00', tehran_time='09:00:00',
        date_jalali='',  # خالی!
        symbol='اهرم', ins_code='123', market_phase='continuous',
        last_price=93500, close_price=93500, open_price=93450,
        yesterday_price=0,  # خالی!
        min_allowed_price=0,  # خالی!
        max_allowed_price=0,  # خالی!
    )
    st.insert_snapshot(snap_empty)

    # ۳. درج snapshot با مقادیر پر (شبیه snapshot جدید)
    snap_full = MarketSnapshot(
        timestamp='2026-11-14T09:01', tehran_time='09:01:00',
        date_jalali=today_j,
        symbol='اهرم', ins_code='123', market_phase='continuous',
        last_price=93600, close_price=93600, open_price=93450,
        yesterday_price=93450, min_allowed_price=87843, max_allowed_price=99057,
    )
    st.insert_snapshot(snap_full)
    st.close()

    # ۴. شبیه‌سازی منطق _enrich_with_daily_params
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    print('\n[۱] snapshot خالی قبل از enrichment:')
    cur.execute('SELECT date_jalali, yesterday_price, min_allowed_price, max_allowed_price FROM snapshots WHERE timestamp=?', ('2026-11-14T09:00',))
    r = dict(cur.fetchone())
    print(f'  date_jalali="{r["date_jalali"]}" yp={r["yesterday_price"]} min={r["min_allowed_price"]} max={r["max_allowed_price"]}')
    check('date_jalali خالی', r['date_jalali'] == '')
    check('yesterday_price = 0', r['yesterday_price'] == 0 or r['yesterday_price'] is None)

    print('\n[۲] enrichment از daily_params:')
    # منطق enrichment (مشابه web_dashboard_db.py)
    def enrich(row):
        sym = row.get('symbol') or 'اهرم'
        if not (row.get('date_jalali') or '').strip():
            row['date_jalali'] = today_j
        date_j = (row.get('date_jalali') or '').strip()
        # جستجو: اول با تاریخ snapshot، سپس امروز، سپس آخرین
        dp = None
        if date_j:
            cur.execute('SELECT * FROM daily_params WHERE symbol=? AND date_jalali=? ORDER BY param_id DESC LIMIT 1', (sym, date_j))
            dp = cur.fetchone()
        if not dp:
            cur.execute('SELECT * FROM daily_params WHERE symbol=? ORDER BY param_id DESC LIMIT 1', (sym,))
            dp = cur.fetchone()
        if dp:
            dp = dict(dp)
            for k in ('yesterday_price', 'min_allowed_price', 'max_allowed_price'):
                if not row.get(k):
                    row[k] = dp.get(k)
            if not (row.get('date_jalali') or '').strip():
                row['date_jalali'] = dp.get('date_jalali') or today_j
        return row

    enriched = enrich(dict(r))
    check('date_jalali پر شد', enriched['date_jalali'] == today_j)
    check('yesterday_price پر شد = ۹۳۴۵۰', enriched['yesterday_price'] == 93450)
    check('min_allowed پر شد = ۸۷۸۴۳', enriched['min_allowed_price'] == 87843)
    check('max_allowed پر شد = ۹۹۰۵۷', enriched['max_allowed_price'] == 99057)

    print('\n[۳] snapshot پر (باید تغییر نکند):')
    cur.execute('SELECT date_jalali, yesterday_price, min_allowed_price, max_allowed_price FROM snapshots WHERE timestamp=?', ('2026-11-14T09:01',))
    r2 = dict(cur.fetchone())
    enriched2 = enrich(r2)
    check('date_jalali تغییر نکرد', enriched2['date_jalali'] == today_j)
    check('yesterday_price تغییر نکرد = ۹۳۴۵۰', enriched2['yesterday_price'] == 93450)
    check('min_allowed تغییر نکرد = ۸۷۸۴۳', enriched2['min_allowed_price'] == 87843)

    print('\n[۴] date_jalali در collect():')
    import ast
    src = open('early_warning/data_collector.py').read()
    count = src.count('date_jalali=to_jalali(date.today())')
    check(f'date_jalali در collect (۲ بار)', count == 2)

    print('\n[۵] مقاوم‌سازی load_price_range_live:')
    src2 = open('web_dashboard_live.py').read()
    check('try/except در load_price_range_live', 'except Exception as e:' in src2 and 'yesterday_price از API دریافت نشد' in src2)

    conn.close()

print(f'\n{"="*60}')
print(f'  نتیجه: {passed} پاسخ، {failed} رد')
print('='*60)
sys.exit(0 if failed == 0 else 1)
