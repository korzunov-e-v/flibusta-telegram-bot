import os

import psycopg
from psycopg.rows import dict_row


def get_connection():
    database_url = os.getenv("DATABASE_URL")

    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    return psycopg.connect(
        database_url,
        row_factory=dict_row,
    )


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                email TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def get_email(user_id: int) -> str | None:
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT email
            FROM users
            WHERE user_id = %s
            """,
            (user_id,),
        ).fetchone()

    return row["email"] if row else None


def set_email(user_id: int, email: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, email)
            VALUES (%s, %s)
            ON CONFLICT (user_id)
            DO UPDATE SET
                email = EXCLUDED.email,
                updated_at = NOW()
            """,
            (user_id, email),
        )
