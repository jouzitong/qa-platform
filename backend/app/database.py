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
        if "api_definitions" not in inspector.get_table_names():
            return
        columns = {column["name"] for column in inspector.get_columns("api_definitions")}
        if "template_id" not in columns:
            connection.exec_driver_sql(
                "ALTER TABLE api_definitions ADD COLUMN template_id VARCHAR(36)"
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
