# نگاشت فیلدهای TSETMC به فیلدهای پروژه

> این سند مرجع کامل نگاشت فیلدهای دریافتی از سایت TSETMC به فیلدهای داخلی پروژه است.
> محل پیاده‌سازی: `early_warning/data_collector.py` (نسخه ۳ — APIهای جدید `cdn.tsetmc.com`)
>
> ⚠ **اصلاح مهم (۲۰۲۶-۱۱-۱۱):** نام چند کلید قبلی اشتباه بود و باعث می‌شد بالاترین/پایین‌ترین قیمت روز، حجم کل و ارزش کل معاملات همیشه صفر ذخیره شوند. نام‌های واقعی با بررسی پاسخ واقعی API (و کتابخانه مرجع `tsetmc`) تأیید شد: `priceMax` / `priceMin` / `priceFirst` / `priceYesterday` / `qTotTran5J` / `qTotCap`. نام‌های قدیمی (`pPriceMax` و ...) در این API وجود ندارند.

**مثال خوانش جدول:** `pClosing = close_price` یعنی فیلد `pClosing` از پاسخ API در فیلد `close_price` نمونه داده ذخیره می‌شود.

---

## ۱) Endpoint اول: `ClosingPrice/GetClosingPriceInfo/{InsCode}`
### قیمت‌ها — گروه A و حجم/ارزش — گروه C

| فیلد TSETMC (نام واقعی) | فیلد داخلی | گروه | توضیح |
|---|---|---|---|
| `pDrCotVal` | `last_price` | A | آخرین قیمت معامله |
| `pClosing` | `close_price` | A | قیمت پایانی (میانگین وزنی) |
| `priceFirst` | `open_price` | A | اولین قیمت روز |
| `priceYesterday` | `yesterday_price` | A | قیمت دیروز (مبنای درصد تغییر) |
| `priceMax` | `daily_high` | A | بالاترین قیمت روز |
| `priceMin` | `daily_low` | A | پایین‌ترین قیمت روز |
| — (در این API نیست) | `min_allowed_price` | A | از قیمت دیروز × (۱ − `limit_percent` پیکربندی، پیش‌فرض ۱۰٪) |
| — (در این API نیست) | `max_allowed_price` | A | از قیمت دیروز × (۱ + `limit_percent`) |
| `qTotTran5J` | `total_volume` | C | حجم کل معاملات روز (سهم) |
| `qTotCap` | `total_value` | C | ارزش کل معاملات روز (ریال) |
| `zTotTran` | `total_trade_count` | C | تعداد کل معاملات روز |
| — (در این API نیست) | `base_volume` | C | حجم مبنا: از پیکربندی (`test_symbol.base_volume`) یا ۱۰۰٬۰۰۰ |
| `instrumentState.cEtavalTitle` | `symbol_status` | F | وضعیت نماد (مثلا «مجاز») |

کنترل صحت با پاسخ واقعی: `qTotTran5J × pClosing ≈ qTotCap` (حجم کل × قیمت پایانی ≈ ارزش کل).

---

## ۲) Endpoint دوم: `BestLimits/{InsCode}`
### عمق بازار پنج‌ردیفی — گروه B

| فیلد TSETMC | فیلد داخلی | توضیح |
|---|---|---|
| `pMeDem` | `bid_price_1` تا `bid_price_5` | قیمت خرید (بهترین تا پایین‌تر) |
| `qTitMeDem` | `bid_volume_1` تا `bid_volume_5` | حجم سفارش خرید هر ردیف |
| `zOrdMeDem` | `bid_count_1` تا `bid_count_5` | تعداد سفارش خرید هر ردیف |
| `pMeOf` | `ask_price_1` تا `ask_price_5` | قیمت فروش (بهترین تا بالاتر) |
| `qTitMeOf` | `ask_volume_1` تا `ask_volume_5` | حجم سفارش فروش هر ردیف |
| `zOrdMeOf` | `ask_count_1` تا `ask_count_5` | تعداد سفارش فروش هر ردیف |

در حافظه به‌صورت لیست هم نگه‌داری می‌شوند: `buy_rows[i] = {price, volume, order_count}` و `sell_rows[i] = ...`
فیلدهای جمعی حاصل از این لیست: `best_buy_price`، `best_buy_volume`، `best_sell_price`، `best_sell_volume`، `buy_order_count`، `sell_order_count`

---

## ۳) Endpoint سوم: `ClientType/GetClientType/{InsCode}`
### اطلاعات حقیقی/حقوقی — گروه D

| فیلد TSETMC | فیلد داخلی | توضیح |
|---|---|---|
| `buy_CountI` | `real_buy_count` | تعداد خریداران حقیقی (I = Individual) |
| `buy_I_Volume` | `real_buy_volume` | حجم خرید حقیقی |
| `sell_CountI` | `real_sell_count` | تعداد فروشندگان حقیقی |
| `sell_I_Volume` | `real_sell_volume` | حجم فروش حقیقی |
| `buy_CountN` | `legal_buy_count` | تعداد خریداران حقوقی (N = Non-individual) |
| `buy_N_Volume` | `legal_buy_volume` | حجم خرید حقوقی |
| `sell_CountN` | `legal_sell_count` | تعداد فروشندگان حقوقی |
| `sell_N_Volume` | `legal_sell_volume` | حجم فروش حقوقی |

نکته: اگر پاسخ `GetClientType` خالی بود، از `ClientType/GetClientTypeAll` برای همان `ins_code` جستجو می‌شود.

---

## ۴) فیلدهای محاسباتی داخلی — از API نمی‌آیند

| فیلد داخلی | فرمول محاسبه |
|---|---|
| `interval_volume` | `total_volume` نمونه جدید − نمونه قبلی |
| `interval_value` | تفاضل `total_value` دو نمونه متوالی |
| `interval_trade_count` | تفاضل `total_trade_count` دو نمونه متوالی |
| `interval_real_buy_volume` | تفاضل `real_buy_volume` دو نمونه متوالی |
| `interval_real_sell_volume` | تفاضل `real_sell_volume` دو نمونه متوالی |
| `real_buy_value` (و `real_sell_value`، `legal_buy_value`، `legal_sell_value`) | حجم مربوطه × `close_price` |
| `per_capita_buy_real` | `real_buy_volume` ÷ `real_buy_count` |
| `per_capita_sell_real` | `real_sell_volume` ÷ `real_sell_count` |
| `buyer_power` | سرانه خرید حقیقی ÷ سرانه فروش حقیقی |
| `real_money_flow` | ارزش خرید حقیقی − ارزش فروش حقیقی |
| `real_money_flow_ratio` | `real_money_flow` ÷ `total_value` |
| `date_jalali` / `timestamp` / `tehran_time` | ساعت سیستم (تبدیل شمسی داخلی، بدون کتابخانه بیرونی) |
| `market_phase` | تشخیص از ساعت تهران: پیش‌گشایش (۸:۴۵-۹:۰۰)، پیوسته (۹:۰۰-۱۸:۰۰)، بسته |
| `symbol` / `ins_code` | از پیکربندی یا جستجوی `Instrument/GetInstrumentSearch/{query}` |

فیلدهای کیفیت داده (گروه F): `data_status` (ok / partial / error)، `data_complete`، `missing_fields`، `fetch_error`، `source_update_time`

---

## دو نکته مهم

### نکته ۱ — گروه E (معاملات لحظه‌ای)
API جدید TSETMC (`cdn.tsetmc.com`) فهرست معاملات تک‌تک را نمی‌دهد؛ داده‌های معاملات فقط به‌صورت تجمعی در `GetClosingPriceInfo` موجود است (تعداد، حجم و ارزش کل). بنابراین متد `fetch_trades` در حالت زنده فعلاً لیست خالی برمی‌گرداند و فیلدهای گروه E (`trade_time`، `trade_price`، `trade_volume`، `trade_id`، `aggressor_side`) فقط توسط شبیه‌ساز تولید می‌شوند. داشبورد هم این ستون اختیاری را در نبود داده به‌صورت خنثی و بدون حدس نمایش می‌دهد.

### نکته ۲ — جای ذخیره‌سازی داده‌ها
- در حالت **`run_live.py`**: تمام فیلدهای جدول‌های بالا با همان نام داخلی، در جدول `snapshots` فایل `data/early_warning_live.sqlite` ذخیره می‌شوند (مثلاً ستون `close_price`، ستون‌های `bid_price_1` تا `ask_count_5`). ساختار جدول در `early_warning/storage.py` تعریف شده است.
- در حالت **`web_dashboard_live.py`** (داشبورد رصد زنده): طبق تصمیم پروژه، **هیچ داده‌ای در پایگاه داده یا فایل ذخیره نمی‌شود**؛ همه‌چیز فقط در حافظه (RAM) نگه‌داری می‌شود و با بستن برنامه پاک می‌شود. این داشبورد مستقیماً از منبع داده می‌گیرد و به SQLite وابسته نیست.
