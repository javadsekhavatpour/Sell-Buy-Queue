"""
check_dashboard_version.py
تشخیص نسخه فعلی web_dashboard.py که در حال اجراست.

این اسکریپت:
  ۱. همه فایل‌های web_dashboard*.py را پیدا می‌کند
  ۲. نشانه‌های نسخه را بررسی می‌کند
  ۳. به شما می‌گوید کدام نسخه دارید و چه باید ببینید

نحوه اجرا:
  python check_dashboard_version.py
"""

import sys
import os
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent

print("=" * 70)
print("  TSE Early Warning - Dashboard Version Check")
print("=" * 70)
print()
print(f"Working directory: {Path.cwd()}")
print(f"Script location: {ROOT}")
print()

# یافتن همه فایل‌های web_dashboard*.py
print("=" * 70)
print("PART 1: Finding all web_dashboard files")
print("=" * 70)
print()

found_files = []
for p in ROOT.rglob("web_dashboard*.py"):
    found_files.append(p)

if not found_files:
    print("  No web_dashboard*.py files found!")
    print()
    print("  Download from:")
    print("  https://github.com/javadsekhavatpour/Sell-Buy-Queue/raw/main/web_dashboard.py")
    input("Press Enter to exit...")
    sys.exit(1)

for p in found_files:
    print(f"  Found: {p}")
    with open(p, 'r', encoding='utf-8') as f:
        content = f.read()

    # نشانه‌های نسخه
    has_v2_label = "v2.0-TSETMC" in content
    has_chart_js = "chart.js" in content.lower() or "Chart.js" in content
    has_top_row_grid = "grid-template-columns" in content
    has_real_legal = "real-legal-table" in content
    has_simple_layout = "score-display" in content  # v1 marker
    file_size = len(content)

    print(f"    Size: {file_size} chars")
    print(f"    Has 'v2.0-TSETMC' label: {has_v2_label}")
    print(f"    Has Chart.js: {has_chart_js}")
    print(f"    Has grid top-row: {has_top_row_grid}")
    print(f"    Has real-legal-table: {has_real_legal}")
    print(f"    Has v1 'score-display': {has_simple_layout}")

    # تشخیص نسخه
    if has_v2_label:
        version = "v2.0 (TSETMC style) - LATEST"
    elif has_chart_js and has_top_row_grid and has_real_legal:
        version = "v2.0/v2.1 (TSETMC style)"
    elif has_simple_layout and not has_top_row_grid:
        version = "v1 (simple layout) - OLD"
    else:
        version = "Unknown"

    print(f"    >>> VERSION: {version}")
    print()

# تشخیص نسخه‌ای که import می‌شود
print("=" * 70)
print("PART 2: Which version will Python import?")
print("=" * 70)
print()

try:
    sys.path.insert(0, str(ROOT))
    # اگر web_dashboard قبلاً import شده، آن را پاک کن
    if 'web_dashboard' in sys.modules:
        del sys.modules['web_dashboard']
    import web_dashboard
    src_file = web_dashboard.__file__
    print(f"  Python imports: {src_file}")

    with open(src_file, 'r', encoding='utf-8') as f:
        content = f.read()
    if "v2.0-TSETMC" in content:
        print("  >>> This is v2.0 (TSETMC style) - CORRECT!")
    elif "score-display" in content:
        print("  >>> This is v1 (simple) - WRONG! Need to update.")
    else:
        print("  >>> Unknown version")
except Exception as e:
    print(f"  ERROR: {e}")

print()
print("=" * 70)
print("INSTRUCTIONS")
print("=" * 70)
print()
print("If you see v1 (simple) instead of v2.0 (TSETMC style):")
print()
print("  1) Stop the server (Ctrl+C)")
print("  2) Delete the OLD web_dashboard.py file")
print("  3) Download NEW from:")
print("     https://github.com/javadsekhavatpour/Sell-Buy-Queue/raw/main/web_dashboard.py")
print("  4) Save it as: web_dashboard.py")
print("  5) Run: python web_dashboard.py --port 8052")
print("  6) Browser: http://localhost:8052")
print("  7) Refresh with: Ctrl+F5 (hard refresh to clear cache)")
print()
print("If you see v2.0-TSETMC label in the header, then you have the right version!")
print()

try:
    input("Press Enter to exit...")
except:
    pass
