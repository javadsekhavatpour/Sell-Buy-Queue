"""
force_replace_data_collector.py
جایگزینی قطعی و اجباری data_collector.py با نسخه GitHub.

این اسکریپت:
  ۱. همه فایل‌های data_collector.py در سیستم را پیدا می‌کند
  ۲. نسخه جدید را از GitHub دانلود می‌کند
  ۳. همه نسخه‌های قدیمی را با نسخه جدید جایگزین می‌کند
  ۴. تأیید می‌کند که همه نسخه‌ها جدید هستند

نحوه اجرا:
  python force_replace_data_collector.py
"""

import sys
import os
import shutil
import urllib.request
from pathlib import Path
from datetime import datetime

# تنظیم encoding برای Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
GITHUB_URL = "https://raw.githubusercontent.com/javadsekhavatpour/Sell-Buy-Queue/main/early_warning/data_collector.py"

print("=" * 70)
print("  Force Replace data_collector.py")
print("=" * 70)
print()
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Working dir: {Path.cwd()}")
print()

# مرحله ۱: پیدا کردن همه فایل‌های data_collector.py
print("=" * 70)
print("STEP 1: Finding all data_collector.py files")
print("=" * 70)
print()

found_files = []
for p in ROOT.rglob("data_collector.py"):
    found_files.append(p)
    with open(p, 'r', encoding='utf-8') as f:
        content = f.read()
    has_cdn = "cdn.tsetmc.com" in content
    has_old_bug = "r.order_count for r in inst.get" in content
    print(f"  Found: {p}")
    print(f"    Has cdn.tsetmc.com (NEW v3): {has_cdn}")
    print(f"    Has old bug (r.order_count bug): {has_old_bug}")
    print(f"    Size: {len(content)} chars")
    print()

if not found_files:
    print("  No data_collector.py found!")
    input("Press Enter to exit...")
    sys.exit(1)

print(f"Total found: {len(found_files)} files")
print()

# مرحله ۲: دانلود نسخه جدید از GitHub
print("=" * 70)
print("STEP 2: Downloading NEW version from GitHub")
print("=" * 70)
print()
print(f"URL: {GITHUB_URL}")
print()

try:
    req = urllib.request.Request(GITHUB_URL, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        new_content = response.read()

    new_text = new_content.decode('utf-8')
    print(f"  Downloaded: {len(new_content)} bytes")
    print(f"  Has cdn.tsetmc.com: {'cdn.tsetmc.com' in new_text}")
    print(f"  Has r['order_count'] (FIXED): {\"r[\\\"order_count\\\"]\" in new_text}")
    print()
except Exception as e:
    print(f"  ERROR downloading: {e}")
    input("Press Enter to exit...")
    sys.exit(1)

# مرحله ۳: جایگزینی همه فایل‌ها با نسخه جدید
print("=" * 70)
print("STEP 3: Replacing ALL files with NEW version")
print("=" * 70)
print()

replaced_count = 0
for p in found_files:
    print(f"  Replacing: {p}")
    try:
        # بک‌آپ از نسخه قدیمی
        backup_path = p.with_suffix('.py.bak')
        if backup_path.exists():
            backup_path.unlink()
        shutil.copy2(p, backup_path)
        print(f"    Backup: {backup_path}")

        # نوشتن نسخه جدید
        with open(p, 'wb') as f:
            f.write(new_content)

        # تأیید
        with open(p, 'r', encoding='utf-8') as f:
            verify = f.read()
        has_cdn = "cdn.tsetmc.com" in verify
        has_fix = "r[\"order_count\"]" in verify or "r['order_count']" in verify
        print(f"    Verifying: cdn={has_cdn}, fix={has_fix}")
        if has_cdn and has_fix:
            print(f"    ✓ Successfully replaced")
            replaced_count += 1
        else:
            print(f"    ⚠ Verification failed")
        print()
    except Exception as e:
        print(f"    ERROR: {e}")
        print()

print(f"Successfully replaced: {replaced_count}/{len(found_files)} files")
print()

# مرحله ۴: تأیید نهایی
print("=" * 70)
print("STEP 4: Final verification")
print("=" * 70)
print()

for p in ROOT.rglob("data_collector.py"):
    with open(p, 'r', encoding='utf-8') as f:
        c = f.read()
    has_cdn = "cdn.tsetmc.com" in c
    has_old_bug = "r.order_count for r in inst.get" in c
    status = "✓ NEW (fixed)" if has_cdn and not has_old_bug else "✗ OLD or buggy"
    print(f"  {p}: {status}")

print()
print("=" * 70)
print("DONE!")
print("=" * 70)
print()
print("Now run:")
print("  python test_riton.py")
print()
print("It should NOT have the 'dict.order_count' error this time!")
print()

try:
    input("Press Enter to exit...")
except:
    pass
