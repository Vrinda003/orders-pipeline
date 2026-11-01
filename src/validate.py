"""Row-level validation and transformation. Pure functions: easy to test."""
import math
from datetime import datetime, timezone

import config


class SchemaError(Exception):
    """Raised when the input file's structure is unusable (run must FAIL)."""


def check_header(columns, required, logger=None):
    """Stop the run if a required column is missing; warn about extras."""
    missing = [c for c in required if c not in columns]
    if missing:
        raise SchemaError(f"missing required column(s): {', '.join(missing)}")
    extra = [c for c in columns if c not in required]
    if extra and logger:
        logger.warning("Ignoring unexpected extra column(s): %s", extra)


def parse_ts(value):
    """Parse ISO-8601 into a naive UTC datetime. Raises ValueError."""
    dt = datetime.fromisoformat(value.strip())
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_amount(value):
    """Return a finite float or raise ValueError."""
    amount = float(value)          # "abc" or "" raises ValueError
    if not math.isfinite(amount):  # rejects "nan" and "inf"
        raise ValueError("amount not finite")
    return amount


def validate_row(rec, valid_customers):
    """Return None if good, otherwise a short reject-reason string."""
    if not (rec.get("order_id") or "").strip():
        return "missing_order_id"
    if not (rec.get("customer_id") or "").strip():
        return "missing_customer_id"
    try:
        amount = parse_amount(rec["amount"])
    except (ValueError, TypeError):
        return "amount_not_numeric"
    if amount < 0:
        return "amount_negative"
    if amount > config.MAX_AMOUNT:
        return "amount_too_large"
    if rec["currency"].strip().upper() not in config.ALLOWED_CURRENCIES:
        return "invalid_currency"
    if rec["status"].strip().upper() not in config.ALLOWED_STATUSES:
        return "invalid_status"
    if rec["customer_id"].strip() not in valid_customers:
        return "unknown_customer"
    try:
        order_ts = parse_ts(rec["order_ts"])
        event_ts = parse_ts(rec["event_ts"])
    except (ValueError, TypeError):
        return "invalid_timestamp"
    if event_ts < order_ts:  # domain rule: event can't precede its order
        return "event_before_order"
    return None


def transform_row(rec):
    """Turn a VALID raw row into a clean, typed record with derived fields."""
    order_ts = parse_ts(rec["order_ts"])
    event_ts = parse_ts(rec["event_ts"])
    amount = round(parse_amount(rec["amount"]), 2)
    currency = rec["currency"].strip().upper()
    return {
        "order_id": rec["order_id"].strip(),
        "customer_id": rec["customer_id"].strip(),
        "order_ts": order_ts.isoformat(timespec="seconds"),
        "order_date": order_ts.date().isoformat(),                    # derived
        "amount": amount,
        "currency": currency,
        "amount_usd": round(amount * config.FX_TO_USD[currency], 2),  # derived
        "status": rec["status"].strip().upper(),
        "event_ts": event_ts.isoformat(timespec="seconds"),
    }