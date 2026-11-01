"""Reproducible synthetic data generator (streams rows to disk, one at a time).

Usage:
    python src/generate_data.py --rows 100000 --output data/generated

Writes customers.csv, orders.csv and (SEPARATELY) expected_answers.json, which
holds the true answers so the pipeline output can be checked independently.
"""
import argparse
import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

HEADER = ["order_id", "customer_id", "order_ts", "amount", "currency", "status", "event_ts"]
BAD_TYPES = [
    "missing_order_id", "amount_not_numeric", "amount_negative", "invalid_currency",
    "invalid_status", "unknown_customer", "invalid_timestamp", "event_before_order",
    "malformed_row_field_count",
]
COUNTRIES = ["US", "DE", "IN", "FR", "GB"]
START = datetime(2026, 1, 1)


def iso(dt):
    return dt.isoformat(timespec="seconds")


def make_base(rng, n, n_customers):
    """One valid order (final version). Returns (fields, amount_cents)."""
    order_ts = START + timedelta(minutes=rng.randint(0, 300 * 24 * 60))
    event_ts = order_ts + timedelta(hours=rng.randint(2, 72))
    roll = rng.random()
    if roll < 0.01:
        amount = 0.00                 # boundary: zero is allowed
    elif roll < 0.02:
        amount = 1_000_000.00         # boundary: maximum allowed
    else:
        amount = round(rng.uniform(5, 500), 2)
    fields = [
        f"O{n:07d}", f"C{rng.randint(1, n_customers):04d}", iso(order_ts),
        f"{amount:.2f}", rng.choice(["USD", "EUR", "INR"]),
        rng.choice(["NEW", "SHIPPED", "CANCELLED"]), iso(event_ts),
    ]
    return fields, round(amount * 100)


def stale_version(fields):
    """An OLDER version of the same order (event 1 minute after the order)."""
    order_ts = datetime.fromisoformat(fields[2])
    old = list(fields)
    old[5] = "NEW"
    old[6] = iso(order_ts + timedelta(minutes=1))
    return old


def make_bad(rng, bad_type, fields):
    f = list(fields)
    if bad_type == "missing_order_id":
        f[0] = ""
    elif bad_type == "amount_not_numeric":
        f[3] = "abc"
    elif bad_type == "amount_negative":
        f[3] = "-" + (f[3] if float(f[3]) > 0 else "5.00")  # "-0.00" is not negative
    elif bad_type == "invalid_currency":
        f[4] = "XXX"
    elif bad_type == "invalid_status":
        f[5] = "UNKNOWN"
    elif bad_type == "unknown_customer":
        f[1] = "C9999999"
    elif bad_type == "invalid_timestamp":
        f[2] = "31-31-2026"
    elif bad_type == "event_before_order":
        f[6] = iso(datetime.fromisoformat(f[2]) - timedelta(hours=1))
    elif bad_type == "malformed_row_field_count":
        return ",".join(f[:4])  # raw truncated line (a str means "write as-is")
    return f


def generate(rows, out_dir, seed=42, n_customers=1000,
             bad_rate=0.02, dup_rate=0.01, stale_rate=0.01, older_first_rate=0.01):
    rng = random.Random(seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    with open(out / "customers.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["customer_id", "customer_name", "country", "signup_date"])
        for i in range(1, n_customers + 1):
            w.writerow([f"C{i:04d}", f"Customer {i}", rng.choice(COUNTRIES),
                        iso(START - timedelta(days=rng.randint(1, 900)))[:10]])

    exp = {
        "seed": seed, "source_file": "orders.csv", "data_rows": 0,
        "rejects_by_reason": {t: 0 for t in BAD_TYPES},
        "inserted_rows": 0, "updated_rows": 0, "duplicate_rows": 0,
        "clean_orders": 0, "clean_amount_sum": 0.0,
    }
    cents_total, written, n = 0, 0, 0

    with open(out / "orders.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        while written < rows:
            n += 1
            base, cents = make_base(rng, n, n_customers)
            roll = rng.random()
            kind, lines = "single", [base]
            if roll < bad_rate:
                bad_type = rng.choice(BAD_TYPES)
                kind, lines = bad_type, [make_bad(rng, bad_type, base)]
            elif roll < bad_rate + dup_rate:
                kind, lines = "exact_dup", [base, base]
            elif roll < bad_rate + dup_rate + stale_rate:
                kind, lines = "stale_after_new", [base, stale_version(base)]
            elif roll < bad_rate + dup_rate + stale_rate + older_first_rate:
                kind, lines = "older_first", [stale_version(base), base]
            if written + len(lines) > rows:      # keep the row count exact
                kind, lines = "single", [base]

            for line in lines:
                if isinstance(line, str):
                    f.write(line + "\n")
                else:
                    w.writerow(line)
            written += len(lines)

            if kind in BAD_TYPES:
                exp["rejects_by_reason"][kind] += 1
            else:
                exp["inserted_rows"] += 1
                cents_total += cents
                if kind in ("exact_dup", "stale_after_new"):
                    exp["duplicate_rows"] += 1
                elif kind == "older_first":
                    exp["updated_rows"] += 1

    exp["data_rows"] = written
    exp["clean_orders"] = exp["inserted_rows"]
    exp["clean_amount_sum"] = round(cents_total / 100, 2)
    exp["rejects_by_reason"] = {k: v for k, v in exp["rejects_by_reason"].items() if v}
    (out / "expected_answers.json").write_text(json.dumps(exp, indent=2))
    return exp


def main():
    p = argparse.ArgumentParser(description="Generate synthetic orders data")
    p.add_argument("--rows", type=int, default=100_000)
    p.add_argument("--output", default="data/generated")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--customers", type=int, default=1000)
    a = p.parse_args()
    exp = generate(a.rows, a.output, a.seed, a.customers)
    print(f"Wrote {exp['data_rows']} order rows to {a.output}/orders.csv")
    print(f"Expected clean orders: {exp['clean_orders']}, rejects: {exp['rejects_by_reason']}")


if __name__ == "__main__":
    main()