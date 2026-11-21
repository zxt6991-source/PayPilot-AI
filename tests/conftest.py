import time

import pytest
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with TestClient(app) as session:
        yield session


def wait_run(client, tid):
    for _ in range(300):
        res = client.get("/api/diagnoses/" + tid)
        res.raise_for_status()
        r = res.json()
        if r["state"] in {
            "COMPLETED",
            "FAILED",
            "CLARIFYING",
            "INSUFFICIENT_DATA",
            "CANCELLED",
        }:
            return r
        time.sleep(0.02)
    raise AssertionError("run timed out")
