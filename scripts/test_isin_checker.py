#!/usr/bin/env python3
"""تست: isin_checker + load_price_range_live با ISIN"""
import sys, tempfile, sqlite3
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
for f in ['web_dashboard_live.py', 'early_warning/isin_checker.py',
          'early_warning/data_collector.py', 'early_warning/__init__.py']:
    py_compile.compile(f, doraise=True)
    print(f'  ✓ {f}')

# ۲. تست isin_checker
print('\n[۲] تست isin_checker — پارس HTML')
from early_warning.isin_checker import (
    parse_range_rules_html, get_isin_prefix, get_range_percent_by_isin
)
html_path = ROOT / 'config' / 'tse_range_rules.html'
rules = parse_range_rules_html(html_path)
print(f'  قوانین استخراج‌شده: {len(rules)} مورد')
for prefix, (cat, pct) in rules.items():
    print(f'    {prefix} → {cat} ({pct}%)')
check('۷ پیشوند استخراج شد', len(rules) == 7, f'len={len(rules)}')
check('IRO1 = ۳٪', rules.get('IRO1', ('',0))[1] == 3)
check('IRO3 = ۶٪', rules.get('IRO3', ('',0))[1] == 6)
check('IRO7 = ۱۰٪', rules.get('IRO7', ('',0))[1] == 10)
check('IRO5 = ۵٪', rules.get('IRO5', ('',0))[1] == 5)
check('IRO6 = ۵٪', rules.get('IRO6', ('',0))[1] == 5)
check('IRO8 = ۵٪', rules.get('IRO8', ('',0))[1] == 5)
check('IRO4 = ۳٪', rules.get('IRO4', ('',0))[1] == 3)

print('\n[۳] تست get_isin_prefix')
check('IRO7TSEF0121 → IRO7', get_isin_prefix('IRO7TSEF0121') == 'IRO7')
check('IRO1ABCD0001 → IRO1', get_isin_prefix('IRO1ABCD0001') == 'IRO1')
check('empty → empty', get_isin_prefix('') == '')
check('حروف کوچک → بزرگ', get_isin_prefix('iro7tsef0121') == 'IRO7')

print('\n[۴] تست get_range_percent_by_isin')
r = get_range_percent_by_isin('IRO7TSEF0121', html_path=html_path)
check('IRO7TSEF0121 → ETF ۱۰٪', r is not None and r[1] == 10, str(r))
r = get_range_percent_by_isin('IRO1ABCD0001', html_path=html_path)
check('IRO1ABCD0001 → سهام ۳٪', r is not None and r[1] == 3, str(r))
r = get_range_percent_by_isin('IRO3XXXX0001', html_path=html_path)
check('IRO3XXXX0001 → حق تقدم ۶٪', r is not None and r[1] == 6, str(r))
r = get_range_percent_by_isin('IRO9XXXX0001', html_path=html_path)
check('IRO9 (ناموجود) → None', r is None, str(r))

# ۳. تست load_price_range_live (بدون API → fallback)
print('\n[۵] تست load_price_range_live با fallback (بدون API)')
from web_dashboard_live import load_price_range_live
from early_warning.storage import MarketDataStorage
from early_warning.price_range import to_jalali
from datetime import date

with tempfile.TemporaryDirectory() as tmp:
    db = Path(tmp) / 'test.sqlite'
    cfg = {'test_symbol': {'name': 'اهرم', 'ins_code': '', 'base_price': 93450}}
    st = MarketDataStorage(db)
    # ins_code خالی → API صدا نمی‌زند → ISIN خالی → fallback به symbol_categories.json
    load_price_range_live(cfg, 'اهرم', '', storage=st)
    st.close()

    # بررسی config
    ts = cfg['test_symbol']
    check('fixed_price_range تزریق شد', 'fixed_price_range' in ts)
    check('limit_percent ست شد', ts.get('limit_percent') is not None)
    check('base_price = 93450', ts.get('base_price') == 93450)
    fpr = ts.get('fixed_price_range', {})
    check('yesterday = 93450', fpr.get('yesterday_price') == 93450)
    check('min_allowed > 0', fpr.get('min_allowed_price', 0) > 0)
    check('max_allowed > 0', fpr.get('max_allowed_price', 0) > 0)
    check('isin فیلد موجود', 'isin' in fpr)

    # بررسی بانک
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM daily_params')
    n = cur.fetchone()[0]
    check('daily_params ایجاد شد', n == 1, f'n={n}')
    if n > 0:
        cur.execute('SELECT * FROM daily_params WHERE symbol=?', ('اهرم',))
        r = dict(cur.fetchone())
        check('yesterday_price = 93450', r['yesterday_price'] == 93450)
        check('min_allowed > 0', r['min_allowed_price'] > 0)
        check('max_allowed > 0', r['max_allowed_price'] > 0)
        check('date_jalali = امروز', r['date_jalali'] == to_jalali(date.today()))
    conn.close()

# ۴. تست نماد ناموجود
print('\n[۶] تست نماد ناموجود (بدون ISIN و بدون symbol_categories)')
cfg2 = {'test_symbol': {'name': 'ZZZZ', 'ins_code': '', 'base_price': 1000}}
load_price_range_live(cfg2, 'ZZZZ', '', storage=None)
check('نماد ناموجود → بدون fixed_price_range', 'fixed_price_range' not in cfg2['test_symbol'])

print(f'\n{"="*60}')
print(f'  نتیجه: {passed} پاسخ، {failed} رد')
print('='*60)
sys.exit(0 if failed == 0 else 1)
