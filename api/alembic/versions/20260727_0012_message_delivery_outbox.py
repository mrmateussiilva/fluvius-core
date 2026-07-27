"""add reliable message delivery outbox

Revision ID: 20260727_0012
Revises: 20260727_0011
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0012"
down_revision: str | None = "20260727_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "message_deliveries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.Uuid(),
            sa.ForeignKey("messages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="queued",
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            server_default="4",
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("rq_job_id", sa.String(length=255)),
        sa.Column("last_error", sa.String(length=500)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN "
            "('queued', 'enqueued', 'processing', 'retry_wait', 'completed', 'failed')",
            name="ck_message_deliveries_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 "
            "AND attempt_count <= max_attempts",
            name="ck_message_deliveries_attempts",
        ),
        sa.UniqueConstraint(
            "message_id",
            name="uq_message_deliveries_message_id",
        ),
    )
    op.create_index(
        "ix_message_deliveries_tenant_id",
        "message_deliveries",
        ["tenant_id"],
    )
    op.create_index(
        "ix_message_deliveries_message_id",
        "message_deliveries",
        ["message_id"],
    )
    op.create_index(
        "ix_message_deliveries_status",
        "message_deliveries",
        ["status"],
    )
    op.create_index(
        "ix_message_deliveries_tenant_due",
        "message_deliveries",
        ["tenant_id", "status", "next_attempt_at"],
    )
    op.execute(
        """
        INSERT INTO message_deliveries (
            id,
            tenant_id,
            message_id,
            status,
            attempt_count,
            max_attempts,
            next_attempt_at,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            tenant_id,
            id,
            'queued',
            0,
            4,
            now(),
            now(),
            now()
        FROM messages
        WHERE direction = 'outgoing' AND status = 'pending'
        """
    )


def downgrade() -> None:
    op.drop_table("message_deliveries")
