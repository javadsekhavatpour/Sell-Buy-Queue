#!/usr/bin/env python3
"""تست ضریب کاهش سقف — سناریوی دابور.

شبیه‌سازی: قیمت در سقف روزانه + معاملات sell-triggered (real_sell >> real_buy).
انتظار: sell_flow/sell_breadth/sell_ticket با ضریب کاهش اعمال شوند،
امتیاز کل فشار فروش به‌جای ۲۰ ~۶ باشد.
"""
import sys
PROJ = "/home/z/my-project/download/TSE_Screener"
sys.path.insert(0, PROJ)

from early_warning.data_collector import MarketSnapshot, BestLimitRow
from early_warning.sell_pressure import SellPressureDetector
from web_dashboard_live import load_cfg


def make_snap(price, real_buy_val, real_sell_val, real_buy_cnt, real_sell_cnt,
              min_p, max_p, ts="10:00:00"):
    """ساخت MarketSnapshot با پارامترهای مشخص."""
    return MarketSnapshot(
        timestamp=f"2026-11-18T{ts}", tehran_time=ts, date_jalali="1405-08-28",
        symbol="دابور", last_price=price, close_price=price,
        yesterday_price=int(min_p + (max_p - min_p) * 0.5),
        max_allowed_price=max_p, min_allowed_price=min_p,
        real_buy_value=real_buy_val, real_sell_value=real_sell_val,
        real_buy_count=real_buy_cnt, real_sell_count=real_sell_cnt,
        real_buy_volume=int(real_buy_val / price), real_sell_volume=int(real_sell_val / price),
        buy_rows=[BestLimitRow(price=price-10, volume=500000, order_count=100)],
        sell_rows=[BestLimitRow(price=price+10, volume=10000, order_count=5)],
        data_complete=True,
    )


def run_scenario(label, price, min_p, max_p, rbv, rsv, rbc, rsc):
    """اجرای موتور فروش روی یک جفت snapshot (prev + current)."""
    cfg = load_cfg()
    eng = SellPressureDetector(cfg)
    # prev: مقادیر تجمعی صفر (شروع بازه)
    prev = make_snap(price, 0, 0, 0, 0, min_p, max_p, "09:59:30")
    curr = make_snap(price, rbv, rsv, rbc, rsc, min_p, max_p, "10:00:00")
    res = eng.evaluate(curr, prev)
    price_pos = (price - min_p) / (max_p - min_p) if max_p > min_p else 0
    print(f"\n=== {label} ===")
    print(f"  قیمت={price:,} | کف={min_p:,} سقف={max_p:,} | موقعیت={price_pos:.2f} ({'سقف' if price_pos>=0.95 else 'میانه' if price_pos<=0.5 else 'بالا'})")
    print(f"  معاملات: خرید(value={rbv:,} cnt={rbc}) فروش(value={rsv:,} cnt={rsc})")
    print(f"  امتیاز کل فشار فروش: {res.total_score}")
    for f in res.factors:
        if f.name in ("sell_flow", "sell_breadth", "sell_ticket"):
            print(f"    {f.name:14} score={f.score:6.2f} (max={f.max_points}) | {f.description}")
    return res.total_score


def main():
    # سناریوی دابور: قیمت در سقف، معاملات sell-triggered (فروش >> خرید)
    # سقف = 13000، کف = 11000 (محدوده ±~9%)
    MIN_P = 11000
    MAX_P = 13000

    # ۱) قیمت در سقف (13000) + معاملات فروش‌محور
    score_ceiling = run_scenario(
        "قیمت در سقف (سناریوی دابور)",
        price=13000, min_p=MIN_P, max_p=MAX_P,
        rbv=500_000_000, rsv=2_000_000_000,  # فروش ۴× خرید
        rbc=50, rsc=200,  # فروشنده ۴× خریدار
    )

    # ۲) قیمت در میانه (12000) + همان معاملات فروش‌محور
    score_mid = run_scenario(
        "قیمت در میانه (کنترل)",
        price=12000, min_p=MIN_P, max_p=MAX_P,
        rbv=500_000_000, rsv=2_000_000_000,
        rbc=50, rsc=200,
    )

    # ۳) قیمت در کف (11000) + همان معاملات
    score_floor = run_scenario(
        "قیمت در کف",
        price=11000, min_p=MIN_P, max_p=MAX_P,
        rbv=500_000_000, rsv=2_000_000_000,
        rbc=50, rsc=200,
    )

    print("\n" + "=" * 60)
    print("خلاصه:")
    print(f"  سقف (13000): sell_pressure = {score_ceiling}")
    print(f"  میانه (12000): sell_pressure = {score_mid}")
    print(f"  کف (11000): sell_pressure = {score_floor}")

    # تست کلیدی: در سقف، امتیاز باید کمتر از میانه باشد (چون معاملات
    # sell-triggered در سقف = سودگیری، نه فشار فروش واقعی)
    ok = score_ceiling < score_mid
    print(f"\n  سقف < میانه (کاهش فشار فروش در سقف): {'✓' if ok else '✗'}")
    print(f"  کاهش: {((score_mid - score_ceiling) / score_mid * 100):.0f}٪" if score_mid > 0 else "")

    if ok:
        print("\n  ✅ fix کار می‌کند — فشار فروش در سقف کاهش می‌یابد.")
        return 0
    else:
        print("\n  ❌ fix کار نمی‌کند.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
