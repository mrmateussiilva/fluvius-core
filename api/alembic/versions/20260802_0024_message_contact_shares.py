"""add native shared contacts to messages

Revision ID: 20260802_0024
Revises: 20260802_0023
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0024"
down_revision: str | None = "20260802_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE message_type ADD VALUE IF NOT EXISTS 'contact'")
    op.create_table(
        "message_contact_shares",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("source_contact_id", sa.Uuid(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("organization", sa.String(length=160), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_contact_id"],
            ["contacts.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id",
            "position",
            name="uq_message_contact_shares_position",
        ),
    )
    op.create_index(
        "ix_message_contact_shares_tenant_id",
        "message_contact_shares",
        ["tenant_id"],
    )
    op.create_index(
        "ix_message_contact_shares_message_id",
        "message_contact_shares",
        ["message_id"],
    )
    op.create_index(
        "ix_message_contact_shares_source_contact_id",
        "message_contact_shares",
        ["source_contact_id"],
    )


def downgrade() -> None:
    op.drop_table("message_contact_shares")
