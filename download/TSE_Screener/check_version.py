"""
check_version.py
اسکریپت تشخیص نسخه data_collector.py

این اسکریپت نشان می‌دهد:
  - کدام نسخه data_collector.py دارید (قدیمی یا جدید)
  - آیا API جدید cdn.tsetmc.com در دسترس است
  - کجا فایل باید جایگزین شود
"""

import sys
import os
from pathlib import Path

# تنظیم encoding برای Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

print("=" * 70)
print("  TSE Early Warning - Version Check")
print("=" * 70)
print()

# پیدا کردن مسیر فعلی
current_dir = Path.cwd()
print(f"Current directory: {current_dir}")
print()

# بررسی چند مسیر ممکن
possible_paths = [
    current_dir / "early_warning" / "data_collector.py",
    current_dir / "Sell-Buy-Queue-main" / "early_warning" / "data_collector.py",
    current_dir.parent / "early_warning" / "data_collector.py",
    current_dir.parent / "Sell-Buy-Queue-main" / "early_warning" / "data_collector.py",
]

print("Looking for data_collector.py in possible locations:")
print("─" * 70)

found_path = None
for i, path in enumerate(possible_paths, 1):
    exists = path.exists()
    print(f"  {i}. {path}")
    print(f"     exists: {exists}")
    if exists:
        if not found_path:
            found_path = path

print()

if not found_path:
    print("ERROR: Could not find data_collector.py")
    print()
    print("Please check that:")
    print("  - You are running this script from the project root")
    print("  - The early_warning/ folder exists")
    print("  - data_collector.py is inside early_warning/")
    print()
    # جستجوی کامل
    print("Searching for data_collector.py in current directory tree...")
    for p in current_dir.rglob("data_collector.py"):
        print(f"  Found: {p}")
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
        has_cdn = "cdn.tsetmc.com" in content
        has_old_api = "tsev2/data/instinfodata.aspx" in content
        has_enable_debug = "def enable_debug" in content
        print(f"    Has cdn.tsetmc.com (NEW): {has_cdn}")
        print(f"    Has old API (OLD):       {has_old_api}")
        print(f"    Has enable_debug:        {has_enable_debug}")
        print()
    try:
        input("Press Enter to exit...")
    except:
        pass
    sys.exit(1)

print(f"Found data_collector.py at: {found_path}")
print()

# بررسی محتوای فایل
with open(found_path, 'r', encoding='utf-8') as f:
    content = f.read()

print("Checking version indicators:")
print("─" * 70)

checks = [
    ("cdn.tsetmc.com (NEW API v3)", "cdn.tsetmc.com" in content),
    ("Old API instinfodata.aspx", "tsev2/data/instinfodata.aspx" in content),
    ("enable_debug method defined", "def enable_debug" in content),
    ("search_symbol method", "def search_symbol" in content),
    ("API_BASE constant", "API_BASE" in content),
]

for name, exists in checks:
    mark = "[YES]" if exists else "[NO] "
    print(f"  {mark} {name}")

print()
print("=" * 70)
# نتیجه‌گیری
has_cdn = "cdn.tsetmc.com" in content
has_old = "tsev2/data/instinfodata.aspx" in content
has_enable_debug = "def enable_debug" in content

if has_cdn and has_enable_debug:
    print("  RESULT: You have the NEW version (v3.0) ✓")
    print("  You can run search_riton.py and test_connection.py")
elif has_old or not has_enable_debug:
    print("  RESULT: You have the OLD version ✗")
    print()
    print("  You need to update data_collector.py!")
    print()
    print("  To update:")
    print("  1) Download from:")
    print("     https://github.com/javadsekhavatpour/Sell-Buy-Queue/raw/main/early_warning/data_collector.py")
    print(f"  2) Replace the file at:")
    print(f"     {found_path}")
    print("  3) Run this check again: python check_version.py")
else:
    print("  RESULT: Unknown version - check indicators above")

print("=" * 70)
print()

# نمایش اولین خط فایل برای تأیید
print("First 10 lines of your data_collector.py:")
print("─" * 70)
for i, line in enumerate(content.split('\n')[:15], 1):
    print(f"  {i}: {line}")

print()
try:
    input("Press Enter to exit...")
except:
    pass
