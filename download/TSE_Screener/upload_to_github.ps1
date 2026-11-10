# ============================================================
# اسکریپت آپلود پروژه TSE_Screener به GitHub
# Repository: Sell-Buy-Queue (Private)
# ============================================================
# نحوه اجرا:
#   1. این فایل را در پوشه C:\TSE_Screener ذخیره کنید
#   2. PowerShell را باز کنید (در منوی استارت تایپ کنید PowerShell)
#   3. دستور زیر را اجرا کنید:
#        cd C:\TSE_Screener
#        .\upload_to_github.ps1
#   4. در صورت درخواست، نام کاربری و Personal Access Token GitHub را وارد کنید
# ============================================================

# توقف در اولین خطا
$ErrorActionPreference = "Stop"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  آپلود پروژه TSE_Screener به GitHub" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# بررسی اینکه آیا git نصب است
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Git نصب نیست!" -ForegroundColor Red
    Write-Host "لطفا از https://git-scm.com/download/win دانلود و نصب کنید." -ForegroundColor Yellow
    pause
    exit 1
}

Write-Host "✓ Git نصب است" -ForegroundColor Green

# آدرس ریپازیتوری
$repoUrl = "https://github.com/javadsekhavatpour/Sell-Buy-Queue.git"
Write-Host "📍 ریپازیتوری هدف: $repoUrl" -ForegroundColor Cyan

# اگر .git وجود ندارد، initialize کن
if (-not (Test-Path ".git")) {
    Write-Host "🔧 در حال initialize کردن مخزن محلی..." -ForegroundColor Yellow
    git init
    if ($LASTEXITCODE -ne 0) { Write-Host "❌ خطا در git init" -ForegroundColor Red; pause; exit 1 }
} else {
    Write-Host "✓ مخزن محلی از قبل initialize شده" -ForegroundColor Green
}

# تنظیم remote
Write-Host "🔧 تنظیم remote..." -ForegroundColor Yellow
git remote remove origin 2>$null
git remote add origin $repoUrl
if ($LASTEXITCODE -ne 0) { Write-Host "❌ خطا در افزودن remote" -ForegroundColor Red; pause; exit 1 }
Write-Host "✓ Remote اضافه شد" -ForegroundColor Green

# پرسیدن نام و ایمیل کاربر
Write-Host ""
Write-Host "📝 تنظیم نام و ایمیل Git" -ForegroundColor Cyan
$gitName = git config user.name
if (-not $gitName) {
    $gitName = Read-Host "نام GitHub شما (مثلا javadsekhavatpour)"
    git config user.name $gitName
}
Write-Host "  نام: $gitName" -ForegroundColor Green

$gitEmail = git config user.email
if (-not $gitEmail) {
    $gitEmail = Read-Host "ایمیل GitHub شما"
    git config user.email $gitEmail
}
Write-Host "  ایمیل: $gitEmail" -ForegroundColor Green

# نمایش فایل‌هایی که اضافه می‌شوند
Write-Host ""
Write-Host "🔍 بررسی فایل‌ها..." -ForegroundColor Cyan
git add .
$status = git status --porcelain
$addedCount = ($status | Where-Object { $_ -match "^A" }).Count
$ignoredCount = (Get-Content .gitignore | Where-Object { $_ -and -not $_.StartsWith("#") }).Count
Write-Host "  فایل‌های اضافه شده: $addedCount" -ForegroundColor Green
Write-Host "  الگوهای نادیده گرفته شده: $ignoredCount" -ForegroundColor Green

# commit
Write-Host ""
Write-Host "📦 ساخت commit..." -ForegroundColor Cyan
$commitMsg = @"
Initial commit: TSE Early Warning Engine v1.1

Features:
- Sell Pressure Detector (0-100 score, 6 indicators)
- Smart Accumulation Detector (0-100 score, 6 indicators)
- 3-level alert engine (Yellow/Red/Green) + Orange for mixed
- SQLite storage (snapshots/trades/metadata tables)
- Excel 7-sheet report (Dashboard/SellPressure/Accumulation/Snapshots/Trades/Metadata/History)
- Simulation mode (sell_pressure/accumulation/mixed scenarios)
- Live TSETMC collector with market phases (pre_open/continuous)
- Six data groups A-F (prices, order book, trades, real/legal, market phase)

Files: 22 source files + config + README + .gitignore + LICENSE
"@
git commit -m $commitMsg
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ خطا در commit" -ForegroundColor Red
    pause
    exit 1
}
Write-Host "✓ Commit ساخته شد" -ForegroundColor Green

# تغییر نام شاخه به main
Write-Host ""
Write-Host "🔧 تغییر نام شاخه به main..." -ForegroundColor Cyan
git branch -M main

# push
Write-Host ""
Write-Host "🚀 در حال push به GitHub..." -ForegroundColor Cyan
Write-Host "اگر نام کاربری و رمز خواست:" -ForegroundColor Yellow
Write-Host "  Username: نام کاربری GitHub" -ForegroundColor Yellow
Write-Host "  Password: Personal Access Token (نه رمز عبور GitHub)" -ForegroundColor Yellow
Write-Host ""
Write-Host " اگر توکن ندارید:" -ForegroundColor Yellow
Write-Host "  GitHub → Settings → Developer settings → Personal access tokens" -ForegroundColor Yellow
Write-Host "  → Tokens (classic) → Generate new token → تیک repo → Generate" -ForegroundColor Yellow
Write-Host ""

git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "❌ خطا در push!" -ForegroundColor Red
    Write-Host ""
    Write-Host "موارد رایج:" -ForegroundColor Yellow
    Write-Host "  1. نام کاربری/توکن اشتباه" -ForegroundColor Yellow
    Write-Host "  2. ریپازیتوری وجود ندارد یا private است و دسترسی ندارید" -ForegroundColor Yellow
    Write-Host "  3. ریپازیتوری خالی نیست (مثلا README توسط GitHub ساخته شده)" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "در صورت خطای 'non-fast-forward'، این دستور را اجرا کنید:" -ForegroundColor Cyan
    Write-Host "  git pull origin main --allow-unrelated-histories" -ForegroundColor White
    Write-Host "  git push -u origin main" -ForegroundColor White
    pause
    exit 1
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  ✅ آپلود با موفقیت انجام شد!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "🔗 آدرس ریپازیتوری:" -ForegroundColor Cyan
Write-Host "  $repoUrl" -ForegroundColor White
Write-Host ""
Write-Host "📊 خلاصه:" -ForegroundColor Cyan
Write-Host "  - $addedCount فایل اضافه شد" -ForegroundColor White
Write-Host "  - Commit: Initial commit" -ForegroundColor White
Write-Host "  - شاخه: main" -ForegroundColor White
Write-Host ""
Write-Host "اکنون می‌توانید صفحه GitHub را refresh کنید و فایل‌ها را ببینید." -ForegroundColor Green
pause
