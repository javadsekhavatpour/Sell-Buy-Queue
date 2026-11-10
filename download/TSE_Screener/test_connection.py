"""
test_connection.py
اسکریپت تست اتصال به TSETMC و عیب‌یابی.

این اسکریپت به شما نشان می‌دهد:
  ۱) آیا TSETMC قابل دسترسی است؟
  ۲) آیا کد نماد درست است؟
  ۳) چه داده‌ای از API برمی‌گردد؟
  ۴) کدام فیلد به‌درستی parse می‌شود؟

نحوه اجرا:
  python test_connection.py
  python test_connection.py --ins-code 4674107287748763521
  python test_connection.py --debug
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime

# تنظیم encoding برای Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import MarketDataCollector, MarketSnapshot


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="تست اتصال به TSETMC")
    parser.add_argument("--ins-code", default="4674107287748763521",
                        help="کد ابزار TSETMC")
    parser.add_argument("--symbol", default="دابور", help="نام نماد")
    parser.add_argument("--debug", action="store_true",
                        help="ذخیره پاسخ‌های خام برای دیباگ")
    args = parser.parse_args()

    print("=" * 70)
    print("  TSETMC Connection Test")
    print("=" * 70)
    print()

    config = load_config()
    collector = MarketDataCollector(config)

    if args.debug:
        collector.enable_debug(ROOT / "data" / "raw_responses")
        print("🔍 حالت دیباگ فعال است - پاسخ‌های خام در data/raw_responses ذخیره می‌شوند")
        print()

    print(f"📋 نماد: {args.symbol}")
    print(f"📋 کد ابزار: {args.ins_code}")
    print(f"⏰ زمان تست: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # مرحله ۱: دریافت داده روز جاری
    print("─" * 70)
    print("۱) دریافت داده روز جاری (instinfo)")
    print("─" * 70)

    inst = collector.fetch_intraday(args.ins_code)

    if inst is None:
        print("❌ هیچ پاسخی از TSETMC دریافت نشد!")
        print()
        print("علل احتمالی:")
        print("  • اتصال اینترنت قطع است")
        print("  • TSETMC از دسترس شما بسته شده (IP مسدود)")
        print("  • کد ابزار اشتباه است")
        print("  • ساختار API تغییر کرده و پارسر ناسازگار است")
        print()
        print("اقدامات پیشنهادی:")
        print("  ۱) مرورگر را باز کنید و به http://www.tsetmc.com بروید")
        print("  ۲) اگر باز شد، به صفحه نماد دابور بروید")
        print("  ۳) URL را کپی کنید و کد ابزار را از آن استخراج کنید")
        print("     مثال: http://www.tsetmc.com/Loader.aspx?ParTree=151311&i=4674107287748763521")
        print("     ↑ این عدد همان ins_code است")
        print("  ۴) با --debug اجرا کنید تا پاسخ خام ذخیره شود")
        return

    print("✓ پاسخ دریافت شد")
    print()
    print("داده‌های parse شده:")
    print(f"  آخرین قیمت:        {inst.get('last_price', 0):,}")
    print(f"  قیمت پایانی:      {inst.get('close_price', 0):,}")
    print(f"  قیمت دیروز:       {inst.get('yesterday_price', 0):,}")
    print(f"  بالاترین روز:      {inst.get('daily_high', 0):,}")
    print(f"  پایین‌ترین روز:   {inst.get('daily_low', 0):,}")
    print(f"  حجم معاملات:       {inst.get('trade_volume', 0):,}")
    print(f"  ارزش معاملات:      {inst.get('trade_value', 0):,}")
    print(f"  تعداد معاملات:     {inst.get('trade_count', 0):,}")
    print()

    buy_rows = inst.get("buy_rows", [])
    sell_rows = inst.get("sell_rows", [])
    print(f"  ردیف‌های خرید: {len(buy_rows)}")
    if buy_rows:
        for i, r in enumerate(buy_rows[:3], 1):
            print(f"    {i}: قیمت {r['price']:,} | حجم {r['volume']:,} | سفارش {r['order_count']}")
    print(f"  ردیف‌های فروش: {len(sell_rows)}")
    if sell_rows:
        for i, r in enumerate(sell_rows[:3], 1):
            print(f"    {i}: قیمت {r['price']:,} | حجم {r['volume']:,} | سفارش {r['order_count']}")
    print()

    # مرحله ۲: اطلاعات حقیقی/حقوقی
    print("─" * 70)
    print("۲) اطلاعات حقیقی/حقوقی (clienttype)")
    print("─" * 70)

    ct = collector.fetch_clienttype(args.ins_code)

    if ct is None:
        print("❌ اطلاعات clienttype دریافت نشد")
    else:
        print("✓ دریافت شد")
        print(f"  خریداران حقیقی:    {ct.get('real_buy_count', 0):,}")
        print(f"  فروشندگان حقیقی: {ct.get('real_sell_count', 0):,}")
        print(f"  حجم خرید حقیقی: {ct.get('real_buy_volume', 0):,}")
        print(f"  حجم فروش حقیقی: {ct.get('real_sell_volume', 0):,}")
        print(f"  خریداران حقوقی:    {ct.get('legal_buy_count', 0):,}")
        print(f"  فروشندگان حقوقی: {ct.get('legal_sell_count', 0):,}")
    print()

    # مرحله ۳: معاملات اخیر
    print("─" * 70)
    print("۳) معاملات اخیر (tradehistory)")
    print("─" * 70)

    trades = collector.fetch_trades(args.ins_code)
    if not trades:
        print("❌ معامله‌ای دریافت نشد")
    else:
        print(f"✓ {len(trades)} معامله دریافت شد")
        for t in trades[:5]:
            print(f"  {t.trade_time} | {t.trade_price:,} × {t.trade_volume:,}")
    print()

    # مرحله ۴: ساخت نمونه کامل
    print("─" * 70)
    print("۴) ساخت MarketSnapshot کامل")
    print("─" * 70)

    snap, _ = collector.collect(args.symbol, args.ins_code, fetch_trades=False)

    if snap is None:
        print("❌ ساخت نمونه ناموفق بود")
        return

    print(f"✓ نمونه ساخته شد")
    print(f"  وضعیت داده:        {snap.data_status}")
    if snap.fetch_error:
        print(f"  خطا:               {snap.fetch_error}")
    print(f"  فاز بازار:         {snap.market_phase}")
    print(f"  داده کامل:         {'بله' if snap.data_complete else 'خیر'}")
    if snap.missing_fields:
        print(f"  فیلدهای مفقود:     {', '.join(snap.missing_fields)}")
    print()

    # خلاصه
    print("=" * 70)
    if snap.data_complete and snap.last_price > 0:
        print("✅ نتیجه: همه چیز درست کار می‌کند!")
        print("   می‌توانید run_live.py را اجرا کنید.")
    elif snap.last_price > 0:
        print("⚠️  نتیجه: داده دریافت شد ولی کامل نیست")
        print("   برخی فیلدها مفقودند ولی برنامه کار می‌کند.")
    else:
        print("❌ نتیجه: داده‌ها به‌درستی دریافت نشدند")
        print("   برای عیب‌یابی دقیق‌تر:")
        print("   ۱) با پرچم --debug اجرا کنید")
        print("   ۲) فایل‌های data/raw_responses/ را بررسی کنید")
        print("   ۳) مرورگر را باز کنید و آدرس زیر را تست کنید:")
        print(f"      http://www.tsetmc.com/tsev2/data/instinfodata.aspx?i={args.ins_code}&c=57+")
    print("=" * 70)


if __name__ == "__main__":
    main()
