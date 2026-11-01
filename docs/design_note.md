# Design and trade-off note

## Goal
Process a large CSV without loading it into memory, with correct output, visible
data-quality problems, and safe reruns.

## Key decisions

**Chunked streaming with the standard `csv` module.** The file is read row by row
and grouped into chunks (default 10,000 rows), so memory depends on chunk size, not
file size. I chose `csv` over pandas because it gives exact line numbers for
reject traceability and handles rows with the wrong number of fields without crashing.

**SQLite as the target.** No installation or credentials, supports transactions,
upserts and foreign keys, so the project runs anywhere. Trade-off: single writer and
single machine.

**One transaction per chunk.** A crash loses at most the current chunk. Earlier
chunks stay committed and a rerun simply continues, because already-loaded rows
become harmless duplicates.

**Idempotency by design.** Orders use an upsert guarded by `event_ts`
(newer wins). The history table's key is `order_id + event_ts`. Rejects use a
deterministic ID. Rerunning the same file changes nothing.

**Quarantine instead of dropping.** Every bad row is stored with source file, line
number, raw content and a reason code, so nothing disappears silently.

**History kept separately.** `orders_clean` shows the current state; `orders_history`
keeps every valid version, so change history is preserved.

**Independent answer key.** The generator writes `expected_answers.json` separately.
The pipeline never reads it; the reconciliation compares against it afterwards.

## Performance
Larger chunks were about 1.9x faster at about 13 MB extra memory. Memory stayed flat
when rows grew 5x. Replacing `INSERT OR REPLACE` with an upsert for customers
removed a hidden cost (REPLACE deletes and re-checks every referencing order).

## Trade-offs and limitations
- Not distributed; throughput is limited by one process and SQLite.
- Customer IDs are held in memory (fine for thousands or millions, not billions).
- Rejects are keyed by file name and line number, so editing a file in place can
  leave stale rejects.
- `tracemalloc` measures Python memory only.

## Next steps
Parquet output, orchestration (Airflow), a reject-rate threshold that fails the run,
a warehouse target, and Spark for inputs beyond a single machine.