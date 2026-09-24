from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;
PRAGMA busy_timeout=10000;

CREATE TABLE IF NOT EXISTS announcements (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 art_code TEXT NOT NULL UNIQUE,
 title TEXT, title_ch TEXT, title_en TEXT,
 notice_date TEXT, display_time TEXT, sort_date TEXT, ei_time TEXT,
 language TEXT, product_code TEXT, source_type TEXT,
 raw_json TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS announcement_stocks (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 announcement_id INTEGER NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
 stock_code TEXT NOT NULL, stock_name TEXT, inner_code TEXT, market_code TEXT, ann_type TEXT,
 UNIQUE(announcement_id, stock_code)
);
CREATE TABLE IF NOT EXISTS announcement_columns (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 announcement_id INTEGER NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
 column_code TEXT, column_name TEXT,
 UNIQUE(announcement_id, column_code, column_name)
);
CREATE TABLE IF NOT EXISTS fetch_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 fetch_date TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
 page_size INTEGER, pages INTEGER DEFAULT 0, expected_count INTEGER DEFAULT 0,
 received_count INTEGER DEFAULT 0, inserted_count INTEGER DEFAULT 0,
 duplicate_count INTEGER DEFAULT 0, success INTEGER NOT NULL DEFAULT 0,
 error_message TEXT
);
CREATE TABLE IF NOT EXISTS analysis_results (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 announcement_id INTEGER NOT NULL REFERENCES announcements(id) ON DELETE CASCADE,
 analyzer TEXT NOT NULL, rule_version TEXT NOT NULL,
 category TEXT, is_noise INTEGER, summary TEXT, key_numbers TEXT, result_json TEXT,
 created_at TEXT NOT NULL,
 UNIQUE(announcement_id, analyzer, rule_version)
);
CREATE INDEX IF NOT EXISTS idx_ann_date ON announcements(notice_date);
CREATE INDEX IF NOT EXISTS idx_ann_sort ON announcements(sort_date);
CREATE INDEX IF NOT EXISTS idx_ann_stock_code ON announcement_stocks(stock_code);
CREATE INDEX IF NOT EXISTS idx_ann_stock_id ON announcement_stocks(announcement_id);
CREATE INDEX IF NOT EXISTS idx_ann_column_code ON announcement_columns(column_code);
CREATE INDEX IF NOT EXISTS idx_ann_column_name ON announcement_columns(column_name);
CREATE INDEX IF NOT EXISTS idx_analysis_category ON analysis_results(category);
"""

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    return conn

def init_db():
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.commit()

def insert_announcement(conn, item):
    art_code = str(item.get("art_code") or "").strip()
    if not art_code:
        raise ValueError("missing art_code")
    now = utc_now()
    raw = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
    row = conn.execute("SELECT id FROM announcements WHERE art_code=?", (art_code,)).fetchone()
    if row:
        ann_id = int(row["id"])
        conn.execute("UPDATE announcements SET last_seen_at=? WHERE id=?", (now, ann_id))
        inserted = False
    else:
        cur = conn.execute(
            """INSERT INTO announcements
            (art_code,title,title_ch,title_en,notice_date,display_time,sort_date,ei_time,
             language,product_code,source_type,raw_json,first_seen_at,last_seen_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (art_code,item.get("title"),item.get("title_ch"),item.get("title_en"),
             item.get("notice_date"),item.get("display_time"),item.get("sort_date"),
             item.get("eiTime") or item.get("ei_time"),item.get("language"),
             item.get("product_code"),item.get("source_type"),raw,now,now))
        ann_id = int(cur.lastrowid)
        inserted = True

    for stock in item.get("codes") or []:
        if not isinstance(stock, dict): continue
        code = str(stock.get("stock_code") or "").strip()
        if not code: continue
        conn.execute(
            """INSERT OR IGNORE INTO announcement_stocks
            (announcement_id,stock_code,stock_name,inner_code,market_code,ann_type)
            VALUES (?,?,?,?,?,?)""",
            (ann_id,code,stock.get("short_name"),stock.get("inner_code"),
             stock.get("market_code"),stock.get("ann_type")))

    for column in item.get("columns") or []:
        if not isinstance(column, dict): continue
        conn.execute(
            """INSERT OR IGNORE INTO announcement_columns
            (announcement_id,column_code,column_name) VALUES (?,?,?)""",
            (ann_id,column.get("column_code"),column.get("column_name")))
    return ann_id, inserted
