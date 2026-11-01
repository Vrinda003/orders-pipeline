"""Automated tests. Each test uses its own temporary folder + database."""
import csv
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import generate_data  # noqa: E402
import pipeline       # noqa: E402
import reconcile      # noqa: E402
import validate       # noqa: E402

HEADER = ["order_id", "customer_id", "order_ts", "amount", "currency", "status", "event_ts"]


# ---------- helpers ----------
def row(order_id="O1", customer="C1", order_ts="2026-01-01T10:00:00", amount="10.00",
        currency="USD", status="NEW", event_ts="2026-01-01T12:00:00"):
    return [order_id, customer, order_ts, amount, currency, status, event_ts]


def write_orders(folder, rows, header=HEADER):
    folder = Path(folder)
    with open(folder / "orders.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    with open(folder / "customers.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["customer_id", "customer_name", "country", "signup_date"])
        w.writerow(["C1", "Alice", "US", "2025-01-01"])
        w.writerow(["C2", "Bruno", "DE", "2025-01-02"])
    return folder / "orders.csv"


def run(folder, rows, header=HEADER, **kw):
    path = write_orders(folder, rows, header)
    return pipeline.run_pipeline(path, Path(folder) / "t.db", **kw)


def q(folder, sql):
    conn = sqlite3.connect(str(Path(folder) / "t.db"))
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


# ---------- the required scenarios ----------
def test_happy_path(tmp_path):
    s = run(tmp_path, [row(f"O{i}") for i in range(5)])
    assert s["status"] == "SUCCESS"
    assert (s["input_rows"], s["inserted_rows"], s["rejected_rows"]) == (5, 5, 0)
    assert q(tmp_path, "SELECT COUNT(*) FROM orders_clean") == [(5,)]


def test_empty_input_header_only(tmp_path):
    s = run(tmp_path, [])
    assert s["status"] == "SUCCESS"
    assert s["input_rows"] == 0
    assert q(tmp_path, "SELECT COUNT(*) FROM orders_clean") == [(0,)]


def test_completely_empty_file_fails_clearly(tmp_path):
    path = write_orders(tmp_path, [])
    path.write_text("")  # zero bytes: no header at all
    s = pipeline.run_pipeline(path, tmp_path / "t.db")
    assert s["status"] == "FAILED"
    assert "empty" in s["failure_reason"]


def test_malformed_record_goes_to_rejects(tmp_path):
    path = write_orders(tmp_path, [row("O1")])
    with open(path, "a") as f:
        f.write("O2,C1,2026-01-01T10:00:00\n")  # too few fields
    s = pipeline.run_pipeline(path, tmp_path / "t.db")
    assert s["status"] == "SUCCESS"
    assert s["rejected_rows"] == 1
    assert q(tmp_path, "SELECT reject_reason, line_number FROM orders_rejects") == [
        ("malformed_row_field_count", 3)]


def test_exact_duplicate_stored_once(tmp_path):
    s = run(tmp_path, [row("O1"), row("O1")])
    assert (s["inserted_rows"], s["duplicate_rows"]) == (1, 1)
    assert q(tmp_path, "SELECT COUNT(*) FROM orders_clean") == [(1,)]


def test_null_required_field_rejected(tmp_path):
    s = run(tmp_path, [row(order_id=""), row("O2")])
    assert s["reject_breakdown"] == {"missing_order_id": 1}
    assert s["inserted_rows"] == 1


def test_missing_required_column_fails_run(tmp_path):
    bad_header = [h for h in HEADER if h != "amount"]
    path = write_orders(tmp_path, [], header=bad_header)
    s = pipeline.run_pipeline(path, tmp_path / "t.db")
    assert s["status"] == "FAILED"
    assert "missing required column" in s["failure_reason"] and "amount" in s["failure_reason"]
    assert q(tmp_path, "SELECT status FROM pipeline_runs") == [("FAILED",)]


def test_extra_column_is_ignored(tmp_path):
    header = HEADER + ["surprise"]
    s = run(tmp_path, [row("O1") + ["x"]], header=header)
    assert s["status"] == "SUCCESS" and s["inserted_rows"] == 1


def test_unknown_customer_rejected(tmp_path):
    s = run(tmp_path, [row(customer="C999")])
    assert s["reject_breakdown"] == {"unknown_customer": 1}


def test_rerun_same_file_is_idempotent(tmp_path):
    rows = [row("O1"), row("O2"), row("O3", amount="abc")]
    run(tmp_path, rows)
    before = (q(tmp_path, "SELECT COUNT(*) FROM orders_clean"),
              q(tmp_path, "SELECT COUNT(*) FROM orders_rejects"),
              q(tmp_path, "SELECT COUNT(*) FROM orders_history"))
    s2 = run(tmp_path, rows)
    after = (q(tmp_path, "SELECT COUNT(*) FROM orders_clean"),
             q(tmp_path, "SELECT COUNT(*) FROM orders_rejects"),
             q(tmp_path, "SELECT COUNT(*) FROM orders_history"))
    assert before == after == ([(2,)], [(1,)], [(2,)])
    assert s2["inserted_rows"] == 0 and s2["duplicate_rows"] == 2


def test_late_older_version_does_not_overwrite_newer(tmp_path):
    newer = row("O1", status="SHIPPED", event_ts="2026-01-02T12:00:00")
    older = row("O1", status="NEW", event_ts="2026-01-01T12:00:00")
    s = run(tmp_path, [newer, older])  # newer arrives first, older arrives late
    assert s["duplicate_rows"] == 1
    assert q(tmp_path, "SELECT status FROM orders_clean") == [("SHIPPED",)]
    assert q(tmp_path, "SELECT COUNT(*) FROM orders_history") == [(2,)]  # history keeps both


def test_newer_version_updates_existing_order(tmp_path):
    older = row("O1", status="NEW", event_ts="2026-01-01T12:00:00")
    newer = row("O1", status="SHIPPED", event_ts="2026-01-02T12:00:00")
    s = run(tmp_path, [older, newer])
    assert (s["inserted_rows"], s["updated_rows"]) == (1, 1)
    assert q(tmp_path, "SELECT status FROM orders_clean") == [("SHIPPED",)]


def test_domain_amount_boundaries(tmp_path):
    rows = [row("O1", amount="0.00", status="CANCELLED"),     # zero is valid
            row("O2", amount="1000000.00"),                   # exact max is valid
            row("O3", amount="1000000.01"),                   # just over -> reject
            row("O4", amount="-0.01"),                        # negative -> reject
            row("O5", amount="nan")]                          # not a real number
    s = run(tmp_path, rows)
    assert s["inserted_rows"] == 2
    assert s["reject_breakdown"] == {"amount_too_large": 1, "amount_negative": 1,
                                     "amount_not_numeric": 1}


def test_domain_event_before_order_rejected(tmp_path):
    s = run(tmp_path, [row(order_ts="2026-01-05T10:00:00", event_ts="2026-01-04T10:00:00")])
    assert s["reject_breakdown"] == {"event_before_order": 1}


def test_derived_fields_and_timezone_normalisation():
    rec = dict(zip(HEADER, row(amount="100", currency="eur",
                               order_ts="2026-03-01T10:00:00+02:00",
                               event_ts="2026-03-01T12:00:00+02:00")))
    out = validate.transform_row(rec)
    assert out["amount_usd"] == 108.0 and out["currency"] == "EUR"
    assert out["order_ts"] == "2026-03-01T08:00:00"   # converted to UTC
    assert out["order_date"] == "2026-03-01"


def test_partial_failure_then_retry_recovers(tmp_path):
    rows = [row(f"O{i}") for i in range(6)]
    path = write_orders(tmp_path, rows)
    db = tmp_path / "t.db"
    s1 = pipeline.run_pipeline(path, db, chunk_size=2, fail_after_chunks=1)  # crash in chunk 2
    assert s1["status"] == "FAILED" and "simulated crash" in s1["failure_reason"]
    assert q(tmp_path, "SELECT COUNT(*) FROM orders_clean") == [(2,)]   # chunk 1 kept, chunk 2 rolled back
    s2 = pipeline.run_pipeline(path, db, chunk_size=2)                  # simply re-run
    assert s2["status"] == "SUCCESS"
    assert q(tmp_path, "SELECT COUNT(*) FROM orders_clean") == [(6,)]
    assert s2["inserted_rows"] == 4 and s2["duplicate_rows"] == 2


def test_chunking_gives_same_result_as_one_big_chunk(tmp_path):
    rows = [row(f"O{i}") for i in range(25)] + [row("O3")]
    a = tmp_path / "a"; b = tmp_path / "b"; a.mkdir(); b.mkdir()
    sa = run(a, rows, chunk_size=1000)
    sb = run(b, rows, chunk_size=7)
    keys = ["input_rows", "inserted_rows", "updated_rows", "duplicate_rows", "rejected_rows"]
    assert [sa[k] for k in keys] == [sb[k] for k in keys]


# ---------- end-to-end on generated data, checked against INDEPENDENT labels ----------
def test_generated_data_matches_expected_answers(tmp_path):
    exp = generate_data.generate(3000, tmp_path, seed=7, n_customers=50)
    s = pipeline.run_pipeline(tmp_path / "orders.csv", tmp_path / "t.db")
    assert s["status"] == "SUCCESS"
    assert s["input_rows"] == exp["data_rows"] == 3000
    assert s["reject_breakdown"] == exp["rejects_by_reason"]
    assert (s["inserted_rows"], s["updated_rows"], s["duplicate_rows"]) == (
        exp["inserted_rows"], exp["updated_rows"], exp["duplicate_rows"])
    checks = reconcile.run_checks(tmp_path / "t.db", tmp_path / "expected_answers.json")
    failed = [c for c in checks if not c[1]]
    assert not failed, failed


def test_generator_is_reproducible(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"
    generate_data.generate(500, a, seed=1, n_customers=20)
    generate_data.generate(500, b, seed=1, n_customers=20)
    assert (a / "orders.csv").read_bytes() == (b / "orders.csv").read_bytes()