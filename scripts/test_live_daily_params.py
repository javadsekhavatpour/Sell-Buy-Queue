#!/usr/bin/env python3
"""تست: web_dashboard_live.py — نوشتن daily_params در بانک"""
import sys, tempfile, json
from pathlib import Path
sys.path.insert(0, '.')

ROOT = Path('.')

passed = failed = 0
def check(name, cond, detail=''):
    global passed, failed
    if cond: passed += 1; print(f'  ✓ {name}')
    else: failed += 1; print(f'  ✗ {name}  {detail}')

# ۱. بررسی نحوی
print('[۱] بررسی خطای نحوی')
import py_compile
for f in ['web_dashboard_live.py', 'early_warning/storage.py', 'early_warning/data_collector.py']:
    py_compile.compile(f, doraise=True)
    print(f'  ✓ {f}')

# ۲. بررسی import
print('\n[۲] بررسی import')
from web_dashboard_live import load_price_range_live, load_cfg
from early_warning.storage import MarketDataStorage
from early_warning.price_range import to_jalali
from datetime import date
print('  ✓ import موفق')

# ۳. تست load_price_range_live با storage (بدون API — base_price fallback)
print('\n[۳] تست load_price_range_live با storage')
with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / 'test.sqlite'
    cfg = {
        'test_symbol': {
            'name': 'اهرم',
            'ins_code': '17914401175772326',
            'base_price': 93450,
        }
    }
    st = MarketDataStorage(db)
    # فراخوانی با ins_code خالی → از base_price استفاده می‌کند (بدون API)
    load_price_range_live(cfg, 'اهرم', '', storage=st)
    st.close()

    # بررسی بانک
    import sqlite3
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM daily_params')
    n = cur.fetchone()[0]
    check('daily_params ایجاد شد', n == 1, f'n={n}')
    if n > 0:
        cur.execute('SELECT * FROM daily_params WHERE symbol=?', ('اهرم',))
        r = dict(cur.fetchone())
        check('symbol = اهرم', r['symbol'] == 'اهرم')
        check('category = صندوق اهرمی', r['category'] == 'صندوق اهرمی')
        check('range_percent = 6.0', r['range_percent'] == 6.0)
        check('yesterday_price = 93450', r['yesterday_price'] == 93450)
        check('min_allowed = 87843', r['min_allowed_price'] == 87843)
        check('max_allowed = 99057', r['max_allowed_price'] == 99057)
        check('date_jalali = امروز', r['date_jalali'] == to_jalali(date.today()))
    conn.close()

    # بررسی config تزریق شده
    ts = cfg['test_symbol']
    check('fixed_price_range تزریق شد', 'fixed_price_range' in ts)
    check('limit_percent = 6.0', ts.get('limit_percent') == 6.0)
    check('base_price به‌روز شد', ts.get('base_price') == 93450)

# ۴. تست بدون storage (باید بدون خطا کار کند)
print('\n[۴] تست بدون storage (حالت قبلی)')
cfg2 = {'test_symbol': {'name': 'اهرم', 'ins_code': '', 'base_price': 93450}}
load_price_range_live(cfg2, 'اهرم', '', storage=None)
check('بدون storage بدون خطا', 'fixed_price_range' in cfg2['test_symbol'])

# ۵. تست نماد ناموجود در symbol_categories
print('\n[۵] تست نماد ناموجود در symbol_categories')
cfg3 = {'test_symbol': {'name': 'XXXX', 'ins_code': '', 'base_price': 1000}}
load_price_range_live(cfg3, 'XXXX', '', storage=None)
check('نماد ناموجود → بدون fixed_price_range', 'fixed_price_range' not in cfg3['test_symbol'])

print(f'\n{"="*60}')
print(f'  نتیجه: {passed} پاسخ، {failed} رد')
print('='*60)
sys.exit(0 if failed == 0 else 1)
