#!/bin/bash
# ============================================================
# راهنمای آپلود پروژه به GitHub
# Repository: https://github.com/javadsekhavatpour/Sell-Buy-Queue.git
# ============================================================
#
# این فایل فقط راهنماست - نیازی به اجرای آن نیست.
# دستورات زیر را به‌ترتیب در ترمینال Windows (PowerShell یا CMD) اجرا کنید.
#
# پیش‌نیازها:
#   1. نصب Git از https://git-scm.com/download/win
#   2. حساب GitHub با دسترسی push به ریپازیتوری
#   3. در صورت نیازبا: PAT (Personal Access Token) از GitHub
#      (تنظیمات → Developer settings → Personal access tokens → Generate new token)
# ============================================================

# مرحله ۱: رفتن به پوشه پروژه
cd C:\TSE_Screener

# مرحله ۲: initialize کردن مخزن محلی git
git init

# مرحله ۳: اضافه کردن remote (آدرس ریپازیتوری GitHub)
git remote add origin https://github.com/javadsekhavatpour/Sell-Buy-Queue.git
# (اگر remote قبلاً اضافه شده باشد، خطا می‌دهد - می‌توانید با `git remote -v` چک کنید)

# مرحله ۴: تنظیم نام و ایمیل (در صورت عدم تنظیم قبلی)
git config user.name "javadsekhavatpour"
git config user.email "your-email@example.com"
# (ایمیل خود را جایگزین کنید - باید همان ایمیلی باشد که در GitHub ثبت کرده‌اید)

# مرحله ۵: بررسی وضعیت
git status

# مرحله ۶: اضافه کردن همه فایل‌ها به index
git add .

# مرحله ۷: بررسی دوباره وضعیت (مطمئن شوید فایل‌های غیرضروری در .gitignore هستند)
git status

# مرحله ۸: ساخت اولین commit
git commit -m "Initial commit: TSE Early Warning Engine v1.1

- Sell Pressure Detector (0-100 score, 6 indicators)
- Smart Accumulation Detector (0-100 score, 6 indicators)
- 3-level alert engine (Yellow/Red/Green) + Orange for mixed
- SQLite storage (snapshots/trades/metadata tables)
- Excel 7-sheet report (Dashboard/SellPressure/Accumulation/Snapshots/Trades/Metadata/History)
- Simulation mode (sell_pressure/accumulation/mixed scenarios)
- Live TSETMC collector with market phases (pre_open/continuous)
- Six data groups A-F: prices, order book, trade volume, real/legal, trades, market phase"

# مرحله ۹: دریافت تغییرات remote (در صورت وجود)
git pull origin main --allow-unrelated-histories
# یا اگر شاخه main ندارید:
# git pull origin master --allow-unrelated-histories

# مرحله ۱۰: push به GitHub (شاخه main)
git branch -M main
git push -u origin main

# ============================================================
# اگر با خطای احراز هویت مواجه شدید:
# ============================================================
# روش ۱: استفاده از Personal Access Token (PAT)
#   - در GitHub: Settings → Developer settings → Personal access tokens → Tokens (classic)
#   - Generate new token (classic) → تیک repo را بزنید → Copy token
#   - هنگام push، نام کاربری را GitHub username و رمز را PAT وارد کنید
#
# روش ۲: استفاده از GitHub CLI (توصیه شده)
#   winget install GitHub.cli
#   gh auth login
#   (سپس دوباره git push را اجرا کنید)
#
# روش ۳: استفاده از Git Credential Manager (پیش‌فرض روی Windows)
#   - اگر در حین نصب Git انتخاب کرده باشید، پنجره باز می‌شود
#
# ============================================================
# دستورات مفید پس از push اولیه:
# ============================================================
# git log --oneline         # مشاهده تاریخچه commits
# git remote -v             # مشاهده remoteها
# git status                # مشاهده وضعیت فعلی
# git pull origin main      # دریافت تغییرات از GitHub
# git push                  # ارسال تغییرات جدید (پس از commit)
