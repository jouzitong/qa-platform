from collections.abc import Generator

from sqlalchemy import create_engine, event, inspect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def get_session() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        yield session


def ensure_schema_compatibility() -> None:
    """Add MVP-era columns that create_all cannot apply to an existing SQLite database."""
    if not settings.database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())

        asset_key_tables = {
            "api_definitions": "uq_api_definition_project_key",
            "assertion_definitions": "uq_assertion_definition_project_key",
            "test_flows": "uq_test_flow_project_key",
        }
        for table_name, index_name in asset_key_tables.items():
            if table_name not in tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            added_key = "key" not in columns
            if added_key:
                connection.exec_driver_sql(
                    f"ALTER TABLE {table_name} ADD COLUMN key VARCHAR(120)"
                )
            connection.exec_driver_sql(
                f"UPDATE {table_name} SET key = id WHERE key IS NULL OR key = ''"
            )
            if added_key:
                connection.exec_driver_sql(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} "
                    f"ON {table_name} (project_id, key)"
                )

        if "api_definitions" not in tables:
            return
        columns = {column["name"] for column in inspector.get_columns("api_definitions")}
        if "template_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE api_definitions ADD COLUMN template_id VARCHAR(36)"
            )
        if "assertion_profile_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE api_definitions ADD COLUMN assertion_profile_id VARCHAR(36)"
            )
        if "response_variants" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE api_definitions ADD COLUMN response_variants JSON DEFAULT '[]'"
            )
        if "success_contract" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE api_definitions ADD COLUMN success_contract JSON DEFAULT '{}'"
            )
        if "api_templates" in inspector.get_table_names():
            template_columns = {
                column["name"] for column in inspector.get_columns("api_templates")
            }
            if "parameters" not in template_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE api_templates ADD COLUMN parameters JSON DEFAULT '[]'"
                )
            if "examples" not in template_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE api_templates ADD COLUMN examples JSON DEFAULT '[]'"
                )
        if "step_runs" in inspector.get_table_names():
            step_run_columns = {
                column["name"] for column in inspector.get_columns("step_runs")
            }
            if "assertion_results" not in step_run_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE step_runs ADD COLUMN assertion_results JSON DEFAULT '[]'"
                )
