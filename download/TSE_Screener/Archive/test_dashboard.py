"""
test_dashboard.py
اسکریپت تشخیصی برای داشبورد وب.

این اسکریپت:
  ۱. بررسی می‌کند آیا Flask نصب است
  ۲. بررسی می‌کند آیا پایگاه داده وجود دارد
  ۳. بررسی می‌کند آیا نماده‌ای در پایگاه داده هست
  ۴. سرور وب را تست می‌کند
  ۵. همه چیز را در یک فایل گزارش ذخیره می‌کند

نحوه اجرا:
  python test_dashboard.py
"""

import sys
import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime

# تنظیم encoding
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
    log("  TSE Early Warning - Dashboard Diagnostic")
    log("=" * 70)
    log()
    log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Working dir: {Path.cwd()}")
    log(f"Script dir: {ROOT}")
    log()

    # ========== بخش ۱: بررسی Flask ==========
    log("=" * 70)
    log("PART 1: Check Flask installation")
    log("=" * 70)
    log()

    try:
        import flask
        log(f"✓ Flask is installed")
        log(f"  Version: {flask.__version__}")
        log(f"  Location: {flask.__file__}")
    except ImportError as e:
        log(f"✗ Flask is NOT installed")
        log(f"  Error: {e}")
        log()
        log("To install:")
        log("  pip install flask")
        log()
        save_report()
        return

    log()

    # ========== بخش ۲: بررسی پایگاه داده ==========
    log("=" * 70)
    log("PART 2: Check database")
    log("=" * 70)
    log()

    db_path = ROOT / "data" / "early_warning_live.sqlite"
    log(f"Database path: {db_path}")
    log(f"Database exists: {db_path.exists()}")

    if db_path.exists():
        log(f"  Size: {db_path.stat().st_size} bytes")
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            log(f"  Tables: {tables}")

            if 'snapshots' in tables:
                cur.execute("SELECT COUNT(*) FROM snapshots")
                count = cur.fetchone()[0]
                log(f"  Snapshots count: {count}")

                if count > 0:
                    cur.execute("SELECT tehran_time, market_phase, last_price, close_price FROM snapshots ORDER BY timestamp DESC LIMIT 3")
                    log("  Recent snapshots:")
                    for r in cur.fetchall():
                        log(f"    {r}")
                else:
                    log("  ⚠ No snapshots in database!")
                    log("  Run: python run_live.py")
            else:
                log("  ⚠ 'snapshots' table not found!")

            conn.close()
        except Exception as e:
            log(f"  ERROR accessing database: {e}")
    else:
        log("  ⚠ Database file not found!")
        log("  Run: python run_live.py --symbol ریتون --ins-code 14035144070182412")
    log()

    # ========== بخش ۳: بررسی web_dashboard.py ==========
    log("=" * 70)
    log("PART 3: Check web_dashboard.py")
    log("=" * 70)
    log()

    dashboard_path = ROOT / "web_dashboard.py"
    log(f"Dashboard path: {dashboard_path}")
    log(f"Exists: {dashboard_path.exists()}")

    if dashboard_path.exists():
        with open(dashboard_path, 'r', encoding='utf-8') as f:
            content = f.read()
        log(f"  Size: {len(content)} chars")
        log(f"  Has Flask import: {'from flask' in content}")
        log(f"  Has v2.0 (TSETMC style): {'TSETMC Style' in content or 'chart.js' in content.lower()}")
        log(f"  Has 'DASHBOARD_HTML': {'DASHBOARD_HTML' in content}")
    log()

    # ========== بخش ۴: تست import ==========
    log("=" * 70)
    log("PART 4: Test import")
    log("=" * 70)
    log()

    try:
        sys.path.insert(0, str(ROOT))
        import web_dashboard
        log("✓ web_dashboard imported successfully")
        log(f"  DB_PATH: {web_dashboard.DB_PATH}")
        log(f"  App: {web_dashboard.app}")
    except Exception as e:
        log(f"✗ ERROR importing web_dashboard: {e}")
        import traceback
        log(traceback.format_exc())
        save_report()
        return
    log()

    # ========== بخش ۵: تست سرور ==========
    log("=" * 70)
    log("PART 5: Test server startup")
    log("=" * 70)
    log()

    try:
        import threading
        import time
        import urllib.request

        # شروع سرور در thread جدا
        def run_server():
            web_dashboard.app.run(host='127.0.0.1', port=8052, debug=False, use_reloader=False)

        log("Starting server on port 8052...")
        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        time.sleep(3)

        # تست HTTP request
        log("Testing HTTP request...")
        try:
            req = urllib.request.Request("http://127.0.0.1:8052/", headers={"User-Agent": "test"})
            with urllib.request.urlopen(req, timeout=5) as r:
                status = r.status
                content = r.read(500).decode('utf-8', errors='replace')
                log(f"✓ HTTP request succeeded")
                log(f"  Status: {status}")
                log(f"  Response length: {len(content)} chars")
                log(f"  First 200 chars: {content[:200]}")
        except Exception as e:
            log(f"✗ HTTP request failed: {e}")

        # تست API
        try:
            req = urllib.request.Request("http://127.0.0.1:8052/api/data", headers={"User-Agent": "test"})
            with urllib.request.urlopen(req, timeout=5) as r:
                content = r.read().decode('utf-8', errors='replace')
                log(f"✓ /api/data request succeeded")
                log(f"  Response length: {len(content)} chars")
                log(f"  First 300 chars: {content[:300]}")
        except Exception as e:
            log(f"✗ /api/data request failed: {e}")

    except Exception as e:
        log(f"✗ Server test failed: {e}")
        import traceback
        log(traceback.format_exc())
    log()

    # ========== خلاصه ==========
    log("=" * 70)
    log("SUMMARY")
    log("=" * 70)
    log()

    log("Next steps:")
    log("  1. Make sure run_live.py is running (collects data)")
    log("  2. Run: python web_dashboard.py")
    log("  3. Open browser: http://localhost:8050")
    log()

    save_report()


def save_report():
    report_path = ROOT / "data" / "test_dashboard_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))
    log()
    log(f"Report saved to: {report_path}")
    try:
        os.startfile(str(report_path))
    except:
        pass
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
        save_report()
