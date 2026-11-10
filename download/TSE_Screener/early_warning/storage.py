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

# ستون‌های جدول snapshots به ترتیب (به جز autoincrement)
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
    "buyer_power", "per_capita_buy_real", "per_capita_sell_real",
    "real_money_flow", "real_money_flow_ratio",
    "data_complete", "missing_fields",
]

TRADE_COLUMNS = [
    "symbol", "snapshot_time", "trade_time",
    "trade_price", "trade_volume", "trade_id", "aggressor_side",
]


# ---------------------------------------------------------------------------
# کلاس اصلی ذخیره‌سازی
# ---------------------------------------------------------------------------

class MarketDataStorage:
    """ذخیره‌ساز SQLite برای نمونه‌های تابلو و معاملات."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """ایجاد جداول اگر وجود ندارند."""
        cur = self.conn.cursor()
        cur.executescript(SCHEMA_SNAPSHOTS)
        cur.executescript(SCHEMA_TRADES)
        cur.executescript(SCHEMA_METADATA)
        self.conn.commit()

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

    def close(self):
        self.conn.close()
