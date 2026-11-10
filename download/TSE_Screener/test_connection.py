"""
test_connection.py (نسخه ساده‌شده)
تست اتصال به TSETMC با ذخیره خودکار خروجی در فایل.

نحوه اجرا:
  python test_connection.py            # تست + ذخیره خروجی در فایل
  python test_connection.py --debug     # + ذخیره پاسخ خام TSETMC
  python test_connection.py --no-save   # بدون ذخیره فایل

پس از اجرا، فایل result.txt ساخته می‌شود که می‌توانید برایم بفرستید.
"""

import sys
import json
import argparse
import io
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

from early_warning import MarketDataCollector, MarketSnapshot


def load_config() -> dict:
    cfg_path = ROOT / "config" / "warning_thresholds.json"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="TSETMC Connection Test")
    parser.add_argument("--ins-code", default="4674107287748763521",
                        help="TSETMC instrument code")
    parser.add_argument("--symbol", default="دابور", help="Symbol name")
    parser.add_argument("--debug", action="store_true",
                        help="Save raw TSETMC responses")
    parser.add_argument("--no-save", action="store_true",
                        help="Don't save output to file")
    args = parser.parse_args()

    # ذخیره همه printها در یک buffer
    output_buffer = io.StringIO()

    def log(msg=""):
        print(msg)
        output_buffer.write(str(msg) + "\n")

    log("=" * 70)
    log("  TSETMC Connection Test")
    log("=" * 70)
    log()
    log(f"Symbol:     {args.symbol}")
    log(f"Ins Code:   {args.ins_code}")
    log(f"Time:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log()

    config = load_config()
    collector = MarketDataCollector(config)

    if args.debug:
        collector.enable_debug(ROOT / "data" / "raw_responses")
        log("Debug mode: raw responses saved to data/raw_responses/")
        log()

    # مرحله ۱: دریافت داده روز جاری
    log("─" * 70)
    log("1) Fetching intraday data (instinfo)")
    log("─" * 70)

    try:
        inst = collector.fetch_intraday(args.ins_code)
    except Exception as e:
        log(f"ERROR during fetch: {e}")
        inst = None

    if inst is None:
        log("FAILED: No data received from TSETMC")
        log()
        log("Possible causes:")
        log("  - Internet connection issue")
        log("  - TSETMC is blocking your IP")
        log("  - Wrong ins-code")
        log("  - API structure changed")
        log()
        log("Try these:")
        log("  1) Open http://www.tsetmc.com in your browser")
        log("  2) Run with --debug to save raw responses")
    else:
        log("SUCCESS: Response received")
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
        log()

        buy_rows = inst.get("buy_rows", [])
        sell_rows = inst.get("sell_rows", [])
        log(f"  buy_rows count:  {len(buy_rows)}")
        if buy_rows:
            for i, r in enumerate(buy_rows[:3], 1):
                log(f"    {i}: price={r['price']:,}  vol={r['volume']:,}  orders={r['order_count']}")
        log(f"  sell_rows count: {len(sell_rows)}")
        if sell_rows:
            for i, r in enumerate(sell_rows[:3], 1):
                log(f"    {i}: price={r['price']:,}  vol={r['volume']:,}  orders={r['order_count']}")
    log()

    # مرحله ۲: اطلاعات حقیقی/حقوقی
    log("─" * 70)
    log("2) Fetching client type data (real/legal)")
    log("─" * 70)

    try:
        ct = collector.fetch_clienttype(args.ins_code)
    except Exception as e:
        log(f"ERROR: {e}")
        ct = None

    if ct is None:
        log("FAILED: No clienttype data")
    else:
        log("SUCCESS")
        log(f"  real_buy_count:   {ct.get('real_buy_count', 0):,}")
        log(f"  real_sell_count:  {ct.get('real_sell_count', 0):,}")
        log(f"  real_buy_volume:  {ct.get('real_buy_volume', 0):,}")
        log(f"  real_sell_volume: {ct.get('real_sell_volume', 0):,}")
        log(f"  legal_buy_count:  {ct.get('legal_buy_count', 0):,}")
        log(f"  legal_sell_count: {ct.get('legal_sell_count', 0):,}")
    log()

    # مرحله ۳: معاملات اخیر
    log("─" * 70)
    log("3) Fetching recent trades")
    log("─" * 70)

    try:
        trades = collector.fetch_trades(args.ins_code)
    except Exception as e:
        log(f"ERROR: {e}")
        trades = []

    if not trades:
        log("No trades received")
    else:
        log(f"SUCCESS: {len(trades)} trades")
        for t in trades[:5]:
            log(f"  {t.trade_time} | {t.trade_price:,} x {t.trade_volume:,}")
    log()

    # مرحله ۴: ساخت نمونه کامل
    log("─" * 70)
    log("4) Building full MarketSnapshot")
    log("─" * 70)

    try:
        snap, _ = collector.collect(args.symbol, args.ins_code, fetch_trades=False)
    except Exception as e:
        log(f"ERROR: {e}")
        snap = None

    if snap is None:
        log("FAILED to build snapshot")
    else:
        log("Snapshot built")
        log(f"  data_status:    {snap.data_status}")
        if snap.fetch_error:
            log(f"  fetch_error:    {snap.fetch_error}")
        log(f"  market_phase:   {snap.market_phase}")
        log(f"  data_complete:  {snap.data_complete}")
        if snap.missing_fields:
            log(f"  missing_fields: {snap.missing_fields}")
        log(f"  last_price:     {snap.last_price:,}")
        log(f"  close_price:    {snap.close_price:,}")
        log(f"  buyer_power:    {snap.buyer_power:.2f}")
        log(f"  real_money_flow: {snap.real_money_flow:,.0f}")
    log()

    # خلاصه نهایی
    log("=" * 70)
    if snap and snap.last_price > 0:
        log("RESULT: All good! You can run run_live.py")
    elif snap and snap.last_price == 0:
        log("RESULT: Connection works but no price data received")
        log("  Check if market is open (Sat-Wed, 09:00-12:30 Tehran time)")
        log("  Or run with --debug and send me data/raw_responses/ files")
    else:
        log("RESULT: Connection failed - see errors above")
    log("=" * 70)
    log()

    # ذخیره خروجی در فایل
    if not args.no_save:
        log_path = ROOT / "data" / "test_connection_result.txt"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(output_buffer.getvalue())
        print()
        print(f"📁 Result saved to: {log_path}")
        print()
        print("=" * 70)
        print("📋 Please send me the content of this file:")
        print(f"   {log_path}")
        print("=" * 70)
        print()
        print("How to send:")
        print("  1) Open the file in Notepad")
        print("  2) Ctrl+A to select all")
        print("  3) Ctrl+C to copy")
        print("  4) Paste it in our chat")
        print()

    # مکث برای جلوگیری از بسته شدن پنجره
    print("=" * 70)
    print("Test completed. Window will stay open.")
    print("=" * 70)
    try:
        input("Press Enter to exit...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print()
        print(f"UNEXPECTED ERROR: {e}")
        print()
        import traceback
        traceback.print_exc()
        try:
            input("Press Enter to exit...")
        except:
            pass
