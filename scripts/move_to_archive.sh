#!/bin/bash
# انتقال فایل‌های غیرضروری به Archive/ با حفظ ساختار پوشه‌ای
cd /home/z/my-project/download/TSE_Screener

# ایجاد پوشه‌های Archive
mkdir -p Archive/data Archive/reports

# ── فایل‌های ریشه → Archive/ ──
ROOT_FILES=(
  "FIELD_MAPPING.md"
  "GITHUB_PUSH_GUIDE.md"
  "UPLOAD_TO_GITHUB.sh"
  "check_dashboard_version.py"
  "check_status.py"
  "check_symbol_status.py"
  "check_version.py"
  "debug_clienttype.py"
  "debug_clienttype_detailed.py"
  "diagnose.py"
  "find_symbol_code.py"
  "fix_filenames.py"
  "fix_structure.py"
  "force_replace_data_collector.py"
  "force_update_dashboard.py"
  "run_demo.py"
  "run_everything.bat"
  "run_test_connection.bat"
  "run_web_dashboard.bat"
  "run_web_dashboard_alt.bat"
  "search_riton.py"
  "test_connection.py"
  "test_dabeus.py"
  "test_dashboard.py"
  "test_riton.py"
  "update_data_collector.py"
  "update_from_github.bat"
  "upload_to_github.ps1"
  "view_data.py"
  "web_dashboard.py"
  "web_dashboard_db.py"
)

moved=0
failed=0
for f in "${ROOT_FILES[@]}"; do
  if [ -f "$f" ]; then
    git mv "$f" "Archive/$f" 2>/dev/null && moved=$((moved+1)) || failed=$((failed+1))
  fi
done

# ─ـ data/ → Archive/data/ ──
DATA_FILES=(
  "data/early_warning.sqlite"
  "data/snapshots_export_accumulation.csv"
  "data/snapshots_export_mixed.csv"
  "data/snapshots_export_sell_pressure.csv"
  "data/trades_export_accumulation.csv"
  "data/trades_export_mixed.csv"
  "data/trades_export_sell_pressure.csv"
)
for f in "${DATA_FILES[@]}"; do
  if [ -f "$f" ]; then
    git mv "$f" "Archive/$f" 2>/dev/null && moved=$((moved+1)) || failed=$((failed+1))
  fi
done

# ── reports/ → Archive/reports/ ──
REPORT_FILES=(
  "reports/early_warning_report.pdf"
  "reports/early_warning_report.xlsx"
  "reports/early_warning_report_accumulation.xlsx"
  "reports/early_warning_report_mixed.xlsx"
)
for f in "${REPORT_FILES[@]}"; do
  if [ -f "$f" ]; then
    git mv "$f" "Archive/$f" 2>/dev/null && moved=$((moved+1)) || failed=$((failed+1))
  fi
done

echo "منتقل شد: $moved"
echo "خطا: $failed"
