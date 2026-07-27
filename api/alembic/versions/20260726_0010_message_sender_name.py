"""snapshot the sender name on outgoing messages

Revision ID: 20260726_0010
Revises: 20260726_0009
Create Date: 2026-07-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260726_0010"
down_revision: str | None = "20260726_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("sender_name", sa.String(length=160), nullable=True),
    )
    op.execute(
        """
        UPDATE messages AS message
        SET sender_name = app_user.name
        FROM users AS app_user
        WHERE message.sender_user_id = app_user.id
          AND message.direction = 'outgoing'
        """
    )


def downgrade() -> None:
    op.drop_column("messages", "sender_name")
