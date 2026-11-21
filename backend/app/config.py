import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VERSION = "demo-v1"
RANKER = os.getenv("PAYPILOT_RANKER", "v0.4")
if RANKER not in ("v0.3", "v0.4"):
    raise ValueError("unsupported ranker")
ANCHOR = datetime(2026, 11, 16, 10, tzinfo=timezone.utc)
LAG = timedelta(minutes=5)
DB_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://app_user:demo_app@localhost:55432/paypilot")
READ_URL = os.getenv(
    "PAYMENT_READONLY_DATABASE_URL", "postgresql+psycopg://metric_reader:demo_read@localhost:55432/paypilot"
)
ADMIN_URL = os.getenv(
    "MIGRATION_DATABASE_URL", "postgresql+psycopg://postgres:demo_admin@localhost:55432/paypilot"
)
