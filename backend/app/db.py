from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy import (
    Column as C,
)

from .config import DB_URL, READ_URL

writer = create_engine(DB_URL, pool_pre_ping=True)
reader = create_engine(READ_URL, pool_pre_ping=True)
metadata = MetaData()
ts = DateTime(timezone=True)


def key(name):
    return C(name, Text, primary_key=True)


def field(name, kind=Text):
    return C(name, kind, nullable=False)


def fk(name, target):
    return C(name, Text, ForeignKey(target), nullable=False)


payments = Table(
    "payment_attempts",
    metadata,
    key("payment_attempt_id"),
    field("order_id_hash"),
    field("created_at", ts),
    C("finalized_at", ts),
    field("country_code"),
    field("payment_method"),
    field("channel"),
    field("app_version"),
    field("status"),
    C("failure_stage", Text),
    C("error_code", Text),
    field("dataset_version"),
    field("environment"),
    field("seed_batch_id"),
    CheckConstraint("environment='DEMO'"),
    CheckConstraint("status IN ('PENDING','CANCELLED','SUCCESS','FAILED')"),
    CheckConstraint("channel IN ('Web','Android','iOS')"),
    CheckConstraint("status NOT IN ('SUCCESS','FAILED') OR finalized_at IS NOT NULL"),
)
Index(
    "idx_attempts_metric",
    payments.c.dataset_version,
    payments.c.country_code,
    payments.c.payment_method,
    payments.c.finalized_at,
)
releases = Table(
    "release_events",
    metadata,
    key("release_id"),
    field("channel"),
    field("app_version"),
    field("released_at", ts),
    field("description"),
    field("dataset_version"),
)
tasks = Table(
    "diagnosis_tasks",
    metadata,
    key("task_id"),
    field("owner"),
    C("idempotency_key", Text),
    field("digest"),
    field("user_query"),
    field("filters", JSON),
    field("dataset_version"),
    field("current_run"),
    UniqueConstraint("owner", "idempotency_key"),
)
runs = Table(
    "agent_runs",
    metadata,
    key("run_id"),
    fk("task_id", "diagnosis_tasks.task_id"),
    C("parent_run", Text),
    field("state"),
    field("question"),
    field("filters", JSON),
    field("intent"),
    field("workflow_version"),
    field("model_id"),
    field("prompt_version"),
    field("step_count", Integer),
    field("started_at", ts),
    C("ended_at", ts),
    C("reason", Text),
)
steps = Table(
    "agent_steps",
    metadata,
    fk("run_id", "agent_runs.run_id"),
    field("sequence", Integer),
    field("node"),
    field("started_at", ts),
    C("ended_at", ts),
    UniqueConstraint("run_id", "sequence"),
)
events = Table(
    "agent_events",
    metadata,
    fk("run_id", "agent_runs.run_id"),
    field("sequence", Integer),
    field("event_type"),
    field("payload", JSON),
    field("created_at", ts),
    UniqueConstraint("run_id", "sequence"),
)
evidence = Table(
    "diagnosis_evidence",
    metadata,
    key("evidence_id"),
    fk("run_id", "agent_runs.run_id"),
    field("source_key"),
    field("filters", JSON),
    field("payload", JSON),
    field("data_version"),
)
calls = Table(
    "tool_invocations",
    metadata,
    key("invocation_id"),
    fk("run_id", "agent_runs.run_id"),
    field("tool_name"),
    field("input_digest"),
    field("result_status"),
    C("duration_ms", Integer),
    C("evidence_id", Text, ForeignKey("diagnosis_evidence.evidence_id")),
    UniqueConstraint("run_id", "tool_name", "input_digest"),
)
reports = Table(
    "diagnosis_reports",
    metadata,
    key("report_id"),
    fk("run_id", "agent_runs.run_id"),
    field("schema_version"),
    field("report_json", JSON),
    field("created_at", ts),
    UniqueConstraint("run_id"),
)
feedback = Table(
    "diagnosis_feedback",
    metadata,
    key("feedback_id"),
    fk("run_id", "agent_runs.run_id"),
    fk("report_id", "diagnosis_reports.report_id"),
    field("rating"),
    field("issue_tags", JSON),
    field("note"),
)
documents = Table(
    "knowledge_documents",
    metadata,
    key("document_id"),
    field("title"),
    field("source"),
    field("updated_at", ts),
    field("scope", JSON),
    field("version"),
    field("is_active", Boolean),
)
chunks = Table(
    "knowledge_chunks",
    metadata,
    key("chunk_id"),
    fk("document_id", "knowledge_documents.document_id"),
    field("chunk_order", Integer),
    field("content"),
    field("location"),
)
