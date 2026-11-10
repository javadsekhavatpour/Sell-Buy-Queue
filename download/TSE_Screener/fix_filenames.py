"""
fix_filenames.py
اسکریپت رفع مشکل نام فایل‌ها با فاصله اضافی.

مشکل:
  هنگام دانلود از GitHub، ممکن است فایل‌ها با فاصله اضافی ذخیره شوند:
    web_dashboard .py  (با فاصله قبل از .py)
    data_collector .py

این اسکریپت همه فایل‌های پایتون با نام اشتباه را پیدا و اصلاح می‌کند.

نحوه اجرا:
  python fix_filenames.py
"""

import sys
import os
import shutil
from pathlib import Path

# تنظیم encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent

print("=" * 70)
print("  TSE Early Warning - Fix Filenames")
print("=" * 70)
print()
print(f"Working directory: {ROOT}")
print()

# لیست فایل‌های مورد انتظار
expected_files = [
    "web_dashboard.py",
    "test_connection.py",
    "test_dashboard.py",
    "test_riton.py",
    "search_riton.py",
    "find_symbol_code.py",
    "diagnose.py",
    "check_version.py",
    "fix_structure.py",
    "fix_filenames.py",
    "force_replace_data_collector.py",
    "update_data_collector.py",
    "update_from_github.py",
    "view_data.py",
    "run_demo.py",
    "run_live.py",
    "data_collector.py",
]

# یافتن همه فایل‌های .py در پوشه فعلی و زیرپوشه‌ها
print("=" * 70)
print("PART 1: Finding all .py files (including ones with spaces)")
print("=" * 70)
print()

found_files = []
for p in ROOT.rglob("*.py"):
    found_files.append(p)
    print(f"  {p.name} -> {p}")

print()
print(f"Total .py files found: {len(found_files)}")
print()

# یافتن فایل‌های با نام اشتباه (دارای فاصله اضافی)
print("=" * 70)
print("PART 2: Finding files with bad names (extra spaces)")
print("=" * 70)
print()

bad_files = []
for p in found_files:
    # بررسی فاصله قبل از .py
    if " .py" in p.name or p.name.endswith(" .py") or p.name.startswith(" "):
        bad_files.append(p)
        print(f"  ⚠ BAD NAME: {p}")
    # بررسی فاصله در نام
    elif "  " in p.name:  # دو فاصله پشت سر هم
        bad_files.append(p)
        print(f"  ⚠ DOUBLE SPACE: {p}")

if not bad_files:
    print("  ✓ No files with bad names found")
else:
    print()
    print(f"Found {len(bad_files)} files with bad names")
print()

# اصلاح نام فایل‌ها
print("=" * 70)
print("PART 3: Renaming bad files")
print("=" * 70)
print()

for p in bad_files:
    # حذف فاصله‌های اضافی از نام
    new_name = p.name.replace(" .py", ".py").replace("  ", " ").strip()
    new_path = p.parent / new_name

    if new_path == p:
        # نام درست است
        continue

    print(f"  Renaming: {p.name}")
    print(f"       to: {new_name}")

    if new_path.exists():
        # فایل با نام درست از قبل وجود دارد
        print(f"    ⚠ Target file already exists!")
        print(f"    Replacing with bad-named version (which may be newer)")
        # بک‌آپ از فایل فعلی
        backup = new_path.with_suffix('.py.bak')
        shutil.copy2(new_path, backup)
        print(f"    Backup: {backup}")
        # حذف فایل با نام درست و جایگزینی با فایل نام اشتباه
        new_path.unlink()
        p.rename(new_path)
        print(f"    ✓ Renamed")
    else:
        # فقط تغییر نام
        p.rename(new_path)
        print(f"    ✓ Renamed")
    print()

# بررسی نهایی - آیا همه فایل‌های مورد نیاز وجود دارند؟
print("=" * 70)
print("PART 4: Final verification")
print("=" * 70)
print()

missing = []
for f in expected_files:
    # جستجو در همه پوشه‌ها
    found = False
    for p in ROOT.rglob(f):
        if p.is_file():
            found = True
            break
    if found:
        print(f"  ✓ {f}")
    else:
        # بررسی با نام دارای فاصله
        for p in ROOT.rglob("*"):
            if p.is_file() and p.name.replace(" ", "") == f.replace(" ", ""):
                print(f"  ⚠ {f} -> found as: {p.name}")
                found = True
                break
    if not found:
        missing.append(f)
        print(f"  ✗ {f} - NOT FOUND")

print()
if missing:
    print(f"⚠ {len(missing)} files still missing:")
    for f in missing:
        print(f"    {f}")
    print()
    print("Download from:")
    print("  https://github.com/javadsekhavatpour/Sell-Buy-Queue/raw/main/" + missing[0])
else:
    print("✓ All expected files are present!")
print()

# تست import
print("=" * 70)
print("PART 5: Test import of web_dashboard")
print("=" * 70)
print()

try:
    sys.path.insert(0, str(ROOT))
    import web_dashboard
    print("✓ web_dashboard.py imported successfully!")
    print(f"  DB_PATH: {web_dashboard.DB_PATH}")
except Exception as e:
    print(f"✗ ERROR: {e}")
    import traceback
    print(traceback.format_exc())
print()

print("=" * 70)
print("DONE!")
print("=" * 70)
print()
print("Next steps:")
print("  1) python web_dashboard.py --port 8052")
print("  2) Open browser: http://localhost:8052")
print()

try:
    input("Press Enter to exit...")
except:
    pass
