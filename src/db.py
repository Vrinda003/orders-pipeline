"""SQLite schema and connection helper."""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    customer_id   TEXT PRIMARY KEY,
    customer_name TEXT,
    country       TEXT,
    signup_date   TEXT
);

CREATE TABLE IF NOT EXISTS orders_clean (
    order_id    TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(customer_id),
    order_ts    TEXT NOT NULL,
    order_date  TEXT NOT NULL,
    amount      REAL NOT NULL CHECK (amount >= 0),
    currency    TEXT NOT NULL,
    amount_usd  REAL NOT NULL,
    status      TEXT NOT NULL,
    event_ts    TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    source_file TEXT NOT NULL
);

-- Append-only: every valid version of an order is kept (never overwritten).
CREATE TABLE IF NOT EXISTS orders_history (
    order_id    TEXT NOT NULL,
    event_ts    TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    order_ts    TEXT NOT NULL,
    amount      REAL NOT NULL,
    currency    TEXT NOT NULL,
    status      TEXT NOT NULL,
    run_id      TEXT NOT NULL,
    source_file TEXT NOT NULL,
    PRIMARY KEY (order_id, event_ts)
);

CREATE TABLE IF NOT EXISTS orders_rejects (
    reject_id     TEXT PRIMARY KEY,   -- sha1(source_file|line_number)[:16]
    run_id        TEXT NOT NULL,
    source_file   TEXT NOT NULL,
    line_number   INTEGER NOT NULL,
    raw_record    TEXT NOT NULL,      -- JSON list of the raw fields
    reject_reason TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    run_id           TEXT PRIMARY KEY,
    source_file      TEXT,
    start_time       TEXT NOT NULL,
    end_time         TEXT,
    status           TEXT NOT NULL,   -- RUNNING / SUCCESS / FAILED
    input_rows       INTEGER DEFAULT 0,
    valid_rows       INTEGER DEFAULT 0,
    inserted_rows    INTEGER DEFAULT 0,
    updated_rows     INTEGER DEFAULT 0,
    duplicate_rows   INTEGER DEFAULT 0,
    rejected_rows    INTEGER DEFAULT 0,
    reject_breakdown TEXT,
    chunk_size       INTEGER,
    duration_seconds REAL,
    failure_reason   TEXT
);
"""


def connect(db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn