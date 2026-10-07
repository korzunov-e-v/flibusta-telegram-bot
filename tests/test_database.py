from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from src.database import crud
from src.database.models import SentEmail, User

ROOT = Path(__file__).resolve().parent.parent


def _sql(stmt: object) -> str:
    compiled = stmt.compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]

    return " ".join(str(compiled).split())


def test_select_email_only_verified() -> None:
    sql = _sql(crud.select_email_stmt(1))

    assert sql.startswith("SELECT users.email FROM users WHERE users.user_id = ")
    assert "users.email_verified IS true" in sql


def test_upsert_email() -> None:
    sql = _sql(crud.upsert_email_stmt(1, "a@b.c"))

    assert sql.startswith("INSERT INTO users (user_id, email, email_verified) VALUES")
    assert "ON CONFLICT (user_id) DO UPDATE SET" in sql
    assert "email = excluded.email" in sql
    assert "email_verified = " in sql
    assert "updated_at = now()" in sql


def test_count_and_purge_sent_emails() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)

    count_sql = _sql(crud.count_sent_emails_stmt(1, crud.KIND_BOOK, since))
    purge_sql = _sql(crud.purge_sent_emails_stmt(1, since))

    assert count_sql.startswith("SELECT count(*) AS count_1 FROM sent_emails WHERE")
    assert "sent_emails.kind = " in count_sql and "sent_emails.created_at >= " in count_sql
    assert purge_sql.startswith("DELETE FROM sent_emails WHERE sent_emails.user_id = ")
    assert "sent_emails.created_at < " in purge_sql


@pytest.mark.parametrize("model", [User, SentEmail])
def test_tables_compile_for_postgres(model: type) -> None:
    sql = _sql(CreateTable(model.__table__))  # type: ignore[attr-defined]

    assert "TIMESTAMP WITH TIME ZONE" in sql


def test_new_email_is_unverified_by_default() -> None:
    assert "email_verified BOOLEAN DEFAULT false NOT NULL" in _sql(CreateTable(User.__table__))  # type: ignore[arg-type]


def test_migrations_form_single_chain() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    script = ScriptDirectory.from_config(config)

    assert len(script.get_heads()) == 1
    assert [rev.revision for rev in script.walk_revisions()][-1] == "0d9d095c5df6"
