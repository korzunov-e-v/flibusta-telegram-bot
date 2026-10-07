from datetime import UTC, datetime, timedelta

from sqlalchemy import Delete, Select, delete, func, select
from sqlalchemy.dialects.postgresql import Insert, insert

from src.database.models import SentEmail, User
from src.database.session import SessionLocal

KIND_BOOK = "book"
KIND_CODE = "code"

SENT_EMAILS_RETENTION = timedelta(days=30)


def select_email_stmt(user_id: int) -> Select[str]:
    return select(User.email).where(User.user_id == user_id, User.email_verified.is_(True))


def upsert_email_stmt(user_id: int, email: str) -> Insert:
    stmt = insert(User).values(user_id=user_id, email=email, email_verified=True)

    return stmt.on_conflict_do_update(
        index_elements=[User.user_id],
        set_={
            "email": stmt.excluded.email,
            "email_verified": True,
            "updated_at": func.now(),
        },
    )


def count_sent_emails_stmt(user_id: int, kind: str, since: datetime) -> Select[int]:
    return (
        select(func.count())
        .select_from(SentEmail)
        .where(
            SentEmail.user_id == user_id,
            SentEmail.kind == kind,
            SentEmail.created_at >= since,
        )
    )


def purge_sent_emails_stmt(user_id: int, before: datetime) -> Delete:
    return delete(SentEmail).where(SentEmail.user_id == user_id, SentEmail.created_at < before)


async def get_email(user_id: int) -> str | None:
    """Возвращает только подтверждённый адрес."""
    async with SessionLocal() as session:
        return await session.scalar(select_email_stmt(user_id))


async def set_email(user_id: int, email: str) -> None:
    """Сохраняет адрес как подтверждённый — вызывать только после проверки кода."""
    async with SessionLocal() as session:
        await session.execute(upsert_email_stmt(user_id, email))
        await session.commit()


async def log_sent_email(user_id: int, kind: str) -> None:
    now = datetime.now(UTC)

    async with SessionLocal() as session:
        await session.execute(purge_sent_emails_stmt(user_id, now - SENT_EMAILS_RETENTION))
        session.add(SentEmail(user_id=user_id, kind=kind))
        await session.commit()


async def count_sent_emails(user_id: int, kind: str, period: timedelta) -> int:
    since = datetime.now(UTC) - period

    async with SessionLocal() as session:
        result = await session.execute(count_sent_emails_stmt(user_id, kind, since))

    return result.scalar_one()
