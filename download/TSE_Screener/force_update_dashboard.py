"""
force_update_dashboard.py
جایگزینی قطعی web_dashboard.py با نسخه GitHub (بدون نوار نماد فعال).

این اسکریپت:
  ۱. همه فایل‌های web_dashboard*.py را پیدا می‌کند
  ۲. نسخه جدید را از GitHub دانلود می‌کند
  ۳. همه را با نسخه جدید جایگزین می‌کند
  ۴. تأیید می‌کند که نوار نماد فعال حذف شده است

نحوه اجرا:
  python force_update_dashboard.py
"""

import sys
import os
import shutil
import urllib.request
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
GITHUB_URL = "https://raw.githubusercontent.com/javadsekhavatpour/Sell-Buy-Queue/main/web_dashboard.py"

print("=" * 70)
print("  Force Update web_dashboard.py")
print("=" * 70)
print()

# مرحله ۱: یافتن همه فایل‌های web_dashboard*.py
print("=" * 70)
print("STEP 1: Finding all web_dashboard files")
print("=" * 70)
print()

found_files = []
for p in ROOT.rglob("web_dashboard*.py"):
    found_files.append(p)
    with open(p, 'r', encoding='utf-8') as f:
        content = f.read()
    has_symbol_bar = ("symbolInput" in content or
                      "searchAndSelectSymbol" in content or
                      "نماد فعال" in content)
    print(f"  {p}")
    print(f"    Has symbol bar: {has_symbol_bar}")
    print(f"    Size: {len(content)} chars")
    print()

print(f"Total: {len(found_files)} files")
print()

# مرحله ۲: دانلود نسخه جدید
print("=" * 70)
print("STEP 2: Downloading new version from GitHub")
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
    print(f"  Has symbol bar: {'symbolInput' in new_text}")
    print(f"  Has 'نماد فعال': {'نماد فعال' in new_text}")
    print()
except Exception as e:
    print(f"  ERROR: {e}")
    input("Press Enter to exit...")
    sys.exit(1)

# مرحله ۳: جایگزینی همه فایل‌ها
print("=" * 70)
print("STEP 3: Replacing ALL files with new version")
print("=" * 70)
print()

replaced = 0
for p in found_files:
    print(f"  Replacing: {p}")
    try:
        backup = p.with_suffix('.py.bak')
        if backup.exists():
            backup.unlink()
        shutil.copy2(p, backup)
        print(f"    Backup: {backup}")

        with open(p, 'wb') as f:
            f.write(new_content)

        with open(p, 'r', encoding='utf-8') as f:
            verify = f.read()
        has_symbol_bar = ("symbolInput" in verify or
                          "searchAndSelectSymbol" in verify or
                          "نماد فعال" in verify)
        print(f"    Verifying - has symbol bar: {has_symbol_bar}")
        if not has_symbol_bar:
            print(f"    ✓ Successfully replaced (no symbol bar)")
            replaced += 1
        else:
            print(f"    ⚠ Still has symbol bar!")
        print()
    except Exception as e:
        print(f"    ERROR: {e}")
        print()

print(f"Successfully replaced: {replaced}/{len(found_files)}")
print()

# مرحله ۴: تأیید نهایی
print("=" * 70)
print("STEP 4: Final verification")
print("=" * 70)
print()

for p in ROOT.rglob("web_dashboard*.py"):
    with open(p, 'r', encoding='utf-8') as f:
        c = f.read()
    has_bar = ("symbolInput" in c or
               "searchAndSelectSymbol" in c or
               "نماد فعال" in c)
    status = "✓ NO symbol bar" if not has_bar else "✗ HAS symbol bar"
    print(f"  {p}: {status}")

print()
print("=" * 70)
print("DONE!")
print("=" * 70)
print()
print("Next steps:")
print("  1) Stop web_dashboard.py (Ctrl+C in its CMD window)")
print("  2) Run: python web_dashboard.py --port 8050")
print("  3) Browser: http://localhost:8050")
print("  4) Refresh with Ctrl+F5 to clear browser cache")
print()

try:
    input("Press Enter to exit...")
except:
    pass
