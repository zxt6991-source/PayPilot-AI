from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.config import LAG, VERSION
from app.db import payments, reader, releases
from app.schemas import Dimension, Scope

p = payments.c
PERIODS = {"24h": 1, "7d": 7, "30d": 30}


def windows(scope):
    width = timedelta(days=PERIODS[scope.period])
    end = scope.as_of - LAG
    return (end - width, end), (end - 3 * width, end - width)


def where(scope):
    return [p.dataset_version == VERSION] + [
        p[k] == v
        for k, v in scope.model_dump().items()
        if k in {"country_code", "payment_method", "channel", "app_version"} and v is not None
    ]


def ratio(num, den):
    return float(Decimal(num) / Decimal(den)) if den else None


def delta(a, b):
    if not a["valid_attempts"] or not b["valid_attempts"]:
        return None
    return float(
        round(
            100
            * (
                Decimal(a["successful_attempts"]) / a["valid_attempts"]
                - Decimal(b["successful_attempts"]) / b["valid_attempts"]
            ),
            6,
        )
    )


def sample(n, s):
    return dict(
        valid_attempts=n,
        successful_attempts=s,
        failed_attempts=n - s,
        psr=ratio(s, n),
        quality_flags=["NO_DATA"] if not n else ["LOW_SAMPLE"] if n < 30 else [],
    )


def context(scope, window):
    return dict(
        environment="DEMO",
        data_version=VERSION,
        as_of_utc=scope.as_of.isoformat(),
        query_window={"start_at": window[0].isoformat(), "end_at": window[1].isoformat()},
        filters=scope.model_dump(mode="json"),
    )


def aggregate(scope, window, dimension=None):
    query = select(func.count(), func.count().filter(p.status == "SUCCESS")).where(
        *where(scope),
        p.status.in_(["SUCCESS", "FAILED"]),
        p.finalized_at >= window[0],
        p.finalized_at < window[1],
    )
    if dimension is not None:
        query = query.add_columns(dimension).group_by(dimension)
    with reader.connect() as db:
        rows = db.execute(query).all()
    return {r[2] if dimension is not None else "total": sample(r[0], r[1]) for r in rows}


def metrics(scope: Scope):
    window, _ = windows(scope)
    with reader.connect() as db:
        counts = dict(
            db.execute(
                select(p.status, func.count())
                .where(
                    *where(scope),
                    p.status.in_(["PENDING", "CANCELLED"]),
                    p.created_at >= window[0],
                    p.created_at < window[1],
                    (p.finalized_at.is_(None)) | (p.finalized_at <= scope.as_of),
                )
                .group_by(p.status)
            ).all()
        )
    return {
        **context(scope, window),
        **aggregate(scope, window)["total"],
        "pending": counts.get("PENDING", 0),
        "cancelled": counts.get("CANCELLED", 0),
    }


def compare(scope: Scope):
    current, baseline = windows(scope)
    a, b = aggregate(scope, current)["total"], aggregate(scope, baseline)["total"]
    return {
        **context(scope, current),
        "current": a,
        "baseline": {**context(scope, baseline), **b},
        "delta_pp": delta(a, b),
        "quality_flags": sorted(set(a["quality_flags"] + b["quality_flags"])),
    }


def breakdown(scope: Scope, dimension: Dimension = "channel"):
    if dimension not in ("channel", "app_version", "payment_method", "country_code"):
        raise ValueError("不支持的维度")
    current, baseline = windows(scope)
    a, b = [aggregate(scope, w, p[dimension]) for w in (current, baseline)]
    rows = []
    for key in sorted(a.keys() | b.keys()):
        ca, cb = a.get(key, sample(0, 0)), b.get(key, sample(0, 0))
        rows.append({"value": key, **ca, "baseline": cb, "delta_pp": delta(ca, cb)})
    return {**context(scope, current), "dimension": dimension, "rows": rows}


def errors(scope: Scope):
    window, _ = windows(scope)
    query = (
        select(p.error_code, func.count().label("n"))
        .where(*where(scope), p.status == "FAILED", p.finalized_at >= window[0], p.finalized_at < window[1])
        .group_by(p.error_code)
        .order_by(func.count().desc(), p.error_code)
    )
    with reader.connect() as db:
        rows = db.execute(query).all()
    total = sum(r.n for r in rows)
    return {
        **context(scope, window),
        "failed_attempts": total,
        "rows": [dict(error_code=code, count=n, share_of_failures=ratio(n, total)) for code, n in rows],
    }


def release_changes(scope):
    current, _ = windows(scope)
    query = select(releases).where(
        releases.c.dataset_version == VERSION,
        releases.c.released_at >= current[0],
        releases.c.released_at < current[1],
    )
    if scope.channel:
        query = query.where(releases.c.channel == scope.channel)
    if scope.app_version:
        query = query.where(releases.c.app_version == scope.app_version)
    with reader.connect() as db:
        return {
            **context(scope, current),
            "rows": [dict(r, released_at=r.released_at.isoformat()) for r in db.execute(query).mappings()],
        }


def trend(scope):
    current, _ = windows(scope)
    buckets = 12
    width = (current[1] - current[0]) / buckets
    bucket = func.floor(func.extract("epoch", p.finalized_at - current[0]) / width.total_seconds())
    query = (
        select(bucket, func.count(), func.count().filter(p.status == "SUCCESS"))
        .where(
            *where(scope),
            p.status.in_(["SUCCESS", "FAILED"]),
            p.finalized_at >= current[0],
            p.finalized_at < current[1],
        )
        .group_by(bucket)
    )
    with reader.connect() as db:
        values = {int(k): sample(n, s) for k, n, s in db.execute(query)}
    return {
        **context(scope, current),
        "rows": [
            dict(start_at=(current[0] + i * width).isoformat(), **values.get(i, sample(0, 0)))
            for i in range(buckets)
        ],
    }
