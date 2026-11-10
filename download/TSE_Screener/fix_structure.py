"""
fix_structure.py
اسکریپت اصلاح ساختار پروژه.

این اسکریپت:
  ۱. ساختار فعلی پروژه را بررسی می‌کند
  ۲. فایل‌های که در محل اشتباه قرار دارند را پیدا می‌کند
  ۳. آن‌ها را به محل صحیح منتقل می‌کند
  ۴. ساختار نهایی را نمایش می‌دهد

نحوه اجرا:
  python fix_structure.py
"""

import sys
import os
import shutil
import json
from pathlib import Path
from datetime import datetime

# تنظیم encoding برای Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent

# ذخیره گزارش
output_log = []

def log(msg=""):
    print(msg)
    output_log.append(str(msg))

def main():
    log("=" * 70)
    log("  TSE Early Warning - Fix Project Structure")
    log("=" * 70)
    log()
    log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Working directory: {Path.cwd()}")
    log(f"Script location: {ROOT}")
    log()

    # ========== بخش ۱: بررسی ساختار فعلی ==========
    log("=" * 70)
    log("PART 1: Current project structure")
    log("=" * 70)
    log()

    expected_files_in_root = {
        "run_demo.py", "run_live.py", "web_dashboard.py", "test_connection.py",
        "view_data.py", "find_symbol_code.py", "search_riton.py",
        "check_version.py", "update_data_collector.py", "diagnose.py",
        "fix_structure.py", "requirements.txt", "README.md", "LICENSE",
        ".gitignore",
    }
    expected_bat_files = {
        "run_web_dashboard.bat", "run_web_dashboard_alt.bat",
        "run_test_connection.bat", "update_from_github.bat",
        "run_everything.bat",
    }
    expected_early_warning_files = {
        "__init__.py", "data_collector.py", "data_validator.py",
        "sell_pressure.py", "smart_accumulation.py", "alert_engine.py",
        "excel_report.py", "storage.py",
    }
    expected_config_files = {"warning_thresholds.json"}

    # بررسی فایل‌های ریشه
    log("Files in root directory:")
    root_files = set()
    for f in ROOT.iterdir():
        if f.is_file():
            root_files.add(f.name)
            log(f"  {f.name}")
    log()

    # بررسی پوشه early_warning
    ew_dir = ROOT / "early_warning"
    log(f"early_warning/ folder exists: {ew_dir.exists()}")
    if ew_dir.exists():
        log("Files in early_warning/:")
        ew_files = set()
        for f in ew_dir.iterdir():
            if f.is_file():
                ew_files.add(f.name)
                log(f"  {f.name}")
    else:
        ew_files = set()
    log()

    # ========== بخش ۲: یافتن فایل‌های اشتباه ==========
    log("=" * 70)
    log("PART 2: Finding misplaced files")
    log("=" * 70)
    log()

    # جستجوی data_collector.py در همه مسیرها
    log("Searching for data_collector.py in all subdirectories...")
    found_dc_files = []
    for p in ROOT.rglob("data_collector.py"):
        found_dc_files.append(p)
        with open(p, 'r', encoding='utf-8') as f:
            content = f.read()
        has_cdn = "cdn.tsetmc.com" in content
        log(f"  Found: {p}")
        log(f"    Has cdn.tsetmc.com (NEW v3): {has_cdn}")
    log()

    # جستجوی سایر فایل‌های early_warning
    log("Searching for other early_warning files in wrong locations...")
    misplaced_ew_files = []
    for ew_file in expected_early_warning_files:
        for p in ROOT.rglob(ew_file):
            # اگر در early_warning/ نباشد، اشتباه است
            if "early_warning" not in p.parts:
                misplaced_ew_files.append(p)
                log(f"  Misplaced: {p}")
    log()

    # ========== بخش ۳: انتقال فایل‌های اشتباه ==========
    log("=" * 70)
    log("PART 3: Moving misplaced files to correct location")
    log("=" * 70)
    log()

    # ایجاد پوشه early_warning اگر وجود ندارد
    if not ew_dir.exists():
        log("Creating early_warning/ folder...")
        ew_dir.mkdir()
        log("  Done")
        log()

    # انتقال data_collector.py
    target_dc = ew_dir / "data_collector.py"
    if not target_dc.exists() or (target_dc.exists() and not "cdn.tsetmc.com" in target_dc.read_text(encoding='utf-8')):
        # پیدا کردن نسخه جدید
        new_dc = None
        for p in found_dc_files:
            with open(p, 'r', encoding='utf-8') as f:
                if "cdn.tsetmc.com" in f.read():
                    new_dc = p
                    break

        if new_dc and new_dc != target_dc:
            log(f"Copying data_collector.py from: {new_dc}")
            log(f"                    to: {target_dc}")
            shutil.copy2(new_dc, target_dc)
            log("  Done")
            # اگر فایل در ریشه است و در early_warning نیست، آن را حذف نکن
            # چون ممکن است بقیه برنامه از آن استفاده کنند
            log()

    # انتقال سایر فایل‌های early_warning
    for ew_file in expected_early_warning_files:
        target_path = ew_dir / ew_file
        if not target_path.exists():
            # جستجوی فایل
            for p in misplaced_ew_files:
                if p.name == ew_file:
                    log(f"Copying {ew_file} from: {p}")
                    log(f"              to: {target_path}")
                    shutil.copy2(p, target_path)
                    log("  Done")
                    log()
                    break

    # ========== بخش ۴: ساختار نهایی ==========
    log("=" * 70)
    log("PART 4: Final structure verification")
    log("=" * 70)
    log()

    log("Final early_warning/ folder contents:")
    if ew_dir.exists():
        for f in sorted(ew_dir.iterdir()):
            if f.is_file():
                log(f"  {f.name}")
                if f.name == "data_collector.py":
                    with open(f, 'r', encoding='utf-8') as fh:
                        c = fh.read()
                    log(f"    Has cdn.tsetmc.com: {'cdn.tsetmc.com' in c}")
    log()

    # ========== بخش ۵: تست import ==========
    log("=" * 70)
    log("PART 5: Testing imports")
    log("=" * 70)
    log()

    try:
        sys.path.insert(0, str(ROOT))
        from early_warning import MarketDataCollector
        log("  MarketDataCollector: imported OK ✓")

        config = json.loads((ROOT / "config" / "warning_thresholds.json").read_text(encoding='utf-8'))
        collector = MarketDataCollector(config)
        log(f"  API_BASE: {collector.API_BASE}")
        log(f"  has enable_debug: {hasattr(collector, 'enable_debug')}")
        log(f"  has search_symbol: {hasattr(collector, 'search_symbol')}")

        if hasattr(collector, 'search_symbol'):
            log()
            log("  Testing search_symbol with 'rhyton'...")
            try:
                results = collector.search_symbol("rhyton")
                log(f"  Found {len(results)} results")
                for r in results[:3]:
                    log(f"    code={r.get('code')}, name_fa={r.get('name_fa')}, name_en={r.get('name_en')}")
            except Exception as e:
                log(f"  ERROR: {e}")
    except Exception as e:
        log(f"  ERROR: {e}")
        import traceback
        log(traceback.format_exc())

    log()

    # ========== گزارش نهایی ==========
    log("=" * 70)
    log("DONE!")
    log("=" * 70)
    log()

    report_path = ROOT / "data" / "fix_structure_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))
    log(f"Report saved to: {report_path}")

    # باز کردن خودکار در Notepad
    try:
        os.startfile(str(report_path))
    except:
        pass

    log()
    try:
        input("Press Enter to exit...")
    except:
        pass

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL ERROR: {e}")
        import traceback
        log(traceback.format_exc())
        report_path = ROOT / "data" / "fix_structure_report.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_log))
        try:
            input("Press Enter to exit...")
        except:
            pass
