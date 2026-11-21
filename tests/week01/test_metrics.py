import pytest
from app.db import reader, writer
from app.schemas import Scope
from app.services import metric_service as m
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError


def test_sql_service():
    s = Scope()
    assert m.compare(s)["delta_pp"] == -5.8
    assert m.metrics(s)["psr"] == 0.892
    assert m.compare(s)["baseline"]["psr"] == 0.95
    assert [r["psr"] for r in m.breakdown(s)["rows"]] == [0.85, 0.934]
    assert sum(r["valid_attempts"] for r in m.trend(s)["rows"]) == 2000
    row = m.errors(Scope(channel="Android"))["rows"][0]
    assert row == {
        "error_code": "redirect_timeout",
        "count": 90,
        "share_of_failures": 0.6,
    }
    assert m.metrics(Scope(channel="iOS"))["psr"] is None


@pytest.mark.parametrize("engine", [reader, writer])
def test_payment_write_denied(engine):
    with engine.begin() as conn:
        assert not conn.scalar(text("select has_table_privilege(current_user,'payment_attempts','UPDATE')"))
    with pytest.raises(DBAPIError), engine.begin() as conn:
        conn.execute(text("update payment_attempts set status='FAILED' where false"))
