"""
view_data.py
ابزار مشاهده رکوردهای جمع‌آوری‌شده در SQLite.

سه حالت نمایش:
  1. خلاصه آماری (summary)
  2. آخرین نمونه‌ها (recent)
  3. جستجو در زمان خاص (search)

نحوه اجرا:
  python view_data.py                    # نمایش خلاصه
  python view_data.py --recent 10        # 10 نمونه آخر
  python view_data.py --search 10:00     # نمونه‌های بعد از 10:00
  python view_data.py --trades           # نمایش معاملات اخیر
  python view_data.py --export csv        # خروجی CSV
"""

import argparse
import sqlite3
import csv
import sys
from pathlib import Path
from datetime import datetime

# تنظیم encoding برای نمایش فارسی در Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "early_warning_live.sqlite"


def print_separator(title):
    print("=" * 70)
    print(f"  {title}")
    print("=" * 70)


def show_summary(conn):
    """نمایش خلاصه آماری."""
    print_separator("📊 خلاصه پایگاه داده")
    cur = conn.cursor()

    # تعداد نمونه‌ها
    cur.execute("SELECT COUNT(*) FROM snapshots")
    total_snapshots = cur.fetchone()[0]
    print(f"\n📝 تعداد نمونه‌های ذخیره شده: {total_snapshots}")

    # تعداد معاملات
    cur.execute("SELECT COUNT(*) FROM trades")
    total_trades = cur.fetchone()[0]
    print(f"📈 تعداد معاملات ذخیره شده: {total_trades}")

    # تعداد metadata
    cur.execute("SELECT COUNT(*) FROM metadata")
    total_meta = cur.fetchone()[0]
    print(f"📋 تعداد رکوردهای metadata: {total_meta}")

    if total_snapshots == 0:
        print("\n⚠️ هنوز هیچ نمونه‌ای ذخیره نشده است.")
        return

    # بازه زمانی
    cur.execute("SELECT MIN(tehran_time), MAX(tehran_time) FROM snapshots")
    first_time, last_time = cur.fetchone()
    print(f"\n⏰ بازه زمانی:")
    print(f"   شروع: {first_time}")
    print(f"   پایان: {last_time}")

    # توزیع فاز بازار
    print(f"\n📍 توزیع فاز بازار:")
    cur.execute("""
        SELECT market_phase, COUNT(*) as cnt
        FROM snapshots
        GROUP BY market_phase
        ORDER BY cnt DESC
    """)
    for phase, cnt in cur.fetchall():
        phase_label = {
            "pre_open": "پیش‌گشایش",
            "continuous": "پیوسته",
            "halted": "متوقف",
            "suspended": "ممنوع",
            "closed": "بسته",
        }.get(phase, phase)
        print(f"   {phase_label}: {cnt} نمونه")

    # آخرین نمونه
    print(f"\n📌 آخرین نمونه:")
    cur.execute("""
        SELECT tehran_time, last_price, close_price, total_volume,
               real_buy_volume, real_sell_volume, buyer_power,
               real_money_flow, data_complete, missing_fields
        FROM snapshots
        ORDER BY timestamp DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    if row:
        (tehran_time, last_price, close_price, total_volume,
         real_buy_volume, real_sell_volume, buyer_power,
         real_money_flow, data_complete, missing_fields) = row

        print(f"   زمان:          {tehran_time}")
        print(f"   آخرین قیمت:   {last_price:,.0f}")
        print(f"   قیمت پایانی: {close_price:,.0f}")
        print(f"   حجم کل:       {total_volume:,}")
        print(f"   حجم خرید حقیقی: {real_buy_volume:,}")
        print(f"   حجم فروش حقیقی: {real_sell_volume:,}")
        print(f"   قدرت خریدار: {buyer_power:.2f}")
        if real_money_flow is not None:
            money_billion = real_money_flow / 1e9
            print(f"   ورود/خروج پول: {money_billion:+.2f} میلیارد تومان")
        print(f"   داده کامل:    {'بله' if data_complete else 'خیر'}")
        if missing_fields:
            print(f"   فیلدهای مفقود: {missing_fields}")

    # وضعیت داده‌های ناقص
    cur.execute("""
        SELECT COUNT(*) FROM snapshots
        WHERE data_complete = 0 OR data_status != 'ok'
    """)
    incomplete = cur.fetchone()[0]
    if incomplete > 0:
        print(f"\n⚠️ نمونه‌های ناقص: {incomplete}")

    # میانگین امتیازها در طول زمان (در صورت وجود)
    print(f"\n📊 خلاصه آخرین وضعیت بازار:")
    cur.execute("""
        SELECT
            AVG(buyer_power) as avg_bp,
            MIN(buyer_power) as min_bp,
            MAX(buyer_power) as max_bp
        FROM snapshots
        WHERE buyer_power > 0
    """)
    avg_bp, min_bp, max_bp = cur.fetchone()
    if avg_bp:
        print(f"   میانگین قدرت خریدار: {avg_bp:.2f}")
        print(f"   کمینه: {min_bp:.2f}")
        print(f"   بیشینه: {max_bp:.2f}")


def show_recent(conn, count=10):
    """نمایش آخرین نمونه‌ها."""
    print_separator(f"🕐 آخرین {count} نمونه")
    cur = conn.cursor()

    cur.execute(f"""
        SELECT tehran_time, market_phase, last_price, close_price,
               best_buy_volume, best_sell_volume, buyer_power,
               real_money_flow, data_complete
        FROM snapshots
        ORDER BY timestamp DESC
        LIMIT {int(count)}
    """)

    rows = cur.fetchall()
    if not rows:
        print("\n⚠️ هیچ نمونه‌ای ذخیره نشده است.")
        return

    # هدر
    print(f"\n{'ردیف':<5} {'زمان':<10} {'فاز':<12} {'قیمت':<10} {'قدرت':<8} {'پول':<15} {'کامل':<5}")
    print("-" * 70)

    for i, row in enumerate(rows, 1):
        tehran_time, phase, last_price, close_price,
        bb_vol, bs_vol, buyer_power, money_flow, complete = row

        phase_label = {
            "pre_open": "پیش‌گشایش",
            "continuous": "پیوسته",
        }.get(phase, phase)

        money_str = ""
        if money_flow:
            if abs(money_flow) >= 1e9:
                money_str = f"{money_flow/1e9:+.1f}B"
            else:
                money_str = f"{money_flow/1e6:+.0f}M"

        print(f"{i:<5} {tehran_time:<10} {phase_label:<12} "
              f"{last_price or 0:<10.0f} {buyer_power or 0:<8.2f} "
              f"{money_str:<15} {'✓' if complete else '✗':<5}")


def show_trades(conn, count=20):
    """نمایش آخرین معاملات."""
    print_separator(f"📈 آخرین {count} معامله")
    cur = conn.cursor()

    cur.execute(f"""
        SELECT trade_time, trade_price, trade_volume, trade_id, aggressor_side
        FROM trades
        ORDER BY trade_id_row DESC
        LIMIT {int(count)}
    """)

    rows = cur.fetchall()
    if not rows:
        print("\n⚠️ هیچ معامله‌ای ذخیره نشده است.")
        return

    print(f"\n{'ردیف':<5} {'زمان':<10} {'قیمت':<10} {'حجم':<10} {'شناسه':<15} {'سمت':<10}")
    print("-" * 70)

    for i, (t_time, t_price, t_vol, t_id, side) in enumerate(rows, 1):
        side_label = {"buy": "خرید", "sell": "فروش"}.get(side, "نامشخص")
        print(f"{i:<5} {t_time:<10} {t_price:<10.0f} {t_vol:<10,} "
              f"{(t_id or '-'):<15} {side_label:<10}")


def search_by_time(conn, time_str):
    """جستجوی نمونه‌ها از یک زمان خاص."""
    print_separator(f"🔍 نمونه‌های بعد از {time_str}")
    cur = conn.cursor()

    cur.execute("""
        SELECT tehran_time, market_phase, last_price, buyer_power,
               real_money_flow, data_complete
        FROM snapshots
        WHERE tehran_time >= ?
        ORDER BY tehran_time ASC
    """, (time_str,))

    rows = cur.fetchall()
    if not rows:
        print(f"\n⚠️ هیچ نمونه‌ای بعد از {time_str} یافت نشد.")
        return

    print(f"\nتعداد: {len(rows)} نمونه")
    print(f"\n{'زمان':<10} {'فاز':<12} {'قیمت':<10} {'قدرت':<8} {'پول':<15} {'کامل':<5}")
    print("-" * 70)

    for row in rows:
        tehran_time, phase, last_price, buyer_power, money_flow, complete = row
        phase_label = {"pre_open": "پیش‌گشایش", "continuous": "پیوسته"}.get(phase, phase)
        money_str = ""
        if money_flow:
            if abs(money_flow) >= 1e9:
                money_str = f"{money_flow/1e9:+.1f}B"
            else:
                money_str = f"{money_flow/1e6:+.0f}M"
        print(f"{tehran_time:<10} {phase_label:<12} {last_price or 0:<10.0f} "
              f"{buyer_power or 0:<8.2f} {money_str:<15} {'✓' if complete else '✗':<5}")


def export_csv(conn, table="snapshots", output_path="data/export_view.csv"):
    """خروجی CSV."""
    print_separator(f"💾 خروجی CSV از جدول {table}")
    cur = conn.cursor()

    cur.execute(f"SELECT * FROM {table} ORDER BY timestamp ASC")
    rows = cur.fetchall()

    if not rows:
        print(f"\n⚠️ جدول {table} خالی است.")
        return

    output = ROOT / output_path
    output.parent.mkdir(parents=True, exist_ok=True)

    with open(output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([d[0] for d in cur.description])
        for r in rows:
            writer.writerow(r)

    print(f"\n✓ {len(rows)} ردیف به CSV خروجی شد:")
    print(f"  {output}")


def show_metadata(conn):
    """نمایش metadata."""
    print_separator("📋 Metadata")
    cur = conn.cursor()

    cur.execute("""
        SELECT date_jalali, symbol, open_time, close_time,
               total_snapshots, total_trades, market_phase_summary,
               data_source
        FROM metadata
        ORDER BY meta_id DESC
    """)

    rows = cur.fetchall()
    if not rows:
        print("\n⚠️ هیچ metadata‌ای ذخیره نشده است.")
        return

    for row in rows:
        (date_j, symbol, open_t, close_t, total_s, total_t,
         phase_sum, source) = row
        print(f"\n  نماد: {symbol} | تاریخ: {date_j}")
        print(f"  بازه: {open_t} تا {close_t}")
        print(f"  نمونه‌ها: {total_s} | معاملات: {total_t}")
        print(f"  فازها: {phase_sum}")
        print(f"  منبع: {source}")
        print("-" * 50)


def main():
    parser = argparse.ArgumentParser(
        description="مشاهده رکوردهای جمع‌آوری‌شده TSE Early Warning"
    )
    parser.add_argument("--recent", type=int, default=0,
                        help="تعداد نمونه اخیر برای نمایش (مثلا 10)")
    parser.add_argument("--search", type=str, default="",
                        help="جستجوی نمونه‌های بعد از زمان (مثلا 10:00)")
    parser.add_argument("--trades", action="store_true",
                        help="نمایش آخرین معاملات")
    parser.add_argument("--metadata", action="store_true",
                        help="نمایش metadata")
    parser.add_argument("--export", type=str, default="",
                        help="خروجی CSV (snapshots یا trades)")
    parser.add_argument("--db", type=str, default=str(DB_PATH),
                        help="مسیر فایل SQLite")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"❌ فایل پایگاه داده یافت نشد: {db_path}")
        print("   ابتدا run_live.py را اجرا کنید تا داده جمع شود.")
        return

    conn = sqlite3.connect(str(db_path))

    if args.recent > 0:
        show_recent(conn, args.recent)
    elif args.search:
        search_by_time(conn, args.search)
    elif args.trades:
        show_trades(conn)
    elif args.metadata:
        show_metadata(conn)
    elif args.export:
        export_csv(conn, args.export)
    else:
        show_summary(conn)

    conn.close()


if __name__ == "__main__":
    main()
