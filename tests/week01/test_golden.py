"""Independent database oracle; deliberately does not call the metric service."""

from datetime import timedelta

from app.config import ANCHOR, LAG
from app.db import reader
from sqlalchemy import text


def test_golden_sql():
    end = ANCHOR - LAG
    with reader.connect() as db:

        def counts(start, stop, channel=None):
            return tuple(
                db.execute(
                    text("""
                SELECT count(*), count(*) FILTER (WHERE status='SUCCESS'),
                  count(*) FILTER (WHERE status='FAILED'),
                  count(*) FILTER (WHERE error_code='redirect_timeout')
                FROM payment_attempts
                WHERE dataset_version='demo-v1' AND country_code='DE'
                  AND payment_method='Klarna' AND status IN ('SUCCESS','FAILED')
                  AND finalized_at >= :start AND finalized_at < :stop
                  AND channel=coalesce(:channel, channel)
            """),
                    dict(start=start, stop=stop, channel=channel),
                ).one()
            )

        day = timedelta(days=1)
        assert counts(end - 3 * day, end - day)[:3] == (4000, 3800, 200)
        assert counts(end - day, end)[:3] == (2000, 1784, 216)
        assert counts(end - day, end, "Android") == (1000, 850, 150, 90)
        assert counts(end - day, end, "Web")[:3] == (1000, 934, 66)
