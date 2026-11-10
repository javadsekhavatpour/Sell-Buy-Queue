"""
test_riton.py
تست اتصال به نماد ریتون و نمایش داده‌های زنده.

این اسکریپت:
  ۱. با کد ریتون (14035144070182412) به TSETMC وصل می‌شود
  ۲. داده‌های قیمت، حجم، سفارش‌ها را دریافت می‌کند
  ۳. پاسخ خام TSETMC را ذخیره می‌کند
  ۴. گزارش کامل می‌سازد

نحوه اجرا:
  python test_riton.py
"""

import sys
import json
import os
from pathlib import Path
from datetime import datetime

# تنظیم encoding برای Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from early_warning import MarketDataCollector

# ذخیره گزارش
output_log = []

def log(msg=""):
    print(msg)
    output_log.append(str(msg))


def main():
    log("=" * 70)
    log("  Test ریتون Connection - LIVE DATA")
    log("=" * 70)
    log()
    log(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"Symbol: ریتون")
    log(f"Ins Code: 14035144070182412")
    log()

    config = json.loads((ROOT / "config" / "warning_thresholds.json").read_text(encoding='utf-8'))
    collector = MarketDataCollector(config)
    collector.enable_debug(ROOT / "data" / "raw_responses")

    # ========== تست ۱: دریافت داده قیمت ==========
    log("=" * 70)
    log("TEST 1: Fetch intraday data (price + volume + orders)")
    log("=" * 70)
    log()

    try:
        inst = collector.fetch_intraday("14035144070182412")
        if inst is None:
            log("FAILED: No data received")
        else:
            log("SUCCESS!")
            log()
            log("Parsed values:")
            log(f"  last_price:      {inst.get('last_price', 0):,}")
            log(f"  close_price:     {inst.get('close_price', 0):,}")
            log(f"  yesterday_price: {inst.get('yesterday_price', 0):,}")
            log(f"  daily_high:      {inst.get('daily_high', 0):,}")
            log(f"  daily_low:       {inst.get('daily_low', 0):,}")
            log(f"  trade_volume:    {inst.get('trade_volume', 0):,}")
            log(f"  trade_value:     {inst.get('trade_value', 0):,}")
            log(f"  trade_count:     {inst.get('trade_count', 0):,}")
            log(f"  buy_rows count:  {len(inst.get('buy_rows', []))}")
            log(f"  sell_rows count: {len(inst.get('sell_rows', []))}")
            log()
            if inst.get('buy_rows'):
                log("Buy rows (اولین ۳ ردیف):")
                for i, r in enumerate(inst['buy_rows'][:3], 1):
                    log(f"  {i}: price={r['price']:,}  vol={r['volume']:,}  orders={r['order_count']}")
            if inst.get('sell_rows'):
                log("Sell rows (اولین ۳ ردیف):")
                for i, r in enumerate(inst['sell_rows'][:3], 1):
                    log(f"  {i}: price={r['price']:,}  vol={r['volume']:,}  orders={r['order_count']}")
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())
    log()

    # ========== تست ۲: اطلاعات حقیقی/حقوقی ==========
    log("=" * 70)
    log("TEST 2: Fetch client type (real/legal)")
    log("=" * 70)
    log()

    try:
        ct = collector.fetch_clienttype("14035144070182412")
        if ct is None:
            log("FAILED: No data")
        else:
            log("SUCCESS!")
            log(f"  real_buy_count:   {ct.get('real_buy_count', 0):,}")
            log(f"  real_sell_count:  {ct.get('real_sell_count', 0):,}")
            log(f"  real_buy_volume:  {ct.get('real_buy_volume', 0):,}")
            log(f"  real_sell_volume: {ct.get('real_sell_volume', 0):,}")
            log(f"  legal_buy_count:  {ct.get('legal_buy_count', 0):,}")
            log(f"  legal_sell_count: {ct.get('legal_sell_count', 0):,}")
    except Exception as e:
        log(f"ERROR: {e}")
    log()

    # ========== تست ۳: معاملات اخیر ==========
    log("=" * 70)
    log("TEST 3: Fetch recent trades")
    log("=" * 70)
    log()

    try:
        trades = collector.fetch_trades("14035144070182412")
        if not trades:
            log("No trades received")
        else:
            log(f"SUCCESS: {len(trades)} trades")
            log("First 5 trades:")
            for t in trades[:5]:
                log(f"  {t.trade_time} | {t.trade_price:,} x {t.trade_volume:,}")
    except Exception as e:
        log(f"ERROR: {e}")
    log()

    # ========== تست ۴: ساخت snapshot کامل ==========
    log("=" * 70)
    log("TEST 4: Build full MarketSnapshot")
    log("=" * 70)
    log()

    try:
        snap, _ = collector.collect("ریتون", "14035144070182412", fetch_trades=False)
        if snap is None:
            log("FAILED")
        else:
            log("SUCCESS!")
            log(f"  data_status:    {snap.data_status}")
            log(f"  market_phase:   {snap.market_phase}")
            log(f"  data_complete:  {snap.data_complete}")
            log(f"  last_price:     {snap.last_price:,}")
            log(f"  close_price:    {snap.close_price:,}")
            log(f"  buyer_power:    {snap.buyer_power:.2f}")
            if snap.missing_fields:
                log(f"  missing_fields: {snap.missing_fields}")
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        log(traceback.format_exc())
    log()

    # ========== خلاصه ==========
    log("=" * 70)
    log("SUMMARY")
    log("=" * 70)
    log()

    if snap and snap.last_price > 0:
        log("✅ SUCCESS! All systems working!")
        log()
        log("You can now run:")
        log("  python run_live.py --symbol ریتون --ins-code 14035144070182412")
    elif snap:
        log("⚠️  Connection works but some data missing")
        log("  Check raw responses in data/raw_responses/")
    else:
        log("❌ Connection failed")
    log()

    # ذخیره گزارش
    report_path = ROOT / "data" / "test_riton_result.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(output_log))
    log(f"Report saved to: {report_path}")
    log(f"Raw responses in: {ROOT / 'data' / 'raw_responses'}")

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
        report_path = ROOT / "data" / "test_riton_result.txt"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(output_log))
        try:
            input("Press Enter to exit...")
        except:
            pass
