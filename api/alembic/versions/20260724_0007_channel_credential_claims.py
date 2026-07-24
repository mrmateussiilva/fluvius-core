"""Claim one provider credential per WhatsApp channel.

Revision ID: 20260724_0007
Revises: 20260722_0006
Create Date: 2026-07-24
"""

import sqlalchemy as sa

from alembic import op

revision = "20260724_0007"
down_revision = "20260722_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "whatsapp_channels",
        sa.Column("credential_fingerprint", sa.String(length=64), nullable=True),
    )
    op.create_unique_constraint(
        "uq_whatsapp_channels_provider_credential",
        "whatsapp_channels",
        ["provider", "credential_fingerprint"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_whatsapp_channels_provider_credential",
        "whatsapp_channels",
        type_="unique",
    )
    op.drop_column("whatsapp_channels", "credential_fingerprint")
