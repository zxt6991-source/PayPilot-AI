"""Generate an immutable demo-v1 batch in a single transaction."""

import argparse
import hashlib
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.config import ADMIN_URL, ANCHOR, LAG, ROOT, VERSION
from app.db import documents, payments, releases
from app.knowledge import ingest
from sqlalchemy import create_engine, func, select, text


def generate():
    rng = random.Random(20261116)
    end = ANCHOR - LAG
    for i in range(30000):
        country, method = "DE", "Klarna"
        channel = ("Android", "Web")[i % 2]
        if i < 4000:
            age = rng.randrange(86400, 259200)
            status = "SUCCESS" if i < 3800 else "FAILED"
            error = "issuer_declined"
        elif i < 6000:
            index = (i - 4000) // 2
            age = rng.randrange(86400)
            status = "SUCCESS" if index < (850 if channel == "Android" else 934) else "FAILED"
            error = "redirect_timeout" if channel == "Android" and index < 940 else "issuer_declined"
        else:
            country, method = rng.choice(
                [
                    ("DE", "Card"),
                    ("GB", "Card"),
                    ("GB", "Klarna"),
                    ("SG", "PayPal"),
                    ("SG", "Card"),
                ]
            )
            channel = rng.choice(["Android", "Web", "iOS"])
            age = rng.randrange(86400 * (3 if i % 2 else 90))
            status = rng.choices(["SUCCESS", "FAILED", "PENDING", "CANCELLED"], [90, 7, 2, 1])[0]
            error = rng.choice(["issuer_declined", "network_error"])
        when = end - timedelta(seconds=age + 1)
        yield dict(
            payment_attempt_id=f"demo-{i:05}",
            order_id_hash=hashlib.sha256(f"demo-order-{i // 2}".encode()).hexdigest()[:20],
            created_at=when - timedelta(seconds=20),
            finalized_at=None if status == "PENDING" else when,
            country_code=country,
            payment_method=method,
            channel=channel,
            app_version=rng.choice(["2.4", "2.5"]) if channel != "Web" else "web",
            status=status,
            error_code=error if status == "FAILED" else None,
            failure_stage="authorization"
            if status == "FAILED" and error == "issuer_declined"
            else ("client" if status == "FAILED" else None),
            dataset_version=VERSION,
            environment="DEMO",
            seed_batch_id="seed-20261116",
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--confirm-demo-reset", action="store_true")
    parser.add_argument("--seed", type=int, choices=[20261116], default=20261116)
    parser.add_argument("--count", type=int, choices=[30000], default=30000)
    parser.add_argument(
        "--anchor-date",
        choices=["2026-11-16T10:00:00Z"],
        default="2026-11-16T10:00:00Z",
    )
    args = parser.parse_args()
    if args.reset and not args.confirm_demo_reset:
        parser.error("--reset requires --confirm-demo-reset")
    rows = list(generate())
    digest = hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()
    with create_engine(ADMIN_URL).begin() as db:
        db.execute(text("select pg_advisory_xact_lock(20261116)"))
        exists = db.scalar(
            select(func.count()).select_from(payments).where(payments.c.dataset_version == VERSION)
        )
        if exists and not args.reset:
            if exists != len(rows):
                raise RuntimeError("Incomplete seed batch")
            print("demo-v1 already present")
            return
        if exists:
            db.execute(payments.delete().where(payments.c.dataset_version == VERSION))
            db.execute(releases.delete().where(releases.c.dataset_version == VERSION))
        for i in range(0, len(rows), 1000):
            db.execute(payments.insert(), rows[i : i + 1000])
        db.execute(
            releases.insert().values(
                release_id="demo-release-2.5",
                channel="Android",
                app_version="2.5",
                released_at=ANCHOR - timedelta(hours=24),
                description="Android 灰度扩量，相关性待验证",
                dataset_version=VERSION,
            )
        )
        if not db.scalar(select(func.count()).select_from(documents)):
            ingest(db)
    end = ANCHOR - LAG
    manifest = dict(
        seed=args.seed,
        anchor_at_utc=args.anchor_date,
        dataset_version=VERSION,
        total_rows=len(rows),
        golden_scope={"country_code": "DE", "payment_method": "Klarna"},
        golden_windows={
            "baseline": [
                (end - timedelta(days=3)).isoformat(),
                (end - timedelta(days=1)).isoformat(),
            ],
            "current": [(end - timedelta(days=1)).isoformat(), end.isoformat()],
        },
        expected_metrics={
            "current_psr": 0.892,
            "baseline_psr": 0.95,
            "delta_pp": -5.8,
            "android_timeout_share": 0.6,
        },
        sha256=digest,
    )
    (ROOT / "data/seed_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Inserted", len(rows), "DEMO attempts", digest)


if __name__ == "__main__":
    main()
