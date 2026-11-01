"""Reconciliation / validation report.

Usage:
    python src/reconcile.py --db output/orders.db --expected data/generated/expected_answers.json
"""
import argparse
import json
import sqlite3
import sys
from pathlib import Path

import config


def one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()[0]


def run_checks(db_path, expected_path=None):
    """Return a list of (check_name, passed, detail)."""
    conn = sqlite3.connect(str(db_path))
    checks = []

    def add(name, ok, detail):
        checks.append((name, bool(ok), detail))

    run = conn.execute(
        "SELECT run_id, status, input_rows, inserted_rows, updated_rows, duplicate_rows, "
        "rejected_rows, source_file FROM pipeline_runs ORDER BY start_time DESC, rowid DESC LIMIT 1"
    ).fetchone()
    if run is None:
        add("a pipeline run exists", False, "pipeline_runs is empty")
        return checks
    run_id, status, inp, ins, upd, dup, rej, source_file = run

    add("latest run status is SUCCESS", status == "SUCCESS", f"run {run_id}: {status}")
    add("input = inserted + updated + duplicate + rejected", inp == ins + upd + dup + rej,
        f"{inp} vs {ins}+{upd}+{dup}+{rej} = {ins + upd + dup + rej}")

    dupes = one(conn, "SELECT COUNT(*) FROM (SELECT order_id FROM orders_clean "
                      "GROUP BY order_id HAVING COUNT(*) > 1)")
    add("no duplicate order_id in orders_clean", dupes == 0, f"{dupes} duplicated ids")

    orphans = one(conn, "SELECT COUNT(*) FROM orders_clean o LEFT JOIN customers c "
                        "ON o.customer_id = c.customer_id WHERE c.customer_id IS NULL")
    add("every order has a known customer (referential integrity)", orphans == 0,
        f"{orphans} orphan orders")

    n_rej = one(conn, "SELECT COUNT(*) FROM orders_rejects WHERE source_file = ?", (source_file,))
    add("rejects table matches run's rejected count", n_rej == rej, f"{n_rej} vs {rej}")

    missing_hist = one(conn, "SELECT COUNT(*) FROM orders_clean o LEFT JOIN orders_history h "
                             "ON o.order_id = h.order_id AND o.event_ts = h.event_ts "
                             "WHERE h.order_id IS NULL")
    add("every current order has a matching history row", missing_hist == 0,
        f"{missing_hist} without history")

    if expected_path:
        exp = json.loads(Path(expected_path).read_text())
        n_clean = one(conn, "SELECT COUNT(*) FROM orders_clean WHERE source_file = ?", (exp["source_file"],))
        add("clean order count matches expected_answers", n_clean == exp["clean_orders"],
            f"{n_clean} vs {exp['clean_orders']}")
        total = one(conn, "SELECT COALESCE(SUM(amount), 0) FROM orders_clean WHERE source_file = ?",
                    (exp["source_file"],))
        add("sum(amount) matches expected_answers", abs(total - exp["clean_amount_sum"]) < 0.01,
            f"{total:.2f} vs {exp['clean_amount_sum']:.2f}")
        got = dict(conn.execute("SELECT reject_reason, COUNT(*) FROM orders_rejects "
                                "WHERE source_file = ? GROUP BY reject_reason", (exp["source_file"],)))
        add("rejects by reason match expected_answers", got == exp["rejects_by_reason"],
            f"{got} vs {exp['rejects_by_reason']}")
        add("input row count matches expected_answers", inp == exp["data_rows"],
            f"{inp} vs {exp['data_rows']}")
    conn.close()
    return checks


def sample_queries(db_path):
    conn = sqlite3.connect(str(db_path))
    queries = {
        "Revenue (USD) by customer country":
            "SELECT c.country, COUNT(*) AS orders, ROUND(SUM(o.amount_usd), 2) AS revenue_usd "
            "FROM orders_clean o JOIN customers c USING (customer_id) "
            "GROUP BY c.country ORDER BY revenue_usd DESC",
        "Orders per status":
            "SELECT status, COUNT(*) AS orders FROM orders_clean GROUP BY status ORDER BY orders DESC",
        "Top 5 customers by revenue (USD)":
            "SELECT customer_id, ROUND(SUM(amount_usd), 2) AS revenue_usd FROM orders_clean "
            "GROUP BY customer_id ORDER BY revenue_usd DESC LIMIT 5",
        "Rejects by reason":
            "SELECT reject_reason, COUNT(*) AS n FROM orders_rejects GROUP BY reject_reason ORDER BY n DESC",
    }
    out = {}
    for title, sql in queries.items():
        cur = conn.execute(sql)
        out[title] = ([d[0] for d in cur.description], cur.fetchall())
    conn.close()
    return out


def md_table(cols, rows):
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in rows]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description="Reconcile pipeline output")
    p.add_argument("--db", default=str(config.DEFAULT_DB_PATH))
    p.add_argument("--expected")
    p.add_argument("--out", default=str(config.BASE_DIR / "output" / "reconciliation_report.md"))
    a = p.parse_args()

    checks = run_checks(a.db, a.expected)
    lines = ["# Reconciliation report", "", "| Check | Result | Detail |", "|---|---|---|"]
    for name, ok, detail in checks:
        lines.append(f"| {name} | {'PASS' if ok else 'FAIL'} | {detail} |")
        print(f"[{'PASS' if ok else 'FAIL'}] {name}  ({detail})")
    lines += ["", "# Sample queries"]
    for title, (cols, rows) in sample_queries(a.db).items():
        lines += ["", f"## {title}", "", md_table(cols, rows)]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text("\n".join(lines) + "\n")
    print(f"\nReport written to {a.out}")
    sys.exit(0 if all(ok for _, ok, _ in checks) else 1)


if __name__ == "__main__":
    main()