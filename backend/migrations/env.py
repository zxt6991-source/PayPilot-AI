from alembic import context
from app.config import ADMIN_URL
from app.db import metadata
from sqlalchemy import create_engine

with create_engine(ADMIN_URL).begin() as conn:
    context.configure(connection=conn, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()
