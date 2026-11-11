"""
check_status.py
بررسی سریع وضعیت داده‌ها و داشبورد.

نحوه اجرا:
  python check_status.py
"""

import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent

print("=" * 60)
print("  بررسی وضعیت داده‌ها")
print("=" * 60)
print(f"زمان: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ۱. پیکربندی
print("=" * 60)
print("۱. پیکربندی نماد")
print("=" * 60)
cfg_path = ROOT / "config" / "warning_thresholds.json"
print(f"مسیر: {cfg_path}")
print(f"موجود: {cfg_path.exists()}")
if cfg_path.exists():
    cfg = json.loads(cfg_path.read_text(encoding='utf-8'))
    ts = cfg["test_symbol"]
    print(f"نماد: {ts['name']}")
    print(f"کد: {ts['ins_code']}")
print()

# ۲. بانک اطلاعاتی
print("=" * 60)
print("۲. بانک اطلاعاتی")
print("=" * 60)
db_path = ROOT / "data" / "early_warning_live.sqlite"
print(f"مسیر: {db_path}")
print(f"موجود: {db_path.exists()}")

if db_path.exists():
    print(f"اندازه: {db_path.stat().st_size:,} bytes")
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # تعداد نمونه‌ها
        cur.execute("SELECT COUNT(*) FROM snapshots")
        count = cur.fetchone()[0]
        print(f"تعداد نمونه‌ها: {count}")

        if count > 0:
            # نمادهای موجود
            cur.execute("SELECT symbol, COUNT(*) FROM snapshots GROUP BY symbol")
            for sym, cnt in cur.fetchall():
                print(f"  نماد '{sym}': {cnt} نمونه")

            # آخرین نمونه
            cur.execute("SELECT tehran_time, symbol, last_price, close_price, market_phase FROM snapshots ORDER BY timestamp DESC LIMIT 1")
            row = cur.fetchone()
            print(f"\nآخرین نمونه:")
            print(f"  زمان: {row[0]}")
            print(f"  نماد: {row[1]}")
            print(f"  آخرین قیمت: {row[2]:,}" if row[2] else "  آخرین قیمت: 0")
            print(f"  قیمت پایانی: {row[3]:,}" if row[3] else "  قیمت پایانی: 0")
            print(f"  فاز: {row[4]}")

            # ۵ نمونه اخیر
            print(f"\n۵ نمونه اخیر:")
            cur.execute("SELECT tehran_time, last_price, close_price, market_phase FROM snapshots ORDER BY timestamp DESC LIMIT 5")
            for r in cur.fetchall():
                print(f"  {r[0]} | قیمت: {r[1] or 0:,} | فاز: {r[3]}")
        else:
            print("\n⚠ بانک خالی است! run_live.py اجرا نشده یا داده‌ای دریافت نکرده.")
        conn.close()
    except Exception as e:
        print(f"خطا: {e}")
else:
    print("\n⚠ بانک اطلاعاتی وجود ندارد!")
    print("   run_live.py را اجرا کنید تا ساخته شود.")
print()

# ۳. تشخیص مشکل
print("=" * 60)
print("۳. تشخیص مشکل")
print("=" * 60)
if not db_path.exists() or count == 0:
    print("❌ مشکلات احتمالی:")
    print("   ۱. run_live.py اجرا نشده")
    print("   ۲. بازار بسته است (ساعت 09:00-12:30 یا 12:30-18:00)")
    print("   ۳. کد نماد اشتباه است")
    print()
    print("اقدامات:")
    print("   ۱. در ساعات بازار اجرا کنید")
    print("   ۲. python run_live.py را اجرا کنید")
    print("   ۳. خروجی را بررسی کنید - آیا قیمت‌ها غیر صفر هستند؟")
elif row[2] == 0 and row[3] == 0:
    print("⚠ داده‌ها صفر هستند - نماد معامله نداشته یا کد اشتباه است")
else:
    print("✓ داده‌ها موجود هستند")
    print("اگر داشبورد خالی است:")
    print("   ۱. python web_dashboard.py --port 8050 را اجرا کنید")
    print("   ۲. مرورگر: http://localhost:8050")
    print("   ۳. Ctrl+F5 برای refresh")
print()

try:
    input("Press Enter to exit...")
except:
    pass
