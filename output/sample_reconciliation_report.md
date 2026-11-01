# Reconciliation report

| Check | Result | Detail |
|---|---|---|
| latest run status is SUCCESS | PASS | run 20261101T210357_d59209: SUCCESS |
| input = inserted + updated + duplicate + rejected | PASS | 20 vs 0+0+11+9 = 20 |
| no duplicate order_id in orders_clean | PASS | 0 duplicated ids |
| every order has a known customer (referential integrity) | PASS | 0 orphan orders |
| rejects table matches run's rejected count | PASS | 9 vs 9 |
| every current order has a matching history row | PASS | 0 without history |
| clean order count matches expected_answers | PASS | 8 vs 8 |
| sum(amount) matches expected_answers | PASS | 5317.50 vs 5317.50 |
| rejects by reason match expected_answers | PASS | {'amount_negative': 1, 'amount_not_numeric': 1, 'event_before_order': 1, 'invalid_currency': 1, 'invalid_status': 1, 'invalid_timestamp': 1, 'malformed_row_field_count': 1, 'missing_order_id': 1, 'unknown_customer': 1} vs {'missing_order_id': 1, 'amount_not_numeric': 1, 'amount_negative': 1, 'unknown_customer': 1, 'invalid_timestamp': 1, 'invalid_currency': 1, 'invalid_status': 1, 'event_before_order': 1, 'malformed_row_field_count': 1} |
| input row count matches expected_answers | PASS | 20 vs 20 |

# Sample queries

## Revenue (USD) by customer country

| country | orders | revenue_usd |
|---|---|---|
| DE | 2 | 168.0 |
| US | 2 | 85.5 |
| IN | 2 | 81.0 |
| FR | 2 | 57.0 |

## Orders per status

| status | orders |
|---|---|
| SHIPPED | 4 |
| NEW | 3 |
| CANCELLED | 1 |

## Top 5 customers by revenue (USD)

| customer_id | revenue_usd |
|---|---|
| C0002 | 168.0 |
| C0001 | 85.5 |
| C0003 | 81.0 |
| C0004 | 57.0 |

## Rejects by reason

| reject_reason | n |
|---|---|
| unknown_customer | 1 |
| missing_order_id | 1 |
| malformed_row_field_count | 1 |
| invalid_timestamp | 1 |
| invalid_status | 1 |
| invalid_currency | 1 |
| event_before_order | 1 |
| amount_not_numeric | 1 |
| amount_negative | 1 |
