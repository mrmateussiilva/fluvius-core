"""index pending provider events for health and reconcile

Revision ID: 20260730_0018
Revises: 20260730_0017
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260730_0018"
down_revision: str | None = "20260730_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_provider_events_tenant_processed_created",
        "provider_events",
        ["tenant_id", "processed", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_provider_events_channel_processed_created",
        "provider_events",
        ["channel_id", "processed", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_provider_events_channel_processed_created",
        table_name="provider_events",
    )
    op.drop_index(
        "ix_provider_events_tenant_processed_created",
        table_name="provider_events",
    )
