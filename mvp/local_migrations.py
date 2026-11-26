"""Narrow, repeatable migrations for existing local SQLite demonstration databases."""
from sqlalchemy import inspect


def upgrade_local_feedback_schema(engine):
    inspector = inspect(engine)
    if not inspector.has_table("mvp_feedback"):
        return
    existing = {column["name"] for column in inspector.get_columns("mvp_feedback")}
    statements = {
        "version": "ALTER TABLE mvp_feedback ADD COLUMN version INTEGER NOT NULL DEFAULT 1",
        "judgement": "ALTER TABLE mvp_feedback ADD COLUMN judgement VARCHAR(30)",
        "work_url": "ALTER TABLE mvp_feedback ADD COLUMN work_url VARCHAR(500) NOT NULL DEFAULT ''",
    }
    with engine.begin() as connection:
        for column, sql in statements.items():
            if column not in existing:
                connection.exec_driver_sql(sql)
