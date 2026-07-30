"""support WhatsApp group chats

Revision ID: 20260730_0016
Revises: 20260727_0015
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "20260730_0016"
down_revision: str | None = "20260727_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

contact_kind = sa.Enum("direct", "group", name="contact_kind")


def upgrade() -> None:
    contact_kind.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "contacts",
        sa.Column(
            "kind",
            contact_kind,
            server_default="direct",
            nullable=False,
        ),
    )
    op.add_column(
        "contacts",
        sa.Column("provider_address", sa.String(length=255), nullable=True),
    )
    op.alter_column(
        "contacts",
        "phone_number",
        existing_type=sa.String(length=32),
        type_=sa.String(length=64),
        existing_nullable=False,
    )
    op.create_index("ix_contacts_tenant_kind", "contacts", ["tenant_id", "kind"])

    op.add_column(
        "messages",
        sa.Column("participant_phone", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("participant_name", sa.String(length=160), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "participant_name")
    op.drop_column("messages", "participant_phone")
    op.drop_index("ix_contacts_tenant_kind", table_name="contacts")
    op.alter_column(
        "contacts",
        "phone_number",
        existing_type=sa.String(length=64),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.drop_column("contacts", "provider_address")
    op.drop_column("contacts", "kind")
    contact_kind.drop(op.get_bind(), checkfirst=True)
