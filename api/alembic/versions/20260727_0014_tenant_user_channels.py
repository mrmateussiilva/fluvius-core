"""scope tenant users to WhatsApp channels

Revision ID: 20260727_0014
Revises: 20260727_0013
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0014"
down_revision: str | None = "20260727_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenant_user_channels",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "channel_id",
            sa.Uuid(),
            sa.ForeignKey("whatsapp_channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "channel_id",
            name="uq_tenant_user_channels_membership",
        ),
    )
    op.create_index(
        "ix_tenant_user_channels_tenant_id",
        "tenant_user_channels",
        ["tenant_id"],
    )
    op.create_index(
        "ix_tenant_user_channels_user_id",
        "tenant_user_channels",
        ["user_id"],
    )
    op.create_index(
        "ix_tenant_user_channels_channel_id",
        "tenant_user_channels",
        ["channel_id"],
    )
    op.execute(
        """
        INSERT INTO tenant_user_channels (
            id,
            tenant_id,
            user_id,
            channel_id,
            created_at,
            updated_at
        )
        SELECT
            gen_random_uuid(),
            membership.tenant_id,
            membership.user_id,
            channel.id,
            now(),
            now()
        FROM tenant_users AS membership
        JOIN whatsapp_channels AS channel
          ON channel.tenant_id = membership.tenant_id
        WHERE membership.role = 'agent'
        """
    )


def downgrade() -> None:
    op.drop_table("tenant_user_channels")
