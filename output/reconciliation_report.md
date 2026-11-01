# Reconciliation report

| Check | Result | Detail |
|---|---|---|
| latest run status is SUCCESS | PASS | run 20261101T213230_03ad65: SUCCESS |
| input = inserted + updated + duplicate + rejected | PASS | 100000 vs 0+0+98058+1942 = 100000 |
| no duplicate order_id in orders_clean | PASS | 0 duplicated ids |
| every order has a known customer (referential integrity) | PASS | 0 orphan orders |
| rejects table matches run's rejected count | PASS | 1942 vs 1942 |
| every current order has a matching history row | PASS | 0 without history |
| clean order count matches expected_answers | PASS | 95088 vs 95088 |
| sum(amount) matches expected_answers | PASS | 985531985.15 vs 985531985.15 |
| rejects by reason match expected_answers | PASS | {'amount_negative': 176, 'amount_not_numeric': 243, 'event_before_order': 221, 'invalid_currency': 213, 'invalid_status': 221, 'invalid_timestamp': 211, 'malformed_row_field_count': 232, 'missing_order_id': 229, 'unknown_customer': 196} vs {'missing_order_id': 229, 'amount_not_numeric': 243, 'amount_negative': 176, 'invalid_currency': 213, 'invalid_status': 221, 'unknown_customer': 196, 'invalid_timestamp': 211, 'event_before_order': 221, 'malformed_row_field_count': 232} |
| input row count matches expected_answers | PASS | 100000 vs 100000 |

# Sample queries

## Revenue (USD) by customer country

| country | orders | revenue_usd |
|---|---|---|
| IN | 19245 | 154148060.68 |
| GB | 19329 | 145221262.84 |
| FR | 19896 | 144539895.13 |
| DE | 18000 | 119518416.11 |
| US | 18618 | 112330068.81 |

## Orders per status

| status | orders |
|---|---|
| CANCELLED | 32022 |
| NEW | 31637 |
| SHIPPED | 31429 |

## Top 5 customers by revenue (USD)

| customer_id | revenue_usd |
|---|---|
| C0833 | 4259359.14 |
| C0535 | 4254232.88 |
| C0484 | 4200846.52 |
| C0037 | 4180462.97 |
| C0551 | 4178750.5 |

## Rejects by reason

| reject_reason | n |
|---|---|
| amount_not_numeric | 243 |
| malformed_row_field_count | 232 |
| missing_order_id | 229 |
| invalid_status | 221 |
| event_before_order | 221 |
| invalid_currency | 213 |
| invalid_timestamp | 211 |
| unknown_customer | 196 |
| amount_negative | 176 |
