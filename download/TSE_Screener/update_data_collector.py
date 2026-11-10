"""
update_data_collector.py
اسکریپت به‌روزرسانی خودکار فایل data_collector.py

این اسکریپت:
  ۱. فایل جدید data_collector.py را از GitHub دانلود می‌کند
  ۲. در پوشه early_warning/ ذخیره می‌کند
  ۳. نسخه قدیمی را به data_collector_old.py تغییر نام می‌دهد

نحوه اجرا:
  python update_data_collector.py
"""

import sys
import os
import urllib.request
from pathlib import Path

# تنظیم encoding برای Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

GITHUB_URL = "https://raw.githubusercontent.com/javadsekhavatpour/Sell-Buy-Queue/main/early_warning/data_collector.py"
FILENAME = "data_collector.py"
FILENAME_OLD = "data_collector_old.py"

print("=" * 70)
print("  TSE Early Warning - Auto Update data_collector.py")
print("=" * 70)
print()

current_dir = Path.cwd()
print(f"Current directory: {current_dir}")

# پیدا کردن پوشه early_warning
target_dir = None
candidates = [
    current_dir / "early_warning",
    current_dir / "Sell-Buy-Queue-main" / "early_warning",
    current_dir.parent / "early_warning",
    current_dir.parent / "Sell-Buy-Queue-main" / "early_warning",
]

for path in candidates:
    if path.exists():
        target_dir = path
        break

if not target_dir:
    # جستجوی بازگشتی
    print("Searching for early_warning/ folder...")
    for p in current_dir.rglob("early_warning"):
        if p.is_dir():
            target_dir = p
            break

if not target_dir:
    print("ERROR: Cannot find 'early_warning/' folder")
    print()
    print("Please make sure you are in the project root directory.")
    print("Current directory is:")
    print(f"  {current_dir}")
    print()
    try:
        input("Press Enter to exit...")
    except:
        pass
    sys.exit(1)

target_file = target_dir / FILENAME
old_file = target_dir / FILENAME_OLD

print(f"Target folder: {target_dir}")
print(f"Target file:   {target_file}")
print()

# بررسی نسخه فعلی
if target_file.exists():
    with open(target_file, 'r', encoding='utf-8') as f:
        current_content = f.read()
    has_cdn = "cdn.tsetmc.com" in current_content
    print(f"Current version: {'NEW' if has_cdn else 'OLD'}")
    if has_cdn:
        print("You already have the new version!")
        print("No update needed.")
        try:
            input("Press Enter to exit...")
        except:
            pass
        sys.exit(0)

    # تغییر نام فایل قدیمی
    print(f"Backing up old file to: {old_file}")
    try:
        if old_file.exists():
            old_file.unlink()
        target_file.rename(old_file)
        print("Backup done")
    except Exception as e:
        print(f"ERROR during backup: {e}")

print()
print("Downloading new data_collector.py from GitHub...")
print(f"URL: {GITHUB_URL}")
print()

try:
    # هدرهای شبیه مرورگر
    req = urllib.request.Request(
        GITHUB_URL,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        content = response.read()

    # ذخیره فایل
    with open(target_file, 'wb') as f:
        f.write(content)

    print(f"SUCCESS! File saved to: {target_file}")
    print(f"File size: {len(content)} bytes")

    # بررسی نسخه جدید
    with open(target_file, 'r', encoding='utf-8') as f:
        new_content = f.read()
    has_cdn = "cdn.tsetmc.com" in new_content
    print()
    print(f"New version has cdn.tsetmc.com: {has_cdn}")
    if has_cdn:
        print()
        print("=" * 70)
        print("  Update successful! ✓")
        print("  You now have the new API v3.0 collector")
        print("=" * 70)
        print()
        print("Next steps:")
        print("  1) python check_version.py   (verify)")
        print("  2) python search_riton.py     (find ریتون code)")
        print("  3) python test_connection.py --debug  (test)")
    else:
        print()
        print("WARNING: Downloaded file does not have cdn.tsetmc.com")
        print("Maybe GitHub returned an error page")

except Exception as e:
    print(f"ERROR downloading: {e}")
    print()
    print("Please download manually from:")
    print(f"  {GITHUB_URL}")
    print(f"And save it to: {target_file}")

print()
try:
    input("Press Enter to exit...")
except:
    pass
