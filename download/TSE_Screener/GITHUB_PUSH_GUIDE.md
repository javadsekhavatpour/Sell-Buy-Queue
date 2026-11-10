# راهنمای Push تغییرات به GitHub

## ریپازیتوری
- **آدرس:** https://github.com/javadsekhavatpour/Sell-Buy-Queue
- **شاخه اصلی:** `main`
- **نوع:** Private

## نحوه Push تغییرات

### روش ۱: توسط دستیار AI (توصیه شده)

کافی است به من بگویید: «این تغییرات را در گیت‌هاب ذخیره کن» و توکن GitHub خود را ارائه دهید.
من این کارها را انجام می‌دهم:

1. بررسی تغییرات (git status)
2. اضافه کردن فایل‌ها (git add)
3. ساخت commit با پیام مناسب
4. push به GitHub با استفاده از توکن شما
5. **پاک کردن توکن از سیستم** (برای امنیت)

### روش ۲: دستی (روی Windows)

در PowerShell یا CMD:

```bash
cd C:\TSE_Screener

# بررسی فایل‌های تغییر کرده
git status

# اضافه کردن همه تغییرات
git add .

# ساخت commit با توضیح
git commit -m "توضیح تغییرات"

# push به GitHub
git push origin main
```

## قواعد commit

### فرمت پیام commit:

```
<نوع>: <توضیح کوتاه>

<توضیح مفصل (اختیاری)>
```

### انواع commit:

| نوع | کاربرد |
|-----|--------|
| `feat` | افزودن قابلیت جدید |
| `fix` | رفع خطا |
| `refactor` | بهبود کد بدون تغییر رفتار |
| `docs` | تغییر مستندات |
| `style` | تغییرات قالب‌بندی |
| `test` | افزودن یا اصلاح تست |
| `chore` | کارهای نگهداری |

### مثال:

```
feat: افزودن پشتیبانی از فاز حراج پایانی

- افزودن MarketPhase.AUCTION_CLOSE
- اصلاح شبیه‌ساز برای فاز جدید
- به‌روزرسانی validator
```

## نکات امنیتی

- 🔐 **هرگز توکن را در فایل کد یا .gitignore نشکنید**
- 🔐 **توکن‌های قدیمی را در GitHub باطل کنید** (Settings → Developer settings → Personal access tokens)
- 🔐 پس از هر push، توکن از سیستم پاک می‌شود
- 🔐 اگر اشتباهاً توکن را در فایلی قرار دادید، بلافاصله آن را از GitHub باطل کنید

## عیب‌یابی

### خطای "Permission denied"
- توکن اعتبار ندارد یا باطل شده → توکن جدید بسازید
- دسترسی push به ریپازیتوری ندارید → بررسی تنظیمات دسترسی

### خطای "non-fast-forward"
```bash
git pull origin main --allow-unrelated-histories
git push origin main
```

### خطای "Authentication failed"
- نام کاربری درست: `javadsekhavatpour`
- رمز: توکن PAT (نه رمز GitHub)

## ساخت Personal Access Token (PAT)

1. به https://github.com/settings/tokens بروید
2. **Generate new token (classic)** را کلیک کنید
3. **Note** = "TSE Screener" (نام دلخواه)
4. **Expiration** = No expiration (یا 90 days)
5. **Scopes** = تیک **repo** را بزنید
6. **Generate token** → کپی کنید (فقط یک‌بار نمایش داده می‌شود)
