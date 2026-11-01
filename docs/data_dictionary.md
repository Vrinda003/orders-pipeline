# Data dictionary

## Source files

### customers.csv (reference data)
| Column | Type | Nullable | Description |
|---|---|---|---|
| customer_id | text | no | Key, e.g. `C0001` |
| customer_name | text | yes | Display name |
| country | text | yes | Country code |
| signup_date | text (date) | yes | ISO-8601 date |

### orders.csv (large input, one row per order event)
| Column | Type | Nullable | Description |
|---|---|---|---|
| order_id | text | no | Order key, e.g. `O0000001`. Not unique in the file: an order can appear several times (versions) |
| customer_id | text | no | Must exist in customers |
| order_ts | text (ISO-8601) | no | When the order was placed |
| amount | decimal | no | 0 to 1,000,000 inclusive |
| currency | text | no | USD, EUR or INR |
| status | text | no | NEW, SHIPPED or CANCELLED |
| event_ts | text (ISO-8601) | no | When this version of the order was recorded; must be >= order_ts |

Grain: one row = one version (event) of one order.

## Target tables (SQLite)

### customers
| Column | Type | Null | Key | Description |
|---|---|---|---|---|
| customer_id | TEXT | no | PK | Customer key |
| customer_name | TEXT | yes | | |
| country | TEXT | yes | | |
| signup_date | TEXT | yes | | |

### orders_clean (current state, one row per order)
| Column | Type | Null | Key | Description |
|---|---|---|---|---|
| order_id | TEXT | no | PK | Unique order key |
| customer_id | TEXT | no | FK customers | Referential integrity |
| order_ts | TEXT | no | | ISO-8601, UTC |
| order_date | TEXT | no | | Derived: date of order_ts |
| amount | REAL | no | | Check: >= 0 |
| currency | TEXT | no | | USD / EUR / INR |
| amount_usd | REAL | no | | Derived: amount x fixed rate |
| status | TEXT | no | | NEW / SHIPPED / CANCELLED |
| event_ts | TEXT | no | | Version timestamp; newest wins |
| run_id | TEXT | no | | Run that last wrote this row |
| source_file | TEXT | no | | File it came from |

### orders_history (append-only, every valid version)
| Column | Type | Null | Key | Description |
|---|---|---|---|---|
| order_id | TEXT | no | PK (part 1) | |
| event_ts | TEXT | no | PK (part 2) | Makes reruns safe |
| customer_id, order_ts, amount, currency, status | | no | | As in the source |
| run_id, source_file | TEXT | no | | Lineage |

### orders_rejects (quarantine)
| Column | Type | Null | Key | Description |
|---|---|---|---|---|
| reject_id | TEXT | no | PK | `sha1(source_file|line_number)[:16]`, deterministic |
| run_id | TEXT | no | | Run that rejected it |
| source_file | TEXT | no | | Traceability |
| line_number | INTEGER | no | | Line in the source file |
| raw_record | TEXT | no | | Original fields as a JSON list |
| reject_reason | TEXT | no | | Reason code (see README) |

### pipeline_runs (one row per run)
| Column | Type | Null | Description |
|---|---|---|---|
| run_id | TEXT (PK) | no | Start time + random suffix |
| source_file | TEXT | yes | Input file name |
| start_time, end_time | TEXT | no / yes | ISO-8601 |
| status | TEXT | no | RUNNING, SUCCESS or FAILED |
| input_rows | INTEGER | | Data rows read |
| valid_rows | INTEGER | | inserted + updated + duplicate |
| inserted_rows / updated_rows / duplicate_rows | INTEGER | | New / replaced by newer / not applied |
| rejected_rows | INTEGER | | Quarantined rows |
| reject_breakdown | TEXT | | JSON: counts by reason |
| chunk_size | INTEGER | | Chunk size used |
| duration_seconds | REAL | | |
| failure_reason | TEXT | yes | Set when FAILED |

## Relationships
`orders_clean.customer_id` references `customers.customer_id`.
`orders_history` holds all versions of each `orders_clean.order_id`.
`orders_rejects` and all loaded tables link to `pipeline_runs` through `run_id`.