"""add durable provider event inbox

Revision ID: 20260804_0025
Revises: 20260802_0024
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260804_0025"
down_revision: str | None = "20260802_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "provider_event_inbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider_event_id",
            sa.Uuid(),
            sa.ForeignKey("provider_events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("normalized_kind", sa.String(length=24), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=False),
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
            server_default="8",
            nullable=False,
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("rq_job_id", sa.String(length=255)),
        sa.Column("last_error", sa.String(length=500)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("media_storage_key", sa.String(length=500)),
        sa.Column("media_file_name", sa.String(length=255)),
        sa.Column("media_content_type", sa.String(length=120)),
        sa.Column("media_size_bytes", sa.BigInteger()),
        sa.Column("media_content_sha256", sa.String(length=64)),
        sa.Column("media_error", sa.String(length=500)),
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
            name="ck_provider_event_inbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 "
            "AND attempt_count <= max_attempts",
            name="ck_provider_event_inbox_attempts",
        ),
        sa.CheckConstraint(
            "normalized_kind IN ('message', 'edit')",
            name="ck_provider_event_inbox_normalized_kind",
        ),
        sa.UniqueConstraint(
            "provider_event_id",
            name="uq_provider_event_inbox_event_id",
        ),
    )
    op.create_index(
        "ix_provider_event_inbox_tenant_id",
        "provider_event_inbox",
        ["tenant_id"],
    )
    op.create_index(
        "ix_provider_event_inbox_status",
        "provider_event_inbox",
        ["status"],
    )
    op.create_index(
        "ix_provider_event_inbox_tenant_due",
        "provider_event_inbox",
        ["tenant_id", "status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_table("provider_event_inbox")
