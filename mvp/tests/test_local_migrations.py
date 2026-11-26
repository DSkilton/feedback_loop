"""Local schema upgrades preserve earlier demonstration records."""
from sqlalchemy import create_engine, inspect, text

from mvp.local_migrations import upgrade_local_feedback_schema


def test_local_feedback_migration_is_repeatable_and_preserves_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'older-demo.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE mvp_feedback (id INTEGER PRIMARY KEY, status VARCHAR(30))")
        connection.exec_driver_sql("INSERT INTO mvp_feedback (id, status) VALUES (12, 'IN_PROGRESS')")
    upgrade_local_feedback_schema(engine)
    upgrade_local_feedback_schema(engine)
    columns = {item["name"] for item in inspect(engine).get_columns("mvp_feedback")}
    assert {"version", "judgement", "work_url"} <= columns
    with engine.connect() as connection:
        row = connection.execute(text("SELECT status, version, judgement, work_url FROM mvp_feedback WHERE id=12")).one()
    assert row == ("IN_PROGRESS", 1, None, "")
