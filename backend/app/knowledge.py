import hashlib
import re
from datetime import datetime

from sqlalchemy import select

from app.config import ANCHOR, RANKER, ROOT
from app.db import chunks, documents, reader


def ingest(conn):
    for path in sorted((ROOT / "data/kb").glob("*.md")):
        title, *parts = re.split(r"^## ", path.read_text(), flags=re.M)
        scope = (
            {"country_code": "DE", "payment_method": "Klarna", "channel": "Android"}
            if path.stem == "KB-001"
            else {}
        )
        conn.execute(
            documents.insert().values(
                document_id=path.stem,
                title=title.strip()[2:],
                source="PayPilot 自编 DEMO 文档",
                version="kb-v1",
                updated_at=ANCHOR,
                scope=scope,
                is_active=True,
            )
        )
        for i, part in enumerate(parts):
            heading, content = part.strip().split("\n", 1)
            digest = hashlib.sha256(part.encode()).hexdigest()[:12]
            conn.execute(
                chunks.insert().values(
                    chunk_id=f"{path.stem}-{digest}",
                    document_id=path.stem,
                    chunk_order=i,
                    location=heading,
                    content=content,
                )
            )


def library():
    query = (
        select(documents, chunks.c.chunk_id, chunks.c.content, chunks.c.location)
        .join(chunks)
        .where(documents.c.is_active)
        .order_by(documents.c.document_id, chunks.c.chunk_order)
    )
    with reader.connect() as db:
        return [dict(row, updated_at=row.updated_at.isoformat()) for row in db.execute(query).mappings()]


def search(query, scope):
    keywords = (
        "redirect_timeout",
        "webview",
        "deep link",
        "回跳",
        "psr",
        "成功率",
        "分母",
        "pending",
        "cancelled",
        "版本",
        "sdk",
        "发布",
        "issuer_declined",
        "network_error",
        "错误分布",
        "错误码",
    )
    ranked = []
    at = datetime.fromisoformat(str(scope["as_of"])) if scope.get("as_of") else ANCHOR
    for doc in library():
        if datetime.fromisoformat(doc["updated_at"]) > at:
            continue
        expires = doc["scope"].get("valid_until")
        if expires and datetime.fromisoformat(expires) <= at:
            continue
        if any(
            scope.get(k) and scope[k] != doc["scope"][k]
            for k in ("channel", "payment_method", "country_code")
            if k in doc["scope"]
        ):
            continue
        if re.search(r"忽略.{0,8}(指令|规则)|ignore.{0,15}instructions", doc["content"], re.IGNORECASE):
            continue
        body = (doc["title"] + " " + doc["content"]).lower()
        if RANKER == "v0.4":
            body += " " + doc["location"].lower()
        score = sum((5 if "_" in term else 1) for term in keywords if term in query.lower() and term in body)
        if score:
            ranked.append((score, doc))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["chunk_id"]))
    hits = [doc for _, doc in ranked[:3]]
    claims = {}
    for hit in hits:
        key = hit["scope"].get("claim_key")
        if key:
            claims.setdefault(key, set()).add(hit["scope"].get("claim_value"))
    conflict = any(len(values) > 1 for values in claims.values())
    return {"status": "CONFLICT" if conflict else "MATCH" if hits else "NO_EVIDENCE", "hits": hits}
