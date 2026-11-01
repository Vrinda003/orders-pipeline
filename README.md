# Orders Pipeline: chunked CSV ingestion with validation, quarantine and reconciliation

A small data pipeline that reads a large orders CSV **in chunks** (bounded memory),
validates every row, loads good rows into SQLite, quarantines bad rows with their
reason, and proves its own correctness with tests and a reconciliation report.

## Architecture

```
customers.csv ──► load customers (small, in memory as a set) ─────────────┐
                                                                          ▼
orders.csv ──► chunk reader ──► validate row ──┬─ valid ──► orders_history (every version)
 (streamed,    (10,000 rows     (schema,       │            orders_clean   (newest version wins)
  one chunk     at a time)       business      └─ invalid ─► orders_rejects (reason + line number)
  in memory)                     rules)
                                                    every chunk = one transaction
                                                    every run   = one row in pipeline_runs
                                                                          │
                                                                          ▼
                                              reconcile.py ──► reconciliation_report.md
```

## Project structure

```
src/config.py         settings (paths, chunk size, allowed values, FX rates)
src/validate.py       row validation and transformation (pure functions)
src/db.py             SQLite schema
src/pipeline.py       the pipeline (read, validate, load, record run)
src/generate_data.py  reproducible synthetic data + separate answer key
src/reconcile.py      correctness checks and sample queries
src/benchmark.py      speed and memory measurement
tests/                19 automated tests
data/sample/          small hand-written input (20 rows) + expected answers
docs/                 data dictionary, design note
output/               run report, reconciliation reports, test results, benchmark
```

## Setup (Windows PowerShell)

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```
Requires Python 3.10 or newer. Only `pytest` is needed; everything else is the standard library.

## How to run

```
# 1. Small sample (20 rows, readable by hand)
python src/pipeline.py --input data/sample/orders.csv --db output/sample.db --report output/sample_run_report.json
python src/reconcile.py --db output/sample.db --expected data/sample/expected_answers.json --out output/sample_reconciliation_report.md

# 2. Larger generated run (100,000 rows, fixed seed 42)
python src/generate_data.py --rows 100000 --output data/generated
python src/pipeline.py --input data/generated/orders.csv
python src/reconcile.py --expected data/generated/expected_answers.json

# 3. Tests
python -m pytest -v

# 4. Benchmark
python src/benchmark.py --sizes 100000 500000 --chunk-sizes 500 10000
```

Useful options: `--chunk-size N`, `--db PATH`, `--report PATH`, `--customers PATH`.
The pipeline exits with code 1 if the run FAILED.

## Naming conventions

- Tables and columns: `snake_case`. Timestamps: ISO-8601 (`2026-01-15T10:30:00`).
- Every loaded row carries `run_id` and `source_file`.
- `run_id` = start time + random suffix, e.g. `20261031T021822_d9cb30`.
- `order_id` format `O0000001`, `customer_id` format `C0001`.
- `reject_id` is deterministic: first 16 hex characters of `sha1(source_file|line_number)`.

## Business rules (a row is rejected if any rule fails)

| Reason code | Rule |
|---|---|
| `malformed_row_field_count` | row has a different number of fields than the header |
| `missing_order_id` / `missing_customer_id` | required key is empty |
| `amount_not_numeric` | amount is not a finite number ("abc", empty, nan, inf) |
| `amount_negative` | amount < 0 |
| `amount_too_large` | amount > 1,000,000 |
| `invalid_currency` | not in USD, EUR, INR |
| `invalid_status` | not in NEW, SHIPPED, CANCELLED |
| `unknown_customer` | customer_id not in customers (referential integrity) |
| `invalid_timestamp` | order_ts or event_ts is not valid ISO-8601 |
| `event_before_order` | event_ts is earlier than order_ts |

Boundary decisions: an amount of exactly 0 is **valid** (e.g. a cancelled order);
exactly 1,000,000 is **valid**; 1,000,000.01 is rejected.

Derived fields: `order_date` (date part of `order_ts`) and `amount_usd`
(amount × fixed rate from `config.py`, rounded to 2 decimals).

Schema rules at file level: a missing **required column** (or a completely empty
file) FAILS the whole run with a clear reason; **extra columns** are ignored with a warning.

## Duplicates, late data and history

- Order key is `order_id`. The newest `event_ts` wins in `orders_clean`.
- A row with the same or an older `event_ts` than what is stored is counted as a `duplicate_row` (not applied).
- **Every valid version** is kept in `orders_history` (primary key `order_id + event_ts`), so history is never silently overwritten.
- Counting rule per run: `input_rows = inserted + updated + duplicate + rejected`.

## Idempotency, retry, restart and backfill

- **Rerun of the same file:** produces no new rows (all valid rows become duplicates, rejects are overwritten via their deterministic ID).
- **Retry after failure:** just run the same command again.
- **Restart after a crash:** each chunk is one transaction. A failed chunk is rolled back; earlier chunks stay committed. Rerunning skips them naturally (they are duplicates) and loads the rest. Tested in `test_partial_failure_then_retry_recovers`.
- **Backfill:** run the pipeline on older files at any time. The `event_ts` rule means old data never overwrites newer data.
- Every run is recorded in `pipeline_runs` (status, counts, duration, failure reason).

## Evidence

| What | Where |
|---|---|
| Test results (19 passed) | `output/test_results.txt` |
| Reconciliation, sample data | `output/sample_reconciliation_report.md` |
| Reconciliation, 100k rows | `output/reconciliation_report.md` |
| Run metrics | `output/run_report.json`, `output/pipeline.log` |
| Benchmark | `output/benchmark_results.md` |

Reconciliation checks: run status, count balance, no duplicate keys, referential
integrity, rejects traceable and matching, history present, and agreement with the
independent `expected_answers.json` (counts, sums, rejects by reason).

## Performance

Measured on my laptop (Python 3.13):

| rows | chunk_size | seconds | rows/sec | peak Python memory (MB) |
|---|---|---|---|---|
| 100,000 | 500 | 4.35 | 23,006 | 0.8 |
| 100,000 | 10,000 | 2.12 | 47,113 | 13.7 |
| 500,000 | 500 | 21.03 | 23,776 | 0.8 |
| 500,000 | 10,000 | 11.43 | 43,737 | 13.7 |

- **Bounded memory:** 5x more rows, same peak memory. Memory depends on chunk size, not file size.
- **Optimization 1, bigger chunks:** 500 to 10,000 rows per chunk is about 1.9x faster (fewer commits and lookups) at the cost of about 13 MB.
- **Optimization 2, upsert for customers:** loading customers with `INSERT OR REPLACE` made reruns very slow, because REPLACE deletes the row first and SQLite then re-checks all orders referencing it. Using `ON CONFLICT DO UPDATE` avoids the delete and keeps reruns fast.
- Memory is measured with `tracemalloc`, which counts Python memory only (not SQLite's internal memory).

## Assumptions

- Input is UTF-8 CSV with a header row.
- Timestamps with an offset are converted to UTC; timestamps without one are treated as UTC.
  Python 3.10 cannot parse a trailing `Z`; use 3.11+ if the data contains it.
- Currency and status are matched case-insensitively (`usd` becomes `USD`).
- All versions of an order share the same customer and amount (only status/event_ts change).
- The customers file is small enough to hold its IDs in memory.

## Known limitations

- Single machine, single process; not distributed.
- The reference customers file is fully loaded into memory.
- Rejects are keyed by `source_file + line_number`. If a file is edited and reloaded under the same name, rejects from old line numbers that no longer exist are not removed.
- `orders_clean.run_id` shows the last run that changed the row, not the first.
- No automatic detection of orders that disappear from later files (no delete handling).

## Possible next steps

- Write curated output as Parquet and partition by `order_date`.
- Schedule with Airflow/cron; add alerting when a run FAILS or the reject rate spikes.
- Move to PostgreSQL or a warehouse; use Spark/Dask for much larger inputs.
- Add a reject-rate threshold that fails the run automatically.
- Data-quality dashboard on top of `pipeline_runs` and `orders_rejects`.