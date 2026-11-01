"""Central settings. Change values here instead of hunting through the code."""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BASE_DIR / "output" / "orders.db"
DEFAULT_REPORT_PATH = BASE_DIR / "output" / "run_report.json"
DEFAULT_LOG_PATH = BASE_DIR / "output" / "pipeline.log"

# How many data rows are held in memory at once (this bounds memory).
CHUNK_SIZE = 10_000

# Columns the orders file MUST have. Extra columns are ignored with a warning.
REQUIRED_ORDER_COLUMNS = [
    "order_id", "customer_id", "order_ts", "amount",
    "currency", "status", "event_ts",
]
REQUIRED_CUSTOMER_COLUMNS = ["customer_id", "customer_name", "country", "signup_date"]

ALLOWED_CURRENCIES = {"USD", "EUR", "INR"}
ALLOWED_STATUSES = {"NEW", "SHIPPED", "CANCELLED"}

# Fixed exchange rates (to USD) so the transformation is deterministic.
FX_TO_USD = {"USD": 1.0, "EUR": 1.08, "INR": 0.012}

MAX_AMOUNT = 1_000_000.00  # business rule: larger amounts are errors