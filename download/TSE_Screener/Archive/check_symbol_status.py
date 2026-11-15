"""
check_symbol_status.py
بررسی وضعیت نماد در پیکربندی و بانک اطلاعاتی.

این اسکریپت نشان می‌دهد:
  ۱. نماد فعلی در فایل پیکربندی
  ۲. نمادهای ذخیره شده در بانک اطلاعاتی
  ۳. مسیر فایل‌های پیکربندی و بانک اطلاعاتی
  ۴. آخرین نمونه‌های بانک اطلاعاتی

نحوه اجرا:
  python check_symbol_status.py
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

print("=" * 70)
print("  TSE Early Warning - Symbol Status Check")
print("=" * 70)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"Script location: {ROOT}")
print()

# ۱. فایل پیکربندی
print("=" * 70)
print("PART 1: Configuration file")
print("=" * 70)
print()

cfg_path = ROOT / "config" / "warning_thresholds.json"
print(f"Path: {cfg_path}")
print(f"Exists: {cfg_path.exists()}")

if cfg_path.exists():
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        ts = cfg.get("test_symbol", {})
        print(f"  name:     {ts.get('name', 'N/A')}")
        print(f"  ticker:   {ts.get('ticker', 'N/A')}")
        print(f"  ins_code: {ts.get('ins_code', 'N/A')}")
        print(f"  base_price: {ts.get('base_price', 'N/A')}")
        print()
        print("Raw content:")
        print(json.dumps(cfg.get('test_symbol', {}), ensure_ascii=False, indent=2))
    except Exception as e:
        print(f"ERROR reading: {e}")
print()

# ۲. جستجوی همه فایل‌های پیکربندی در سیستم
print("=" * 70)
print("PART 2: All warning_thresholds.json files found")
print("=" * 70)
print()

found_configs = []
for p in ROOT.rglob("warning_thresholds.json"):
    found_configs.append(p)
    print(f"  {p}")
    try:
        with open(p, "r", encoding="utf-8") as f:
            c = json.load(f)
        ts = c.get("test_symbol", {})
        print(f"    name: {ts.get('name', 'N/A')}, ins_code: {ts.get('ins_code', 'N/A')}")
    except Exception as e:
        print(f"    ERROR: {e}")

if not found_configs:
    print("  No config files found!")
print()

# ۳. بانک اطلاعاتی
print("=" * 70)
print("PART 3: Database")
print("=" * 70)
print()

db_path = ROOT / "data" / "early_warning_live.sqlite"
print(f"Path: {db_path}")
print(f"Exists: {db_path.exists()}")

if db_path.exists():
    print(f"Size: {db_path.stat().st_size} bytes")
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()

        # تمام نمادهای موجود در بانک
        cur.execute("SELECT symbol, COUNT(*) as cnt, MAX(tehran_time) as last_time FROM snapshots GROUP BY symbol ORDER BY cnt DESC")
        rows = cur.fetchall()
        print()
        print("Symbols in database (group by symbol):")
        for sym, cnt, last_time in rows:
            print(f"  {sym}: {cnt} samples, last: {last_time}")
        print()

        # ۵ نمونه اخیر
        cur.execute("SELECT tehran_time, symbol, last_price, close_price FROM snapshots ORDER BY timestamp DESC LIMIT 5")
        print("Last 5 snapshots:")
        for r in cur.fetchall():
            print(f"  {r}")
        print()

        conn.close()
    except Exception as e:
        print(f"ERROR: {e}")
else:
    print("Database not found")
print()

# ۴. جستجوی همه فایل‌های SQLite
print("=" * 70)
print("PART 4: All SQLite databases found")
print("=" * 70)
print()

for p in ROOT.rglob("*.sqlite"):
    print(f"  {p} ({p.stat().st_size} bytes)")
print()

# ۵. خلاصه و تشخیص مشکل
print("=" * 70)
print("PART 5: Diagnosis")
print("=" * 70)
print()

if cfg_path.exists() and db_path.exists():
    cfg_symbol = cfg["test_symbol"]["name"]

    # آخرین نماد در بانک
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT symbol FROM snapshots ORDER BY timestamp DESC LIMIT 1")
        row = cur.fetchone()
        conn.close()

        if row:
            db_symbol = row[0]
            print(f"Config symbol: {cfg_symbol}")
            print(f"DB last symbol: {db_symbol}")

            if cfg_symbol == db_symbol:
                print()
                print("✓ Match - همه چیز درست است")
            else:
                print()
                print("⚠ MISMATCH!")
                print(f"  Config: {cfg_symbol}")
                print(f"  DB:     {db_symbol}")
                print()
                print("Possible reasons:")
                print("  1. Web dashboard updated a DIFFERENT config file")
                print("  2. run_live.py is reading a DIFFERENT config file")
                print("  3. Old data in DB from before symbol change")
                print()
                print("Solutions:")
                print("  - Delete old DB: del data\\early_warning_live.sqlite")
                print("  - Restart run_live.py")
                print("  - Check both files above have the same symbol")
    except Exception as e:
        print(f"ERROR: {e}")
print()

try:
    input("Press Enter to exit...")
except:
    pass
