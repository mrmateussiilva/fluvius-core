"""add encrypted provider credentials and channel provisioning keys

Revision ID: 20260727_0013
Revises: 20260727_0012
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260727_0013"
down_revision: str | None = "20260727_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_channels",
        sa.Column("provisioning_key", sa.Uuid(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_whatsapp_channels_tenant_provisioning_key",
        "whatsapp_channels",
        ["tenant_id", "provisioning_key"],
    )
    op.create_table(
        "provider_credentials",
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
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("encrypted_secret", sa.LargeBinary(), nullable=False),
        sa.Column("secret_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "encryption_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "provisioning_status",
            sa.String(length=24),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("last_error", sa.String(length=500)),
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
            "provisioning_status IN ('pending', 'active', 'failed', 'uncertain')",
            name="ck_provider_credentials_provisioning_status",
        ),
        sa.UniqueConstraint(
            "channel_id",
            "provider",
            name="uq_provider_credentials_channel_provider",
        ),
        sa.UniqueConstraint(
            "provider",
            "secret_fingerprint",
            name="uq_provider_credentials_provider_fingerprint",
        ),
    )
    op.create_index(
        "ix_provider_credentials_tenant_id",
        "provider_credentials",
        ["tenant_id"],
    )
    op.create_index(
        "ix_provider_credentials_channel_id",
        "provider_credentials",
        ["channel_id"],
    )
    op.create_index(
        "ix_provider_credentials_provisioning_status",
        "provider_credentials",
        ["provisioning_status"],
    )


def downgrade() -> None:
    op.drop_table("provider_credentials")
    op.drop_constraint(
        "uq_whatsapp_channels_tenant_provisioning_key",
        "whatsapp_channels",
        type_="unique",
    )
    op.drop_column("whatsapp_channels", "provisioning_key")
