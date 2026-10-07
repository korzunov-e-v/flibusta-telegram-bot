"""email verification and limits

Revision ID: 7c1e4a9b2f31
Revises: 0d9d095c5df6
Create Date: 2026-10-07 20:30:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7c1e4a9b2f31"
down_revision: Union[str, Sequence[str], None] = "0d9d095c5df6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # server_default=true заполняет существующие строки: адреса, заданные до
    # появления подтверждения, считаются подтверждёнными. Затем дефолт меняется на false.
    op.add_column(
        "users",
        sa.Column("email_verified", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.alter_column("users", "email_verified", server_default=sa.text("false"))

    op.create_table(
        "sent_emails",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sent_emails_user_id_created_at", "sent_emails", ["user_id", "created_at"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_sent_emails_user_id_created_at", table_name="sent_emails")
    op.drop_table("sent_emails")
    op.drop_column("users", "email_verified")
