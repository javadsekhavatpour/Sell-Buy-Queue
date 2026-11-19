"""⚠ Shim — محتوای این فایل به web_dashboard_adaptive.py منتقل شده است.

این فایل فقط برای سازگاری با اسکریپت‌های قدیمی باقی مانده است.
کد واقعی همگی در web_dashboard_adaptive.py قرار دارد (ادغام ۱۴۰۵/۰۸/۲۹).

اجرای داشبورد: python web_dashboard_adaptive.py --port 8052
"""
import web_dashboard_adaptive as _m

# بازصدور همه‌ی نام‌ها (شامل نام‌های زیرخط‌دار مثل _build_range_rules_html)
# تا هم `from web_dashboard_live import X` و هم `import web_dashboard_live as wdl` کار کنند
for _k in dir(_m):
    if not _k.startswith("__"):
        globals()[_k] = getattr(_m, _k)
