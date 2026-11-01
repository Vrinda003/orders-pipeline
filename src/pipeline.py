"""Chunked, idempotent CSV -> SQLite pipeline.

Usage:
    python src/pipeline.py --input data/sample/orders.csv
"""
import argparse
import csv
import hashlib
import json
import logging
import sys
import time
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path

import config
import db
import validate

logger = logging.getLogger("pipeline")

UPSERT_SQL = """
INSERT INTO orders_clean
    (order_id, customer_id, order_ts, order_date, amount, currency,
     amount_usd, status, event_ts, run_id, source_file)
VALUES
    (:order_id, :customer_id, :order_ts, :order_date, :amount, :currency,
     :amount_usd, :status, :event_ts, :run_id, :source_file)
ON CONFLICT(order_id) DO UPDATE SET
    customer_id = excluded.customer_id, order_ts = excluded.order_ts,
    order_date  = excluded.order_date,  amount   = excluded.amount,
    currency    = excluded.currency,    amount_usd = excluded.amount_usd,
    status      = excluded.status,      event_ts = excluded.event_ts,
    run_id      = excluded.run_id,      source_file = excluded.source_file
WHERE excluded.event_ts > orders_clean.event_ts   -- late/older data never wins
"""

HISTORY_SQL = """
INSERT OR IGNORE INTO orders_history
    (order_id, event_ts, customer_id, order_ts, amount, currency, status,
     run_id, source_file)
VALUES
    (:order_id, :event_ts, :customer_id, :order_ts, :amount, :currency,
     :status, :run_id, :source_file)
"""

REJECT_SQL = """
INSERT OR REPLACE INTO orders_rejects
    (reject_id, run_id, source_file, line_number, raw_record, reject_reason)
VALUES (:reject_id, :run_id, :source_file, :line_number, :raw_record, :reject_reason)
"""


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def make_run_id():
    return datetime.now().strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]


def reject_id(source_file, line_number):
    """Deterministic ID: re-running the same file overwrites, never duplicates."""
    return hashlib.sha1(f"{source_file}|{line_number}".encode()).hexdigest()[:16]


def load_customers(conn, customers_path):
    """Load the (small) reference file into the DB and return the ID set."""
    with open(customers_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        validate.check_header(reader.fieldnames or [], config.REQUIRED_CUSTOMER_COLUMNS, logger)
        for row in reader:
            cid = (row["customer_id"] or "").strip()
            if not cid:
                logger.warning("Skipping customer row without customer_id: %s", row)
                continue
            # Upsert, NOT "INSERT OR REPLACE": REPLACE deletes the row first, which
            # makes SQLite re-check every order that references it (very slow).
            conn.execute(
                "INSERT INTO customers VALUES (?,?,?,?) ON CONFLICT(customer_id) DO UPDATE SET "
                "customer_name=excluded.customer_name, country=excluded.country, "
                "signup_date=excluded.signup_date",
                (cid, row["customer_name"], row["country"], row["signup_date"]),
            )
    conn.commit()
    return {r[0] for r in conn.execute("SELECT customer_id FROM customers")}


def read_chunks(path, chunk_size):
    """Yield (header, [(line_number, fields), ...]) lists of at most chunk_size rows.

    Only one chunk lives in memory at a time -> bounded memory.
    """
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = [h.strip() for h in next(reader)]
        except StopIteration:
            raise validate.SchemaError("file is empty (no header row)")
        validate.check_header(header, config.REQUIRED_ORDER_COLUMNS, logger)
        yield header, None  # first item: header only
        chunk = []
        for fields in reader:
            chunk.append((reader.line_num, fields))
            if len(chunk) >= chunk_size:
                yield header, chunk
                chunk = []
        if chunk:
            yield header, chunk


def fetch_existing(conn, order_ids):
    """Return {order_id: event_ts} for ids already in orders_clean."""
    ids = list(order_ids)
    found = {}
    for i in range(0, len(ids), 500):  # stay under SQLite's variable limit
        batch = ids[i:i + 500]
        marks = ",".join("?" * len(batch))
        q = f"SELECT order_id, event_ts FROM orders_clean WHERE order_id IN ({marks})"
        found.update(conn.execute(q, batch).fetchall())
    return found


def process_chunk(conn, header, rows, run_id, source_file, valid_customers):
    """Validate one chunk and write it. Does NOT commit (caller does)."""
    stats = Counter()
    reasons = Counter()
    valid, rejects = [], []

    for line_no, fields in rows:
        stats["input_rows"] += 1
        if len(fields) != len(header):
            reason = "malformed_row_field_count"
        else:
            rec = dict(zip(header, fields))
            reason = validate.validate_row(rec, valid_customers)
        if reason:
            reasons[reason] += 1
            rejects.append({
                "reject_id": reject_id(source_file, line_no), "run_id": run_id,
                "source_file": source_file, "line_number": line_no,
                "raw_record": json.dumps(fields), "reject_reason": reason,
            })
        else:
            row = validate.transform_row(rec)
            row.update(run_id=run_id, source_file=source_file)
            valid.append(row)

    # Decide insert / update / duplicate in file order, tracking versions
    existing = fetch_existing(conn, {r["order_id"] for r in valid})
    to_upsert = []
    for row in valid:
        seen = existing.get(row["order_id"])
        if seen is None:
            stats["inserted_rows"] += 1
        elif row["event_ts"] > seen:
            stats["updated_rows"] += 1
        else:
            stats["duplicate_rows"] += 1   # same or older version: not applied
            continue
        existing[row["order_id"]] = row["event_ts"]
        to_upsert.append(row)

    conn.executemany(HISTORY_SQL, valid)      # every valid version is kept
    conn.executemany(UPSERT_SQL, to_upsert)   # only newest version wins
    conn.executemany(REJECT_SQL, rejects)
    stats["rejected_rows"] = len(rejects)
    return stats, reasons


def run_pipeline(input_path, db_path=config.DEFAULT_DB_PATH, customers_path=None,
                 chunk_size=config.CHUNK_SIZE, fail_after_chunks=None):
    """Run the whole pipeline. Returns a summary dict; never raises for data problems.

    fail_after_chunks: test hook that simulates a crash after N committed chunks.
    """
    input_path = Path(input_path)
    customers_path = Path(customers_path) if customers_path else input_path.parent / "customers.csv"
    source_file = input_path.name
    run_id = make_run_id()
    start_iso = now_iso()
    start = time.perf_counter()
    totals, all_reasons = Counter(), Counter()
    status, failure = "SUCCESS", None

    conn = db.connect(db_path)
    conn.execute(
        "INSERT INTO pipeline_runs (run_id, source_file, start_time, status, chunk_size) "
        "VALUES (?,?,?,?,?)", (run_id, source_file, start_iso, "RUNNING", chunk_size))
    conn.commit()
    logger.info("Run %s started: file=%s chunk_size=%d", run_id, source_file, chunk_size)

    try:
        valid_customers = load_customers(conn, customers_path)
        committed_chunks = 0
        for header, rows in read_chunks(input_path, chunk_size):
            if rows is None:
                continue  # header-only marker
            stats, reasons = process_chunk(conn, header, rows, run_id, source_file, valid_customers)
            if fail_after_chunks is not None and committed_chunks >= fail_after_chunks:
                raise RuntimeError("simulated crash")  # chunk is rolled back below
            conn.commit()                      # one transaction per chunk
            committed_chunks += 1
            totals.update(stats)
            all_reasons.update(reasons)
            logger.info("chunk %d committed: +%d rows (total %d)",
                        committed_chunks, stats["input_rows"], totals["input_rows"])
    except Exception as exc:  # noqa: BLE001 - we want to record ANY failure
        conn.rollback()                        # undo only the half-done chunk
        status, failure = "FAILED", f"{type(exc).__name__}: {exc}"
        logger.error("Run %s FAILED: %s", run_id, failure)

    duration = round(time.perf_counter() - start, 3)
    valid_rows = totals["inserted_rows"] + totals["updated_rows"] + totals["duplicate_rows"]
    summary = {
        "run_id": run_id, "source_file": source_file, "status": status,
        "start_time": start_iso, "end_time": now_iso(), "chunk_size": chunk_size,
        "input_rows": totals["input_rows"], "valid_rows": valid_rows,
        "inserted_rows": totals["inserted_rows"], "updated_rows": totals["updated_rows"],
        "duplicate_rows": totals["duplicate_rows"], "rejected_rows": totals["rejected_rows"],
        "reject_breakdown": dict(all_reasons), "duration_seconds": duration,
        "failure_reason": failure,
    }
    conn.execute(
        "UPDATE pipeline_runs SET end_time=?, status=?, input_rows=?, valid_rows=?, "
        "inserted_rows=?, updated_rows=?, duplicate_rows=?, rejected_rows=?, "
        "reject_breakdown=?, duration_seconds=?, failure_reason=? WHERE run_id=?",
        (summary["end_time"], status, summary["input_rows"], valid_rows,
         summary["inserted_rows"], summary["updated_rows"], summary["duplicate_rows"],
         summary["rejected_rows"], json.dumps(summary["reject_breakdown"]),
         duration, failure, run_id))
    conn.commit()
    conn.close()
    logger.info("Run %s %s: input=%d valid=%d inserted=%d updated=%d dup=%d rejected=%d (%.2fs)",
                run_id, status, summary["input_rows"], valid_rows, summary["inserted_rows"],
                summary["updated_rows"], summary["duplicate_rows"], summary["rejected_rows"], duration)
    return summary


def setup_logging(log_path=config.DEFAULT_LOG_PATH):
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_path)])


def main():
    p = argparse.ArgumentParser(description="Chunked orders CSV -> SQLite pipeline")
    p.add_argument("--input", required=True, help="path to orders CSV")
    p.add_argument("--customers", help="path to customers CSV (default: customers.csv next to input)")
    p.add_argument("--db", default=str(config.DEFAULT_DB_PATH))
    p.add_argument("--chunk-size", type=int, default=config.CHUNK_SIZE)
    p.add_argument("--report", default=str(config.DEFAULT_REPORT_PATH))
    args = p.parse_args()

    setup_logging()
    summary = run_pipeline(args.input, args.db, args.customers, args.chunk_size)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(summary, indent=2))
    sys.exit(0 if summary["status"] == "SUCCESS" else 1)


if __name__ == "__main__":
    main()