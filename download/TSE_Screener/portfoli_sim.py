#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfoli_sim.py — شبیه‌سازی داشبورد «portfoli» (مشابه /sim داشبورد اصلی)

همهٔ نمونه‌های ذخیره‌شدهٔ بانک خام در یک روز معاملاتی را به‌ترتیب زمان بازپخش
می‌کند؛ در هر گام همان محاسبات لایو (export_portfoli_data._compute_row) روی
دادهٔ همان لحظه اجرا می‌شود و خروجی در دو فایل کنار پروژه ذخیره می‌شود:

    sim_report_portfoli_{تاریخ}.xlsx   ← شیت‌های «داشبورد» (سری زمانی) /
                                          «خلاصه روز» / «روند ۵ دقیقه»
    portfoli_replay_{تاریخ}.json       ← بازپخش گام‌به‌گام در portfoli.html

اجرا (فایل را کنار export_portfoli_data.py در ریشهٔ پروژه بگذارید):
    python portfoli_sim.py                      ← آخرین روزِ موجود در بانک‌ها
    python portfoli_sim.py --date 1405/08/30
    python portfoli_sim.py --interval 5 --max-frames 500

بازپخش در مرورگر: فایل replay JSON را کنار portfoli.html بگذارید و
«📥 بارگذاری داده» را بزنید (یا ?replay=نام فایل.json در آدرس صفحه).
"""
from __future__ import annotations

import argparse
import bisect
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import export_portfoli_data as exp  # noqa: E402  (هم‌پوشان با این فایل)

# ستون‌های سری زمانی شیت «داشبورد» — پیش‌فرضِ جدول (شامل روند جریان پول و واژگونی)
# + کف/سقف مجاز + بقیهٔ ستون‌های روند
SIM_COLS = ["date_jalali", "fetch_hms", "symbol"] + [
    c for c in exp.DEFAULT_VISIBLE
    if c not in ("date_jalali", "fetch_hms", "symbol")
] + ["min_allowed_price", "max_allowed_price",
     "flow_ratio_recent_avg", "trend_power_session", "trend_power_recent",
     # مبنای نسبت‌های چندروزهٔ جریان پول — برای ردیابی اشکال در جدول
     # (ارزش خرید/فروش حقیقی و ورود/خروج پول در DEFAULT_VISIBLE خودشان هستند)
     "mf_ratio_30d_pct", "flow5_avg_abs", "flow30_avg_abs"]


def collect_day(root: Path, date: str | None) -> tuple[str, dict, dict]:
    """همهٔ نمونه‌های خام یک روز، به تفکیک نماد. خروجی: (تاریخ، {نماد: سطرها}، {نماد: پیکربندی})."""
    cfg = json.loads((root / "config" / "symbols.json").read_text(encoding="utf-8"))["symbols"]
    per_symbol: dict[str, list] = {}
    per_cfg: dict[str, dict] = {}
    dates = set()
    for s in cfg:
        if s.get("ok", True) is False and not s.get("ins_code"):
            continue
        name = s["name"]
        db = root / "data" / "raw" / f"raw_{name}.sqlite"
        if not db.exists():
            continue
        con = sqlite3.connect(str(db))
        con.row_factory = sqlite3.Row
        try:
            if date is None:
                row = con.execute("SELECT MAX(date_jalali) FROM raw_snapshots").fetchone()
                date = row[0]
            rows = con.execute(
                "SELECT * FROM raw_snapshots WHERE date_jalali = ? ORDER BY id", (date,)
            ).fetchall()
        finally:
            con.close()
        if rows:
            per_symbol[name] = rows
            per_cfg[name] = s
            dates.add(rows[0]["date_jalali"])
    return date, per_symbol, per_cfg


def build_frames(per_symbol: dict, per_cfg: dict, root: Path, date: str,
                 max_frames: int, trend_window: int = exp.TREND_WINDOW_DEFAULT) -> list[dict]:
    """بازپخش: در هر تیکِ زمان، آخرین نمونهٔ هر نماد تا آن لحظه با فرمول‌های لایو محاسبه می‌شود.

    سری نسبت جریان پول/قدرت خریدار هر نماد به‌صورت در حال اجرا جمع می‌شود تا روند
    «از ابتدای جلسه» و «N نمونهٔ اخیر» در هر فریم همان لحظه محاسبه شود.
    """
    ticks = sorted({str(r["fetch_hms"]) for rows in per_symbol.values() for r in rows})
    if len(ticks) > max_frames:  # نمونه‌برداری زمانی برای نگه‌داشتن حجم خروجی
        step = -(-len(ticks) // max_frames)
        ticks = ticks[::step]
    hms_idx = {n: ([str(r["fetch_hms"]) for r in rows], rows)
               for n, rows in per_symbol.items()}
    last_used = {n: -1 for n in hms_idx}      # اندیس نمونه‌ای که تا فریم قبل مصرف شده
    run_flow: dict[str, list] = {n: [] for n in hms_idx}
    run_power: dict[str, list] = {n: [] for n in hms_idx}

    frames = []
    for t in ticks:
        rows_out = []
        for name, (hms_list, rows) in hms_idx.items():
            i = bisect.bisect_right(hms_list, t) - 1
            if i < 0:
                continue  # هنوز اولین نمونهٔ این نماد نرسیده
            # نمونه‌های جدیدِ رسیده از فریم قبل → به سری‌های روند اضافه شود
            for k in range(last_used[name] + 1, i + 1):
                r = rows[k]
                rbv, rsv = r["buy_i_volume"] or 0, r["sell_i_volume"] or 0
                rbc, rsc = r["buy_counti"] or 0, r["sell_counti"] or 0
                tval = r["trade_value"] or 0
                px = float(r["pc"] or 0) or float(r["pl"] or 0)
                if tval and px:
                    run_flow[name].append((rbv - rsv) * px / tval * 100)
                if rbc and rsc:
                    run_power[name].append((rbv / rbc) / (rsv / rsc))
            last_used[name] = i
            row = {en: None for en in exp.ALL_FIELDS}
            exp._compute_row(row, name, per_cfg[name], root,
                             root / "data" / "raw" / f"raw_{name}.sqlite", rows[i])
            row.update(exp._trends_from_series(run_flow[name], run_power[name], trend_window))
            row["_meta"] = None  # در بازپخش لازم نیست — حجم فایل کم می‌شود
            rows_out.append(row)
        frames.append({"t": t, "rows": rows_out})
    return frames


def _pct_of_session(values: list[float]) -> tuple[float | None, float | None]:
    vals = [v for v in values if v is not None]
    return (min(vals), max(vals)) if vals else (None, None)


def xlsx_report(frames: list[dict], date: str, per_symbol: dict, out: Path,
                interval: int) -> None:
    """گزارش اکسل سه‌شیت: سری زمانی + خلاصهٔ روز + روند ۵ دقیقه‌ای.

    openpyxl فقط همین‌جا import می‌شود تا build_frames بدون آن هم برای
    بازپخش وبِ portfoli_server.py کار کند.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    thin = Side(style="thin", color="B0BDD4")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    hfont = Font(name="B Nazanin", size=10, bold=True, color="FFFFFF")
    hfill = PatternFill("solid", fgColor="4A72C4")
    cfont = Font(name="B Nazanin", size=9)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)

    def header(ws, titles, ens=None):
        """سطر ۱: هدر فارسی — سطر ۲: نام فیلد بانک خام (یا «—» برای محاسبه‌ای).

        ens = نام انگلیسی ستون‌ها برای نگاشت به exp.FIELD_SOURCES؛ اگر داده
        نشود سطر دوم نوشته نمی‌شود (شیت‌های خلاصه/روند ستون‌های ترکیبی دارند).
        """
        ws.sheet_view.rightToLeft = True
        for j, h in enumerate(titles, 1):
            c = ws.cell(row=1, column=j, value=h)
            c.font, c.fill, c.alignment, c.border = hfont, hfill, center, border
        if ens:
            sfill = PatternFill("solid", fgColor="D9E2F3")
            sfont = Font(name="B Nazanin", size=8, italic=True, color="1F3864")
            for j, en in enumerate(ens, 1):
                src = (exp.FIELD_SOURCES.get(en) or (en, ""))[0]
                c = ws.cell(row=2, column=j, value=src)
                c.font, c.fill, c.alignment, c.border = sfont, sfill, center, border
        for j in range(1, len(titles) + 1):
            ws.column_dimensions[get_column_letter(j)].width = 13
        ws.freeze_panes = f"A{3 if ens else 2}"

    def help_sheet(wb):
        """شیت «راهنما» — منبع بانک/API و فرمول مختصر هر ستون داشبورد."""
        ws = wb.create_sheet("راهنما")
        ws.sheet_view.rightToLeft = True
        hf = Font(name="B Nazanin", size=10, bold=True, color="FFFFFF")
        hfl = PatternFill("solid", fgColor="4A72C4")
        bf = Font(name="B Nazanin", size=9)
        for j, h in enumerate(["هدر فارسی", "نام فیلد بانک/API", "نوع", "توضیح/فرمول"], 1):
            c = ws.cell(row=1, column=j, value=h)
            c.font, c.fill, c.alignment, c.border = hf, hfl, center, border
        fa_map = {en: fa for _, cols in exp.GROUPS for fa, en in cols}
        r = 2
        for en, (src, desc) in exp.FIELD_SOURCES.items():
            kind = "محاسبه‌ای" if src.startswith("calc_") else "مستقیم از بانک"
            for j, v in enumerate([fa_map.get(en, en), src, kind, desc], 1):
                c = ws.cell(row=r, column=j, value=v)
                c.font, c.alignment, c.border = bf, center, border
            r += 1
        for j, w in enumerate([34, 22, 14, 74], 1):
            ws.column_dimensions[get_column_letter(j)].width = w
        ws.freeze_panes = "A2"

    # ── شیت ۱: داشبورد (سری زمانی همهٔ نمادها) ──
    ws = wb.active
    ws.title = "داشبورد"
    # هدر فارسی از GROUPS
    fa_map = {}
    for t, cols in exp.GROUPS:
        for fa, en in cols:
            fa_map[en] = fa
    titles = [fa_map.get(c, c) for c in SIM_COLS]
    header(ws, titles, SIM_COLS)
    r = 3
    for f in frames:
        for row in f["rows"]:
            for j, en in enumerate(SIM_COLS, 1):
                c = ws.cell(row=r, column=j, value=row.get(en))
                c.font, c.alignment, c.border = cfont, center, border
            r += 1

    # ── شیت ۲: خلاصهٔ روز ──
    ws2 = wb.create_sheet("خلاصه روز")
    sum_titles = ["نماد", "اولین نمونه", "آخرین نمونه", "تعداد نمونه",
                  "آخرین قیمت", "٪ نوسان پایانی", "جریان پول پایانی",
                  "کمینه جریان پول", "بیشینه جریان پول",
                  "میانگین قدرت خریدار", "نسبت خریدار به فروشنده",
                  "امتیاز واکنش قیمت", "از نظر مبلغ خرید یا فروش",
                  "واژگونی‌های جلسه", "واژگونی پایانی"]
    header(ws2, sum_titles, [11, 10, 10, 9, 10, 11, 14, 14, 14, 13, 14, 12, 14, 11, 20])
    last_by_sym = {}
    for f in frames:
        for row in f["rows"]:
            last_by_sym[row["symbol"]] = row  # آخرین فریم = آخرین وضعیت
    all_by_sym: dict[str, list] = {}
    for f in frames:
        for row in f["rows"]:
            all_by_sym.setdefault(row["symbol"], []).append(row)
    r = 2
    for sym, rows_all in sorted(all_by_sym.items()):
        last = last_by_sym[sym]
        flows = [x.get("real_money_flow") for x in rows_all]
        flo, fhi = _pct_of_session(flows)
        pows = [x.get("buyer_power") for x in rows_all]
        pows_ok = [p for p in pows if p is not None]
        cells = [sym, rows_all[0]["fetch_hms"], last["fetch_hms"], len(rows_all),
                 last["last_price"], last["pct_close"], last["real_money_flow"],
                 flo, fhi,
                 round(sum(pows_ok) / len(pows_ok), 2) if pows_ok else None,
                 last["buyer_seller_count_ratio"], last["price_reaction_score"],
                 last["buy_sell_amount_side"],
                 sum(1 for x in rows_all if x.get("trend_divergence_kind")),
                 last.get("trend_divergence")]
        for j, v in enumerate(cells, 1):
            c = ws2.cell(row=r, column=j, value=v)
            c.font, c.alignment, c.border = cfont, center, border
        r += 1

    # ── شیت ۳: روند ۵ دقیقه‌ای ──
    ws3 = wb.create_sheet(f"روند {interval} دقیقه")
    header(ws3, ["نماد", "زمان بازه", "٪ نوسان لحظه‌ای (میانگین)",
                 "نسبت جریان پول ٪ (میانگین)", "قدرت خریدار (میانگین)",
                 "ارزش معاملات بازه (میلیون ریال)"],
           [11, 10, 16, 16, 14, 18])
    by_sym_bucket: dict[str, dict[str, list]] = {}
    tv_seq: dict[str, list[tuple[str, float]]] = {}
    for f in frames:
        for row in f["rows"]:
            tv_seq.setdefault(row["symbol"], []).append((f["t"], row.get("total_value") or 0))
            b = _bucket(f["t"], interval)
            by_sym_bucket.setdefault(row["symbol"], {}).setdefault(b, []).append(row)
    r = 3
    for sym in sorted(by_sym_bucket):
        for b in sorted(by_sym_bucket[sym]):
            rows_b = by_sym_bucket[sym][b]
            def avg(key):
                xs = [x.get(key) for x in rows_b if x.get(key) is not None]
                return round(sum(xs) / len(xs), 2) if xs else None
            tv_end = max((tv for t, tv in tv_seq[sym] if _bucket(t, interval) == b), default=0)
            tv_prev = max((tv for t, tv in tv_seq[sym] if _bucket(t, interval) < b), default=0)
            delta = max(tv_end - tv_prev, 0)
            for j, v in enumerate([sym, b, avg("pct_last"), avg("money_flow_ratio_pct"),
                                   avg("buyer_power"), round(delta / 1e6, 1)], 1):
                c = ws3.cell(row=r, column=j, value=v)
                c.font, c.alignment, c.border = cfont, center, border
            r += 1
    help_sheet(wb)
    wb.save(out)


def _bucket(hms: str, interval: int) -> str:
    hh, mm, _ = str(hms).split(":")
    total = int(hh) * 60 + int(mm)
    total -= total % interval
    return f"{total // 60:02d}:{total % 60:02d}"


def main() -> None:
    ap = argparse.ArgumentParser(description="شبیه‌سازی داشبورد portfoli از بانک خام")
    ap.add_argument("--date", default=None, help="تاریخ شمسی مثل 1405/08/30 (پیش‌فرض: آخرین روز)")
    ap.add_argument("--interval", type=int, default=5, help="طول بازهٔ روند (دقیقه؛ پیش‌فرض ۵)")
    ap.add_argument("--max-frames", type=int, default=500,
                    help="سقف تعداد فریم بازپخش (نمونه‌برداری زمانی بالاتر از این)")
    ap.add_argument("--trend-window", type=int, default=exp.TREND_WINDOW_DEFAULT,
                    help="طول پنجرهٔ روند اخیر به تعداد نمونه (پیش‌فرض ۲۰؛ بازهٔ پیشنهادی ۱۰-۳۰)")
    ap.add_argument("--root", default=None, help="ریشهٔ پروژه (پیش‌فرض: پوشهٔ همین اسکریپت)")
    args = ap.parse_args()

    root = Path(args.root) if args.root else HERE
    date, per_symbol, per_cfg = collect_day(root, args.date)
    if not per_symbol:
        print("✗ هیچ نمونه‌ای در بانک‌های خام پیدا نشد")
        return
    n_samples = sum(len(v) for v in per_symbol.values())
    print(f"بازپخش روز {date} — {len(per_symbol)} نماد، {n_samples} نمونهٔ خام…")

    frames = build_frames(per_symbol, per_cfg, root, date, args.max_frames,
                          args.trend_window)
    print(f"✓ {len(frames)} فریم شبیه‌سازی ساخته شد (اولین {frames[0]['t']}، آخرین {frames[-1]['t']})")

    safe_date = date.replace("/", "-")
    rep_json = root / f"portfoli_replay_{safe_date}.json"
    rep_json.write_text(json.dumps({
        "version": 1, "replay": True, "date": date,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "frames": frames,
        "groups": [{"title": t, "cols": [{"fa": fa, "en": en} for fa, en in cols]}
                   for t, cols in exp.GROUPS],
        "default_visible": exp.DEFAULT_VISIBLE,
    }, ensure_ascii=False), encoding="utf-8")
    print(f"✓ {rep_json} — بازپخش در مرورگر با «📥 بارگذاری داده» یا ?replay={rep_json.name}")

    out_xlsx = root / f"sim_report_portfoli_{safe_date}.xlsx"
    xlsx_report(frames, date, per_symbol, out_xlsx, args.interval)
    print(f"✓ {out_xlsx} — شیت‌های داشبورد / خلاصه روز / روند {args.interval} دقیقه")


if __name__ == "__main__":
    main()
