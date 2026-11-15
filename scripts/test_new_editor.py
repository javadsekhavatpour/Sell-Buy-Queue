#!/usr/bin/env python3
"""تست: ویرایشگر HTML جدید با input fieldها و دکمه ذخیره"""
import sys, tempfile, shutil, re
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
for f in ['web_dashboard_live.py', 'early_warning/isin_checker.py']:
    py_compile.compile(f, doraise=True)
    print(f'  ✓ {f}')

# ۲. تست پارس فرمت جدید (input fieldها)
print('\n[۲] تست پارس فایل HTML جدید (input fieldها)')
from early_warning.isin_checker import parse_range_rules_html, get_range_percent_by_isin
html_path = ROOT / 'config' / 'tse_range_rules.html'
rules = parse_range_rules_html(html_path)
print(f'  قوانین استخراج‌شده: {len(rules)} مورد')
check('۷ پیشوند استخراج شد', len(rules) == 7, f'len={len(rules)}')
check('IRO1 = ۳٪', rules.get('IRO1', ('',0))[1] == 3)
check('IRO3 = ۶٪', rules.get('IRO3', ('',0))[1] == 6)
check('IRO7 = ۱۰٪', rules.get('IRO7', ('',0))[1] == 10)
check('IRO5 = ۵٪', rules.get('IRO5', ('',0))[1] == 5)
check('IRO6 = ۵٪', rules.get('IRO6', ('',0))[1] == 5)
check('IRO8 = ۵٪', rules.get('IRO8', ('',0))[1] == 5)
check('IRO4 = ۳٪', rules.get('IRO4', ('',0))[1] == 3)
# بررسی نام دسته‌ها
check('IRO7 دسته = صندوق ETF', 'صندوق' in rules.get('IRO7', ('',0))[0])
check('IRO3 دسته = حق تقدم', 'حق تقدم' in rules.get('IRO3', ('',0))[0])

# ۳. تست route /range-rules (سرو فایل مستقیم)
print('\n[۳] تست route /range-rules — سرو فایل')
import web_dashboard_live as wdl
wdl.app.config['TESTING'] = True
client = wdl.app.test_client()

resp = client.get('/range-rules')
check('GET /range-rules → 200', resp.status_code == 200, f'status={resp.status_code}')
content = resp.get_data(as_text=True)
check('صفحه شامل input field', '<input' in content)
check('صفحه شامل دکمه ذخیره', 'ذخیره' in content)
check('صفحه شامل name="pct_IRO7"', 'name="pct_IRO7"' in content)
check('صفحه شامل data-prefix="IRO7"', 'data-prefix="IRO7"' in content)
check('صفحه شامل فرم POST', 'method="post"' in content)
check('صفحه شامل AJAX fetch', 'fetch' in content)

# ۴. تست ذخیره (POST /range-rules/save)
print('\n[۴] تست POST /range-rules/save — تغییر IRO7 از ۱۰ به ۱۲')
with tempfile.TemporaryDirectory() as tmp:
    orig_html = ROOT / 'config' / 'tse_range_rules.html'
    tmp_config = Path(tmp) / 'config'
    tmp_config.mkdir()
    tmp_html = tmp_config / 'tse_range_rules.html'
    shutil.copy(orig_html, tmp_html)

    rules_before = parse_range_rules_html(orig_html)
    form_data = {}
    for prefix, (cat, pct) in rules_before.items():
        form_data[f'cat_{prefix}'] = cat
        form_data[f'pct_{prefix}'] = '12' if prefix == 'IRO7' else str(int(pct))

    orig_root = wdl.ROOT
    wdl.ROOT = Path(tmp)
    try:
        resp2 = client.post('/range-rules/save', data=form_data)
        check('POST → 200', resp2.status_code == 200, f'status={resp2.status_code}')
        rj = resp2.get_json()
        check('JSON ok=True', rj and rj.get('ok') == True, str(rj))

        # بررسی فایل ذخیره‌شده
        rules_after = parse_range_rules_html(tmp_html)
        check('IRO7 = ۱۲ (ذخیره شد)', rules_after.get('IRO7', ('',0))[1] == 12, str(rules_after.get('IRO7')))
        check('IRO1 تغییر نکرد (۳)', rules_after.get('IRO1', ('',0))[1] == 3)
        check('۷ قانون بعد از ذخیره', len(rules_after) == 7, f'len={len(rules_after)}')

        # بررسی فایل هنوز input field دارد (قابل ویرایش است)
        saved = tmp_html.read_text(encoding='utf-8')
        check('فایل ذخیره‌شده شامل input', '<input' in saved)
        check('فایل ذخیره‌شده شامل دکمه ذخیره', 'ذخیره' in saved)
        check('فایل ذخیره‌شده شامل فرم', 'method="post"' in saved)
        check('فایل ذخیره‌شده شامل AJAX', 'fetch' in saved)
    finally:
        wdl.ROOT = orig_root

# ۵. تست get_range_percent_by_isin با فایل جدید
print('\n[۵] تست get_range_percent_by_isin با فایل جدید')
r = get_range_percent_by_isin('IRO7TSEF0121', html_path=html_path)
check('IRO7TSEF0121 → ETF ۱۰٪', r is not None and r[1] == 10, str(r))
r = get_range_percent_by_isin('IRO1ABCD0001', html_path=html_path)
check('IRO1ABCD0001 → سهام ۳٪', r is not None and r[1] == 3, str(r))
r = get_range_percent_by_isin('IRO3XXXX0001', html_path=html_path)
check('IRO3XXXX0001 → حق تقدم ۶٪', r is not None and r[1] == 6, str(r))

# ۶. تست فرمت قدیم (backward compatibility)
print('\n[۶] تست backward compatibility با فرمت data-pct')
old_format_html = """
<table><tbody>
<tr><td data-prefix="IRO9">IRO9</td><td class="cat">تست</td><td data-pct="7">± 7 ٪</td></tr>
</tbody></table>
"""
with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False, encoding='utf-8') as f:
    f.write(old_format_html)
    tmp_old = Path(f.name)
old_rules = parse_range_rules_html(tmp_old)
check('فرمت قدیم: IRO9 = ۷٪', old_rules.get('IRO9', ('',0))[1] == 7, str(old_rules))
tmp_old.unlink()

print(f'\n{"="*60}')
print(f'  نتیجه: {passed} پاسخ، {failed} رد')
print('='*60)
sys.exit(0 if failed == 0 else 1)
