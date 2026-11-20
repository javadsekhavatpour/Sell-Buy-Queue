"""
storage.py
لایه ذخیره‌سازی داده‌ها با SQLite.

سه جدول مطابق درخواست کاربر:
  1. snapshots  - هر ۶۰ ثانیه یک ردیف از وضعیت کامل تابلو (گروه A تا D و F)
  2. trades     - معاملات انجام‌شده (گروه E)
  3. metadata   - مشخصات نماد، ساعت شروع/پایان، واحد قیمت، منبع، خطاها

قواعد:
  - هیچ نمونه قبلی بازنویسی نمی‌شود
  - فیلدهای مفقود به‌صورت NULL ذخیره می‌شوند، نه صفر
  - پنج ردیف سفارش به‌صورت ستون‌های جداگانه ذخیره می‌شوند (bid_price_1..5)
"""

from __future__ import annotations

import sqlite3
import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Iterator

from .data_collector import MarketSnapshot, Trade


# ---------------------------------------------------------------------------
# ساختار جداول
# ---------------------------------------------------------------------------

SCHEMA_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jalali      TEXT,
    timestamp        TEXT NOT NULL,
    tehran_time      TEXT,
    symbol           TEXT NOT NULL,
    ins_code         TEXT,
    market_phase     TEXT,
    symbol_status    TEXT,
    source_update_time TEXT,
    data_status      TEXT,
    fetch_error      TEXT,

    -- گروه A - قیمت‌ها
    last_price       REAL,
    close_price      REAL,
    open_price       REAL,
    yesterday_price  REAL,
    daily_high       REAL,
    daily_low        REAL,
    min_allowed_price REAL,
    max_allowed_price REAL,

    -- گروه B - بهترین قیمت و تعداد سفارش (مجموع)
    best_buy_price   REAL,
    best_buy_volume  INTEGER,
    best_sell_price  REAL,
    best_sell_volume INTEGER,
    buy_order_count  INTEGER,
    sell_order_count INTEGER,

    -- پنج ردیف خرید
    bid_price_1 INTEGER, bid_volume_1 INTEGER, bid_count_1 INTEGER,
    bid_price_2 INTEGER, bid_volume_2 INTEGER, bid_count_2 INTEGER,
    bid_price_3 INTEGER, bid_volume_3 INTEGER, bid_count_3 INTEGER,
    bid_price_4 INTEGER, bid_volume_4 INTEGER, bid_count_4 INTEGER,
    bid_price_5 INTEGER, bid_volume_5 INTEGER, bid_count_5 INTEGER,

    -- پنج ردیف فروش
    ask_price_1 INTEGER, ask_volume_1 INTEGER, ask_count_1 INTEGER,
    ask_price_2 INTEGER, ask_volume_2 INTEGER, ask_count_2 INTEGER,
    ask_price_3 INTEGER, ask_volume_3 INTEGER, ask_count_3 INTEGER,
    ask_price_4 INTEGER, ask_volume_4 INTEGER, ask_count_4 INTEGER,
    ask_price_5 INTEGER, ask_volume_5 INTEGER, ask_count_5 INTEGER,

    -- گروه C - حجم/ارزش/تعداد معاملات
    total_volume     INTEGER,
    total_value      REAL,
    total_trade_count INTEGER,
    base_volume      INTEGER,
    interval_volume  INTEGER,
    interval_value   REAL,
    interval_trade_count INTEGER,

    -- گروه D - حقیقی/حقوقی
    real_buy_count   INTEGER,
    real_buy_volume  INTEGER,
    real_buy_value   REAL,
    real_sell_count  INTEGER,
    real_sell_volume INTEGER,
    real_sell_value  REAL,
    legal_buy_count  INTEGER,
    legal_buy_volume INTEGER,
    legal_buy_value  REAL,
    legal_sell_count INTEGER,
    legal_sell_volume INTEGER,
    legal_sell_value REAL,
    interval_real_buy_volume  INTEGER,
    interval_real_sell_volume INTEGER,
    interval_real_buy_value   REAL,
    interval_real_sell_value  REAL,
    interval_real_buy_count   INTEGER,
    interval_real_sell_count  INTEGER,
    interval_buy_volume       INTEGER,
    interval_sell_volume      INTEGER,
    clienttype_stale          INTEGER,
    clienttype_lag_shares     INTEGER,
    last_fresh_real_frac      REAL,

    -- شاخص‌های مشتق
    buyer_power      REAL,
    per_capita_buy_real   REAL,
    per_capita_sell_real  REAL,
    real_money_flow  REAL,
    real_money_flow_ratio REAL,

    -- کیفیت داده
    data_complete    INTEGER,
    missing_fields   TEXT
);
CREATE INDEX IF NOT EXISTS idx_snap_symbol_time ON snapshots(symbol, tehran_time);
CREATE INDEX IF NOT EXISTS idx_snap_phase ON snapshots(market_phase);
"""

SCHEMA_TRADES = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id_row   INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol         TEXT NOT NULL,
    snapshot_time  TEXT,
    trade_time     TEXT NOT NULL,
    trade_price    REAL NOT NULL,
    trade_volume   INTEGER NOT NULL,
    trade_id       TEXT,
    aggressor_side TEXT
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_time ON trades(symbol, trade_time);
"""

SCHEMA_METADATA = """
CREATE TABLE IF NOT EXISTS metadata (
    meta_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jalali    TEXT,
    symbol         TEXT NOT NULL,
    ins_code       TEXT,
    open_time      TEXT,
    close_time     TEXT,
    last_update    TEXT,
    price_unit     TEXT,
    volume_unit    TEXT,
    data_source    TEXT,
    market_phase_summary TEXT,
    total_snapshots INTEGER,
    total_trades   INTEGER,
    notes          TEXT
);
"""

# جدول پارامترهای ثابت روز — یک ردیف برای هر نماد در هر روز.
# این مقادیر در طول روز تغییر نمی‌کنند و نباید در هر snapshot تکرار شوند:
#   yesterday_price, min_allowed_price, max_allowed_price, first_price
SCHEMA_DAILY_PARAMS = """
CREATE TABLE IF NOT EXISTS daily_params (
    param_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jalali       TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    ins_code          TEXT,
    category          TEXT,
    range_percent     REAL,
    yesterday_price   REAL,
    first_price       REAL,
    min_allowed_price REAL,
    max_allowed_price REAL,
    computed_at       TEXT,
    UNIQUE(date_jalali, symbol)
);
"""

# ---------------------------------------------------------------------------
# جدول score_history — ذخیره raw_value هر شاخص برای نرمال‌سازی تطبیقی (Phase 2)
#   صدک ۹۰ مقادیر خام تاریخی → آستانه پویا به‌جای full_at ثابت
# ---------------------------------------------------------------------------
SCHEMA_SCORE_HISTORY = """
CREATE TABLE IF NOT EXISTS score_history (
    sh_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT NOT NULL,
    date_jalali  TEXT,
    symbol       TEXT NOT NULL,
    engine       TEXT NOT NULL,
    factor       TEXT NOT NULL,
    raw_value    REAL,
    normalized   REAL,
    score        REAL,
    status       TEXT
);
CREATE INDEX IF NOT EXISTS idx_sh_sym_fact_time
    ON score_history(symbol, factor, timestamp DESC);
"""

# ---------------------------------------------------------------------------
# بانک پردازش‌شده (derived) — لایهٔ مشتقِ ماندگار، جدا از snapshots خام.
#   - derived_samples : یک ردیف به ازای هر نمونهٔ ۳۰ثانیه‌ایِ enriched
#   - aggregate_5min  : تجمیعی ۵دقیقه‌ای
#   - aggregate_15min : تجمیعی ۱۵دقیقه‌ای
# داشبوردهای /live، /db، /sim از این جداول می‌خوانند؛ snapshots خام دست‌نخورده می‌ماند.
# ---------------------------------------------------------------------------
SCHEMA_DERIVED_SAMPLES = """
CREATE TABLE IF NOT EXISTS derived_samples (
    derived_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id      INTEGER,
    date_jalali      TEXT,
    timestamp        TEXT NOT NULL,
    tehran_time      TEXT,
    symbol           TEXT NOT NULL,

    -- حجم ۵ ردیف عرضه/تقاضا
    ask5_volume      REAL,
    bid5_volume      REAL,

    -- مقادیر بازه‌ای + رفع مغایرت (از معاملات واقعی)
    interval_volume           INTEGER,
    interval_value            REAL,
    interval_trade_count      INTEGER,
    interval_real_buy_volume  INTEGER,
    interval_real_sell_volume INTEGER,
    interval_real_buy_value   REAL,
    interval_real_sell_value  REAL,
    interval_real_buy_count   INTEGER,
    interval_real_sell_count  INTEGER,
    interval_buy_volume       INTEGER,
    interval_sell_volume      INTEGER,
    clienttype_stale          INTEGER,
    clienttype_lag_shares     INTEGER,
    last_fresh_real_frac      REAL,

    -- شاخص‌های مشتقِ نمایشی
    buyer_power               REAL,
    per_capita_buy_real       REAL,
    per_capita_sell_real      REAL,
    real_money_flow           REAL,
    real_money_flow_ratio     REAL,

    -- کیفیت داده
    data_complete             INTEGER,
    missing_fields            TEXT,

    -- امتیاز/آلارم تجمعی در این لحظه (اختیاری، از موتور)
    composite_score           REAL,
    alarm_level               TEXT,

    computed_at               TEXT
);
CREATE INDEX IF NOT EXISTS idx_ds_sym_time ON derived_samples(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_ds_sym_date_time
    ON derived_samples(symbol, date_jalali, tehran_time);
"""

# ستون‌های تجمیعی مشترک برای aggregate_5min و aggregate_15min.
_AGG_COLUMNS_BODY = """
    date_jalali       TEXT,
    symbol            TEXT NOT NULL,
    bucket_start      TEXT NOT NULL,
    bucket_end        TEXT,
    sample_count      INTEGER,

    open_price        REAL,
    close_price       REAL,
    high_price        REAL,
    low_price         REAL,

    total_volume      INTEGER,
    total_value       REAL,
    total_trade_count INTEGER,

    interval_real_buy_volume  INTEGER,
    interval_real_sell_volume INTEGER,
    interval_real_buy_value   REAL,
    interval_real_sell_value  REAL,

    buyer_power               REAL,
    real_money_flow           REAL,
    real_money_flow_ratio     REAL,
    per_capita_buy_real       REAL,
    per_capita_sell_real      REAL,

    composite_score           REAL,
    alarm_level               TEXT,

    computed_at               TEXT,
    UNIQUE(symbol, date_jalali, bucket_start)
"""

SCHEMA_AGGREGATE_5MIN = f"""
CREATE TABLE IF NOT EXISTS aggregate_5min (
    agg_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    {_AGG_COLUMNS_BODY}
);
CREATE INDEX IF NOT EXISTS idx_agg5_sym_date ON aggregate_5min(symbol, date_jalali, bucket_start);
"""

SCHEMA_AGGREGATE_15MIN = f"""
CREATE TABLE IF NOT EXISTS aggregate_15min (
    agg_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    {_AGG_COLUMNS_BODY}
);
CREATE INDEX IF NOT EXISTS idx_agg15_sym_date ON aggregate_15min(symbol, date_jalali, bucket_start);
"""

# ستون‌های جدول snapshots به ترتیب (به جز autoincrement)
# توجه: yesterday_price، min_allowed_price، max_allowed_price همچنان در
# snapshots ذخیره می‌شوند (با مقدار ثابت از fixed_price_range / daily_params)
# تا داشبورد مستقیماً از snapshots بخواند. مقدار منبع مرجع در جدول
# daily_params (یک ردیف در روز) است و در snapshots تکرار می‌شود.
SNAPSHOT_COLUMNS = [
    "date_jalali", "timestamp", "tehran_time", "symbol", "ins_code",
    "market_phase", "symbol_status", "source_update_time", "data_status", "fetch_error",
    "last_price", "close_price", "open_price", "yesterday_price",
    "daily_high", "daily_low", "min_allowed_price", "max_allowed_price",
    "best_buy_price", "best_buy_volume", "best_sell_price", "best_sell_volume",
    "buy_order_count", "sell_order_count",
    "bid_price_1", "bid_volume_1", "bid_count_1",
    "bid_price_2", "bid_volume_2", "bid_count_2",
    "bid_price_3", "bid_volume_3", "bid_count_3",
    "bid_price_4", "bid_volume_4", "bid_count_4",
    "bid_price_5", "bid_volume_5", "bid_count_5",
    "ask_price_1", "ask_volume_1", "ask_count_1",
    "ask_price_2", "ask_volume_2", "ask_count_2",
    "ask_price_3", "ask_volume_3", "ask_count_3",
    "ask_price_4", "ask_volume_4", "ask_count_4",
    "ask_price_5", "ask_volume_5", "ask_count_5",
    "total_volume", "total_value", "total_trade_count", "base_volume",
    "interval_volume", "interval_value", "interval_trade_count",
    "real_buy_count", "real_buy_volume", "real_buy_value",
    "real_sell_count", "real_sell_volume", "real_sell_value",
    "legal_buy_count", "legal_buy_volume", "legal_buy_value",
    "legal_sell_count", "legal_sell_volume", "legal_sell_value",
    "interval_real_buy_volume", "interval_real_sell_volume",
    "interval_real_buy_value", "interval_real_sell_value",
    "interval_real_buy_count", "interval_real_sell_count",
    "interval_buy_volume", "interval_sell_volume",
    "clienttype_stale", "clienttype_lag_shares", "last_fresh_real_frac",
    "buyer_power", "per_capita_buy_real", "per_capita_sell_real",
    "real_money_flow", "real_money_flow_ratio",
    "data_complete", "missing_fields",
]

# ستون‌های جدول daily_params (پارامترهای ثابت روز — یک ردیف در روز)
DAILY_PARAMS_COLUMNS = [
    "date_jalali", "symbol", "ins_code", "category", "range_percent",
    "yesterday_price", "first_price", "min_allowed_price", "max_allowed_price",
    "computed_at",
]

TRADE_COLUMNS = [
    "symbol", "snapshot_time", "trade_time",
    "trade_price", "trade_volume", "trade_id", "aggressor_side",
]

# ستون‌های جدول score_history (نرمال‌سازی تطبیقی Phase 2)
SCORE_HISTORY_COLUMNS = [
    "timestamp", "date_jalali", "symbol", "engine", "factor",
    "raw_value", "normalized", "score", "status",
]

# ستون‌های جدول derived_samples (بانک پردازش‌شده — یک ردیف به ازای هر نمونهٔ ۳۰ث)
DERIVED_SAMPLES_COLUMNS = [
    "snapshot_id", "date_jalali", "timestamp", "tehran_time", "symbol",
    "ask5_volume", "bid5_volume",
    "interval_volume", "interval_value", "interval_trade_count",
    "interval_real_buy_volume", "interval_real_sell_volume",
    "interval_real_buy_value", "interval_real_sell_value",
    "interval_real_buy_count", "interval_real_sell_count",
    "interval_buy_volume", "interval_sell_volume",
    "clienttype_stale", "clienttype_lag_shares", "last_fresh_real_frac",
    "buyer_power", "per_capita_buy_real", "per_capita_sell_real",
    "real_money_flow", "real_money_flow_ratio",
    "data_complete", "missing_fields",
    "composite_score", "alarm_level", "computed_at",
]

# ستون‌های مشترک جدول‌های تجمیعی (aggregate_5min / aggregate_15min)
AGGREGATE_COLUMNS = [
    "date_jalali", "symbol", "bucket_start", "bucket_end", "sample_count",
    "open_price", "close_price", "high_price", "low_price",
    "total_volume", "total_value", "total_trade_count",
    "interval_real_buy_volume", "interval_real_sell_volume",
    "interval_real_buy_value", "interval_real_sell_value",
    "buyer_power", "real_money_flow", "real_money_flow_ratio",
    "per_capita_buy_real", "per_capita_sell_real",
    "composite_score", "alarm_level", "computed_at",
]


# ---------------------------------------------------------------------------
# کلاس اصلی ذخیره‌سازی
# ---------------------------------------------------------------------------

class MarketDataStorage:
    """ذخیره‌ساز SQLite برای نمونه‌های تابلو و معاملات."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: امکان استفاده از یک connection در چند thread
        # (داشبورد: _publish در thread پس‌زمینه + _cumulative_scores در thread اصلی)
        # timeout=30: اگر یک thread در حال نوشتن باشد، دیگری تا ۳۰ ثانیه صبر می‌کند
        self.conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """ایجاد جداول اگر وجود ندارند."""
        cur = self.conn.cursor()
        cur.executescript(SCHEMA_SNAPSHOTS)
        cur.executescript(SCHEMA_TRADES)
        cur.executescript(SCHEMA_METADATA)
        cur.executescript(SCHEMA_DAILY_PARAMS)
        cur.executescript(SCHEMA_SCORE_HISTORY)
        cur.executescript(SCHEMA_DERIVED_SAMPLES)
        cur.executescript(SCHEMA_AGGREGATE_5MIN)
        cur.executescript(SCHEMA_AGGREGATE_15MIN)
        self._migrate_snapshots()
        self.conn.commit()

    def _migrate_snapshots(self):
        """افزودن ستون‌های جدید به جدول snapshots موجود (پچ رفع مغایرت‌ها).
        CREATE TABLE IF NOT EXISTS ستون‌های جدید را روی DB قدیمی اضافه نمی‌کند،
        پس با ALTER TABLE به‌صورت idempotent مهاجرت می‌کنیم."""
        cur = self.conn.cursor()
        try:
            cur.execute("PRAGMA table_info(snapshots)")
            existing = {row[1] for row in cur.fetchall()}
        except Exception:
            existing = set()
        new_cols = {
            "interval_real_buy_value": "REAL",
            "interval_real_sell_value": "REAL",
            "interval_real_buy_count": "INTEGER",
            "interval_real_sell_count": "INTEGER",
            "interval_buy_volume": "INTEGER",
            "interval_sell_volume": "INTEGER",
            "clienttype_stale": "INTEGER",
            "clienttype_lag_shares": "INTEGER",
            "last_fresh_real_frac": "REAL",
        }
        for col, typ in new_cols.items():
            if col not in existing:
                try:
                    cur.execute(f"ALTER TABLE snapshots ADD COLUMN {col} {typ}")
                except Exception:
                    pass  # ستون از قبل وجود دارد یا DB فقط‌خواندنی

    # ----- snapshots -----
    def insert_snapshot(self, snap: MarketSnapshot) -> int:
        """درج یک نمونه و بازگشت شناسه ردیف."""
        flat = snap.to_flat_dict()
        # تبدیل data_complete به 0/1
        flat["data_complete"] = 1 if flat.get("data_complete") else 0

        # ساخت placeholders و column list
        cols = SNAPSHOT_COLUMNS
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        values = [flat.get(c) for c in cols]

        sql = f"INSERT INTO snapshots ({col_names}) VALUES ({placeholders})"
        cur = self.conn.cursor()
        cur.execute(sql, values)
        self.conn.commit()
        return cur.lastrowid

    def insert_snapshots_bulk(self, snapshots: List[MarketSnapshot]) -> int:
        """درج گروهی نمونه‌ها - سریع‌تر از درج تکی."""
        rows = []
        for snap in snapshots:
            flat = snap.to_flat_dict()
            flat["data_complete"] = 1 if flat.get("data_complete") else 0
            rows.append([flat.get(c) for c in SNAPSHOT_COLUMNS])

        cols = SNAPSHOT_COLUMNS
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        sql = f"INSERT INTO snapshots ({col_names}) VALUES ({placeholders})"

        cur = self.conn.cursor()
        cur.executemany(sql, rows)
        self.conn.commit()
        return cur.rowcount

    # ----- trades -----
    def insert_trades(self, trades: List[Trade], symbol: str,
                      snapshot_time: str = "") -> int:
        """درج لیست معاملات."""
        if not trades:
            return 0
        rows = [
            [symbol, snapshot_time, tr.trade_time, tr.trade_price,
             tr.trade_volume, tr.trade_id, tr.aggressor_side]
            for tr in trades
        ]
        placeholders = ", ".join(["?"] * len(TRADE_COLUMNS))
        col_names = ", ".join(TRADE_COLUMNS)
        sql = f"INSERT INTO trades ({col_names}) VALUES ({placeholders})"

        cur = self.conn.cursor()
        cur.executemany(sql, rows)
        self.conn.commit()
        return cur.rowcount

    # ----- metadata -----
    def insert_metadata(self, meta: Dict) -> int:
        """درج یک رکورد metadata."""
        cols = list(meta.keys())
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        sql = f"INSERT INTO metadata ({col_names}) VALUES ({placeholders})"
        cur = self.conn.cursor()
        cur.execute(sql, [meta[c] for c in cols])
        self.conn.commit()
        return cur.lastrowid

    # ----- daily_params (پارامترهای ثابت روز — یک ردیف در روز) -----
    def upsert_daily_params(self, params: Dict) -> int:
        """
        درج یا به‌روزرسانی پارامترهای ثابت روز برای یک نماد.

        اگر رکوردی برای (date_jalali, symbol) وجود داشته باشد، به‌روزرسانی
        می‌شود؛ در غیر این صورت ردیف جدید درج می‌شود. این تابع یک بار در
        ابتدای اجرای run_live.py فراخوانی می‌شود.
        """
        cur = self.conn.cursor()
        date_jalali = params.get("date_jalali", "")
        symbol = params.get("symbol", "")
        cur.execute(
            "SELECT param_id FROM daily_params WHERE date_jalali=? AND symbol=?",
            (date_jalali, symbol),
        )
        existing = cur.fetchone()
        cols = DAILY_PARAMS_COLUMNS
        values = [params.get(c) for c in cols]
        if existing:
            param_id = existing[0]
            set_clause = ", ".join(f"{c}=?" for c in cols)
            cur.execute(f"UPDATE daily_params SET {set_clause} WHERE param_id=?",
                        (*values, param_id))
        else:
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            cur.execute(f"INSERT INTO daily_params ({col_names}) VALUES ({placeholders})",
                        values)
            param_id = cur.lastrowid
        self.conn.commit()
        return param_id

    def get_daily_params(self, symbol: str,
                         date_jalali: Optional[str] = None) -> Optional[Dict]:
        """
        خواندن پارامترهای ثابت روز برای یک نماد.

        اگر date_jalali داده نشود، آخرین رکورد نماد برمی‌گردد.
        """
        cur = self.conn.cursor()
        if date_jalali:
            cur.execute(
                "SELECT * FROM daily_params WHERE symbol=? AND date_jalali=? "
                "ORDER BY param_id DESC LIMIT 1",
                (symbol, date_jalali),
            )
        else:
            cur.execute(
                "SELECT * FROM daily_params WHERE symbol=? ORDER BY param_id DESC LIMIT 1",
                (symbol,),
            )
        row = cur.fetchone()
        return dict(row) if row else None

    # ----- پرس‌وجو -----
    def get_snapshots_for_symbol(self, symbol: str,
                                  limit: Optional[int] = None) -> List[Dict]:
        """بازگشت تمام نمونه‌های یک نماد به ترتیب زمانی."""
        sql = "SELECT * FROM snapshots WHERE symbol = ? ORDER BY timestamp ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur = self.conn.cursor()
        cur.execute(sql, (symbol,))
        return [dict(r) for r in cur.fetchall()]

    def get_last_snapshot(self, symbol: str) -> Optional[Dict]:
        """آخرین نمونه نماد."""
        sql = "SELECT * FROM snapshots WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1"
        cur = self.conn.cursor()
        cur.execute(sql, (symbol,))
        row = cur.fetchone()
        return dict(row) if row else None

    def get_trades_for_symbol(self, symbol: str,
                                start_time: str = "",
                                end_time: str = "") -> List[Dict]:
        """بازگشت معاملات یک نماد در یک بازه زمانی."""
        sql = "SELECT * FROM trades WHERE symbol = ?"
        params = [symbol]
        if start_time:
            sql += " AND trade_time >= ?"
            params.append(start_time)
        if end_time:
            sql += " AND trade_time <= ?"
            params.append(end_time)
        sql += " ORDER BY trade_time ASC"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def count_snapshots(self, symbol: Optional[str] = None) -> int:
        """تعداد نمونه‌های ذخیره‌شده."""
        if symbol:
            sql = "SELECT COUNT(*) FROM snapshots WHERE symbol = ?"
            cur = self.conn.cursor()
            cur.execute(sql, (symbol,))
        else:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM snapshots")
        return cur.fetchone()[0]

    def count_trades(self, symbol: Optional[str] = None) -> int:
        """تعداد معاملات ذخیره‌شده."""
        if symbol:
            sql = "SELECT COUNT(*) FROM trades WHERE symbol = ?"
            cur = self.conn.cursor()
            cur.execute(sql, (symbol,))
        else:
            cur = self.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM trades")
        return cur.fetchone()[0]

    # ----- خروجی -----
    def export_snapshots_csv(self, output_path: Path,
                              symbol: Optional[str] = None) -> Path:
        """خروجی CSV از snapshots."""
        import csv
        if symbol:
            sql = "SELECT * FROM snapshots WHERE symbol = ? ORDER BY timestamp ASC"
            params = (symbol,)
        else:
            sql = "SELECT * FROM snapshots ORDER BY timestamp ASC"
            params = ()

        cur = self.conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([d[0] for d in cur.description])
            for r in rows:
                writer.writerow(r)
        return output_path

    def export_trades_csv(self, output_path: Path,
                           symbol: Optional[str] = None) -> Path:
        """خروجی CSV از trades."""
        import csv
        if symbol:
            sql = "SELECT * FROM trades WHERE symbol = ? ORDER BY trade_time ASC"
            params = (symbol,)
        else:
            sql = "SELECT * FROM trades ORDER BY trade_time ASC"
            params = ()

        cur = self.conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([d[0] for d in cur.description])
            for r in rows:
                writer.writerow(r)
        return output_path

    # ----- score_history (نرمال‌سازی تطبیقی Phase 2) -----
    def insert_score_history(self, row: Dict) -> int:
        """
        درج یک مشاهده شاخص در score_history.

        row شامل: timestamp, date_jalali, symbol, engine, factor,
                  raw_value, normalized, score, status
        """
        cols = SCORE_HISTORY_COLUMNS
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        values = [row.get(c) for c in cols]
        sql = f"INSERT INTO score_history ({col_names}) VALUES ({placeholders})"
        cur = self.conn.cursor()
        cur.execute(sql, values)
        self.conn.commit()
        return cur.lastrowid

    def insert_score_history_bulk(self, rows: List[Dict]) -> int:
        """درج گروهی مشاهدات شاخص — سریع‌تر از درج تکی."""
        if not rows:
            return 0
        cols = SCORE_HISTORY_COLUMNS
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        sql = f"INSERT INTO score_history ({col_names}) VALUES ({placeholders})"
        cur = self.conn.cursor()
        cur.executemany(sql, [[r.get(c) for c in cols] for r in rows])
        self.conn.commit()
        return cur.rowcount

    def get_score_history_raw(self, symbol: str, factor: str,
                              limit: int = 500) -> List[float]:
        """
        بازگشت مقادیر خام اخیر یک شاخص برای نرمال‌سازی تطبیقی.

        فقط مقادیر غیر NULL و غیر NaN برمی‌گرداند (مرتب بر اساس زمان نزولی).
        """
        sql = ("SELECT raw_value FROM score_history "
               "WHERE symbol = ? AND factor = ? AND raw_value IS NOT NULL "
               "ORDER BY timestamp DESC LIMIT ?")
        cur = self.conn.cursor()
        cur.execute(sql, (symbol, factor, int(limit)))
        out = []
        for r in cur.fetchall():
            v = r[0]
            if v is not None and v == v:  # NaN check
                out.append(float(v))
        return out

    def get_score_history_count(self, symbol: str, factor: str) -> int:
        """تعداد مشاهدات یک شاخص — برای بررسی min_samples."""
        sql = ("SELECT COUNT(*) FROM score_history "
               "WHERE symbol = ? AND factor = ? AND raw_value IS NOT NULL")
        cur = self.conn.cursor()
        cur.execute(sql, (symbol, factor))
        return int(cur.fetchone()[0])

    # ----- بانک پردازش‌شده (derived_samples / aggregate_5min / aggregate_15min) -----
    def insert_derived_sample(self, snap: MarketSnapshot,
                              snapshot_id: Optional[int] = None,
                              composite_score: Optional[float] = None,
                              alarm_level: Optional[str] = None) -> int:
        """درج یک ردیف enriched برای یک نمونهٔ ۳۰ثانیه‌ای.

        snap باید از پیش enrich شده باشد (فیلدهای مشتق پر شده).
        snapshot_id شناسهٔ ردیف خام متناظر در snapshots است.
        """
        flat = snap.to_flat_dict()
        flat["data_complete"] = 1 if flat.get("data_complete") else 0
        row = {c: flat.get(c) for c in DERIVED_SAMPLES_COLUMNS}
        row["snapshot_id"] = snapshot_id
        row["composite_score"] = composite_score
        row["alarm_level"] = alarm_level
        row["computed_at"] = datetime.now().isoformat(timespec="seconds")
        cols = DERIVED_SAMPLES_COLUMNS
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        sql = f"INSERT INTO derived_samples ({col_names}) VALUES ({placeholders})"
        cur = self.conn.cursor()
        cur.execute(sql, [row.get(c) for c in cols])
        self.conn.commit()
        return cur.lastrowid

    def insert_aggregate(self, table: str, row: Dict) -> int:
        """درج/به‌روزرسانی یک ردیف تجمیعی در aggregate_5min یا aggregate_15min.

        table: "aggregate_5min" یا "aggregate_15min".
        کلید یکتا (symbol, date_jalali, bucket_start) → در صورت تکرار، به‌روزرسانی.
        """
        assert table in ("aggregate_5min", "aggregate_15min"), f"جدول نامعتبر: {table}"
        row = dict(row)
        row["computed_at"] = datetime.now().isoformat(timespec="seconds")
        cols = AGGREGATE_COLUMNS
        values = [row.get(c) for c in cols]
        symbol = row.get("symbol", "")
        date_jalali = row.get("date_jalali", "")
        bucket_start = row.get("bucket_start", "")
        cur = self.conn.cursor()
        cur.execute(
            f"SELECT agg_id FROM {table} "
            "WHERE symbol=? AND date_jalali=? AND bucket_start=?",
            (symbol, date_jalali, bucket_start),
        )
        existing = cur.fetchone()
        if existing:
            agg_id = existing[0]
            set_clause = ", ".join(f"{c}=?" for c in cols)
            cur.execute(f"UPDATE {table} SET {set_clause} WHERE agg_id=?",
                        (*values, agg_id))
        else:
            placeholders = ", ".join(["?"] * len(cols))
            col_names = ", ".join(cols)
            cur.execute(f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})",
                        values)
            agg_id = cur.lastrowid
        self.conn.commit()
        return agg_id

    def get_derived_samples_for_symbol(self, symbol: str,
                                       date_jalali: Optional[str] = None,
                                       limit: Optional[int] = None) -> List[Dict]:
        """بازگشت ردیف‌های enriched یک نماد به ترتیب زمانی."""
        sql = "SELECT * FROM derived_samples WHERE symbol = ?"
        params: list = [symbol]
        if date_jalali:
            sql += " AND date_jalali = ?"
            params.append(date_jalali)
        sql += " ORDER BY timestamp ASC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def get_last_derived_sample(self, symbol: str,
                                date_jalali: Optional[str] = None) -> Optional[Dict]:
        """آخرین ردیف enriched یک نماد (متناسب با timestamp فعلی برای /live و /db)."""
        sql = "SELECT * FROM derived_samples WHERE symbol = ?"
        params: list = [symbol]
        if date_jalali:
            sql += " AND date_jalali = ?"
            params.append(date_jalali)
        sql += " ORDER BY timestamp DESC LIMIT 1"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        row = cur.fetchone()
        return dict(row) if row else None

    def get_aggregates_for_symbol(self, table: str, symbol: str,
                                  date_jalali: Optional[str] = None) -> List[Dict]:
        """بازگشت ردیف‌های تجمیعی یک نماد به ترتیب bucket_start."""
        assert table in ("aggregate_5min", "aggregate_15min"), f"جدول نامعتبر: {table}"
        sql = f"SELECT * FROM {table} WHERE symbol = ?"
        params: list = [symbol]
        if date_jalali:
            sql += " AND date_jalali = ?"
            params.append(date_jalali)
        sql += " ORDER BY bucket_start ASC"
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]

    def count_derived_samples(self, symbol: Optional[str] = None) -> int:
        """تعداد ردیف‌های derived_samples."""
        cur = self.conn.cursor()
        if symbol:
            cur.execute("SELECT COUNT(*) FROM derived_samples WHERE symbol = ?", (symbol,))
        else:
            cur.execute("SELECT COUNT(*) FROM derived_samples")
        return int(cur.fetchone()[0])

    def close(self):
        self.conn.close()
