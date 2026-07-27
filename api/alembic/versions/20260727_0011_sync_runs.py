"""add operational synchronization runs

Revision ID: 20260727_0011
Revises: 20260726_0010
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0011"
down_revision: str | None = "20260726_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sync_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.Uuid(),
            sa.ForeignKey("whatsapp_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "requested_by_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("sync_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("recent_days", sa.Integer(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("processed_items", sa.Integer(), nullable=False),
        sa.Column("succeeded_items", sa.Integer(), nullable=False),
        sa.Column("failed_items", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=500)),
        sa.Column("rq_job_id", sa.String(length=255)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
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
            "sync_type IN ('contacts', 'messages', 'all')",
            name="ck_sync_runs_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
            name="ck_sync_runs_status",
        ),
        sa.CheckConstraint(
            "recent_days BETWEEN 1 AND 30",
            name="ck_sync_runs_recent_days",
        ),
        sa.CheckConstraint(
            "total_items >= 0 AND processed_items >= 0 "
            "AND succeeded_items >= 0 AND failed_items >= 0",
            name="ck_sync_runs_counts",
        ),
    )
    op.create_index("ix_sync_runs_tenant_id", "sync_runs", ["tenant_id"])
    op.create_index("ix_sync_runs_channel_id", "sync_runs", ["channel_id"])
    op.create_index(
        "ix_sync_runs_requested_by_user_id",
        "sync_runs",
        ["requested_by_user_id"],
    )
    op.create_index("ix_sync_runs_status", "sync_runs", ["status"])
    op.create_index(
        "uq_sync_runs_active_channel",
        "sync_runs",
        ["channel_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_table("sync_runs")
