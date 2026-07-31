"""add sync run item breakdown counters

Revision ID: 20260731_0019
Revises: 20260730_0018
Create Date: 2026-07-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260731_0019"
down_revision: str | None = "20260730_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sync_runs",
        sa.Column(
            "contact_items",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "sync_runs",
        sa.Column(
            "group_items",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "sync_runs",
        sa.Column(
            "message_event_items",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "sync_runs",
        sa.Column(
            "imported_group_items",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("sync_runs", "imported_group_items")
    op.drop_column("sync_runs", "message_event_items")
    op.drop_column("sync_runs", "group_items")
    op.drop_column("sync_runs", "contact_items")
