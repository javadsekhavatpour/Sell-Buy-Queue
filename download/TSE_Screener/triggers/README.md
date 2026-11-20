# triggers/ — درخواست ریپورت در طول جلسه

برای ساخت **ریپورت Excel فوری** از یک نماد در حالی که `run_multi.py` در حال
جمع‌آوری است (بدون صبر تا پایان جلسه)، یک فایل trigger بسازید:

```bash
python request_report.py اهرم
# یا مستقیم:
touch triggers/report_اهرم
```

workerِ `run_live.py` در ابتدای تکرار بعدیِ حلقه (هر `interval` ثانیه) این فایل را
می‌بیند، یک ریپورت Excel از بانکِ فعلی می‌سازد (`reports/..._snapshot.xlsx`) و فایل
trigger را حذف می‌کند.

نام فایل باید دقیقاً `report_{نماد}` باشد (نماد فارسی، مطابق `config/symbols.json`).

ریپورت‌های خودکار:
- هر مرز ۵دقیقه‌ای → `reports/..._5min.xlsx`
- هر مرز ۱۵دقیقه‌ای → `reports/..._15min.xlsx`
- پایان جلسه (پیش‌فرض) → `reports/early_warning_report_live_{نماد}.xlsx`
