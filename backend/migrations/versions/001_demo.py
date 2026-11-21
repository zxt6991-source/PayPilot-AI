"""Initial DEMO schema and least-privilege grants."""

from alembic import op
from app.db import metadata

revision = "001_demo"
down_revision = None


def upgrade():
    metadata.create_all(op.get_bind())
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("GRANT USAGE ON SCHEMA public TO metric_reader, app_user")
    op.execute(
        "GRANT SELECT ON payment_attempts, release_events, knowledge_documents, knowledge_chunks TO metric_reader"
    )
    op.execute("""GRANT SELECT, INSERT, UPDATE ON diagnosis_tasks, agent_runs, agent_steps,
        agent_events, tool_invocations, diagnosis_evidence, diagnosis_reports, diagnosis_feedback TO app_user""")


def downgrade():
    metadata.drop_all(op.get_bind())
