#!/usr/bin/env python3
"""تست: ویرایشگر HTML + اعتبارسنجی رنج قیمت"""
import sys, tempfile, shutil
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
for f in ['web_dashboard_live.py', 'run_live.py', 'early_warning/data_collector.py']:
    py_compile.compile(f, doraise=True)
    print(f'  ✓ {f}')

# ۲. تست validate_bid_ask_range
print('\n[۲] تست validate_bid_ask_range')
from early_warning.data_collector import MarketSnapshot, BestLimitRow

# snapshot در رنج — معتبر
snap_ok = MarketSnapshot(
    symbol='اهرم', yesterday_price=93450,
    min_allowed_price=87843, max_allowed_price=99057,
    buy_rows=[BestLimitRow(price=88000), BestLimitRow(price=88500)],
    sell_rows=[BestLimitRow(price=99000), BestLimitRow(price=98900)],
)
ok, oor = snap_ok.validate_bid_ask_range()
check('قیمت‌های در رنج → معتبر', ok, str(oor))
check('هیچ قیمت خارج از رنج نیست', len(oor) == 0)

# snapshot خارج از رنج — ask بالاتر از سقف
snap_bad_ask = MarketSnapshot(
    symbol='اهرم', yesterday_price=93450,
    min_allowed_price=87843, max_allowed_price=99057,
    buy_rows=[BestLimitRow(price=88000)],
    sell_rows=[BestLimitRow(price=99000), BestLimitRow(price=105000)],  # 105000 > 99057
)
ok2, oor2 = snap_bad_ask.validate_bid_ask_range()
check('ask خارج از سقف → نامعتبر', not ok2, str(oor2))
check('یک قیمت خارج از رنج', len(oor2) == 1, f'len={len(oor2)}')
if oor2:
    check('سطح خارج از رنج = ask_2', oor2[0]['side'] == 'ask' and oor2[0]['level'] == 2)

# snapshot خارج از رنج — bid پایین‌تر از کف
snap_bad_bid = MarketSnapshot(
    symbol='اهرم', yesterday_price=93450,
    min_allowed_price=87843, max_allowed_price=99057,
    buy_rows=[BestLimitRow(price=85000)],  # 85000 < 87843
    sell_rows=[BestLimitRow(price=99000)],
)
ok3, oor3 = snap_bad_bid.validate_bid_ask_range()
check('bid خارج از کف → نامعتبر', not ok3, str(oor3))
if oor3:
    check('سطح خارج از رنج = bid_1', oor3[0]['side'] == 'bid' and oor3[0]['level'] == 1)

# snapshot با قیمت صفر (ردیف خالی) → نباید خطا دهد
snap_zero = MarketSnapshot(
    symbol='اهرم', yesterday_price=93450,
    min_allowed_price=87843, max_allowed_price=99057,
    buy_rows=[BestLimitRow(price=88000), BestLimitRow(price=0)],
    sell_rows=[BestLimitRow(price=99000), BestLimitRow(price=0)],
)
ok4, oor4 = snap_zero.validate_bid_ask_range()
check('قیمت صفر (ردیف خالی) → معتبر', ok4, str(oor4))

# snapshot بدون کف/سقف → معتبر (معنای اعتبارسنجی ندارد)
snap_no_range = MarketSnapshot(
    symbol='اهرم', yesterday_price=93450,
    min_allowed_price=0, max_allowed_price=0,
    buy_rows=[BestLimitRow(price=88000)],
    sell_rows=[BestLimitRow(price=99000)],
)
ok5, oor5 = snap_no_range.validate_bid_ask_range()
check('بدون کف/سقف → معتبر', ok5, str(oor5))

# ۳. تست ویرایشگر HTML (Flask routes)
print('\n[۳] تست ویرایشگر HTML (Flask)')
from web_dashboard_live import app, _build_range_rules_html
from early_warning.isin_checker import parse_range_rules_html

# تست client Flask
app.config['TESTING'] = True
client = app.test_client()

# GET /range-rules — باید صفحه ویرایشگر برگرداند
resp = client.get('/range-rules')
check('GET /range-rules → 200', resp.status_code == 200, f'status={resp.status_code}')
html_content = resp.get_data(as_text=True)
check('صفحه شامل جدول', '<table' in html_content)
check('صفحه شامل فیلد pct_IRO7', 'name="pct_IRO7"' in html_content)
check('صفحه شامل دکمه ذخیره', 'ذخیره' in html_content)

# POST /range-rules/save — تغییر درصد IRO7 از 10 به 12
with tempfile.TemporaryDirectory() as tmp:
    # کپی فایل HTML واقعی به tmp/config/
    orig_html = ROOT / 'config' / 'tse_range_rules.html'
    tmp_config = Path(tmp) / 'config'
    tmp_config.mkdir()
    tmp_html = tmp_config / 'tse_range_rules.html'
    shutil.copy(orig_html, tmp_html)

    # ساخت داده فرم
    rules_before = parse_range_rules_html(orig_html)
    form_data = {}
    for prefix, (cat, pct) in rules_before.items():
        if prefix == 'IRO7':
            form_data[f'pct_{prefix}'] = '12'
        else:
            form_data[f'pct_{prefix}'] = str(pct)
        form_data[f'cat_{prefix}'] = cat

    # monkeypatch: تغییر مسیر ROOT به tmp
    import web_dashboard_live as wdl
    orig_root = wdl.ROOT
    wdl.ROOT = Path(tmp)
    try:
        resp2 = client.post('/range-rules/save', data=form_data)
        check('POST /range-rules/save → 200', resp2.status_code == 200, f'status={resp2.status_code}')
        resp_json = resp2.get_json()
        check('پاسخ JSON ok=True', resp_json and resp_json.get('ok') == True, str(resp_json))

        # بررسی فایل ذخیره‌شده
        rules_after = parse_range_rules_html(tmp_html)
        check('IRO7 = ۱۲ (ذخیره شد)', rules_after.get('IRO7', ('',0))[1] == 12, str(rules_after.get('IRO7')))
        check('سایر قوانین تغییر نکرد', rules_after.get('IRO1', ('',0))[1] == rules_before['IRO1'][1])
        check('فایل HTML معتبر بعد از ذخیره', len(rules_after) == 7, f'len={len(rules_after)}')
    finally:
        wdl.ROOT = orig_root

# ۴. تست _build_range_rules_html
print('\n[۴] تست بازسازی HTML')
test_rules = {'IRO7': ('صندوق', 10.0), 'IRO1': ('سهام', 3.0)}
new_html = _build_range_rules_html(test_rules)

# parse from string
import re
def parse_from_str(html):
    rules = {}
    row_pattern = re.compile(
        r"<tr[^>]*>.*?data-prefix\s*=\s*\"([^\"]+)\".*?<td[^>]*class=\"cat\"[^>]*>(.*?)</td>.*?data-pct\s*=\s*\"([^\"]+)\".*?</tr>",
        re.DOTALL | re.IGNORECASE,
    )
    for m in row_pattern.finditer(html):
        prefix = m.group(1).strip().upper()
        cat = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        try: pct = float(m.group(3))
        except: continue
        if prefix and pct > 0: rules[prefix] = (cat, pct)
    return rules

parsed = parse_from_str(new_html)
check('HTML بازسازی‌شده قابل پارس', len(parsed) == 2)
check('IRO7 = ۱۰ در HTML جدید', parsed.get('IRO7', ('',0))[1] == 10)
check('IRO1 = ۳ در HTML جدید', parsed.get('IRO1', ('',0))[1] == 3)

print(f'\n{"="*60}')
print(f'  نتیجه: {passed} پاسخ، {failed} رد')
print('='*60)
sys.exit(0 if failed == 0 else 1)
