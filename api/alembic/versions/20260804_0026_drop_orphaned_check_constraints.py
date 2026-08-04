"""drop check constraints removed from models

Revision ID: 20260804_0026
Revises: 20260804_0025
Create Date: 2026-08-04

CheckConstraints criados em migrations anteriores foram removidos dos models
SQLAlchemy. Esta migration alinha o banco com os models atuais, removendo os
constraints órfãos detectados pelo Alembic.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0026"
down_revision: str | None = "20260804_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # message_deliveries — constraints removidos do model
    op.drop_constraint(
        "ck_message_deliveries_status",
        "message_deliveries",
        type_="check",
    )
    op.drop_constraint(
        "ck_message_deliveries_attempts",
        "message_deliveries",
        type_="check",
    )
    # sync_runs — constraints removidos do model
    op.drop_constraint(
        "ck_sync_runs_type",
        "sync_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_sync_runs_status",
        "sync_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_sync_runs_recent_days",
        "sync_runs",
        type_="check",
    )
    op.drop_constraint(
        "ck_sync_runs_counts",
        "sync_runs",
        type_="check",
    )


def downgrade() -> None:
    # Recria os constraints caso seja necessário reverter
    op.create_check_constraint(
        "ck_sync_runs_counts",
        "sync_runs",
        "total_items >= 0 AND processed_items >= 0 "
        "AND succeeded_items >= 0 AND failed_items >= 0",
    )
    op.create_check_constraint(
        "ck_sync_runs_recent_days",
        "sync_runs",
        "recent_days BETWEEN 1 AND 30",
    )
    op.create_check_constraint(
        "ck_sync_runs_status",
        "sync_runs",
        "status IN ('queued', 'running', 'completed', 'partial', 'failed')",
    )
    op.create_check_constraint(
        "ck_sync_runs_type",
        "sync_runs",
        "sync_type IN ('contacts', 'messages')",
    )
    op.create_check_constraint(
        "ck_message_deliveries_attempts",
        "message_deliveries",
        "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 "
        "AND attempt_count <= max_attempts",
    )
    op.create_check_constraint(
        "ck_message_deliveries_status",
        "message_deliveries",
        "status IN ('queued', 'enqueued', 'processing', 'sent', 'failed')",
    )
