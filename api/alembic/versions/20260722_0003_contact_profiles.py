"""Add WhatsApp profile fields to contacts.

Revision ID: 20260722_0003
Revises: 20260722_0002
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from alembic import op


revision = "20260722_0003"
down_revision = "20260722_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("push_name", sa.String(160)))
    op.add_column("contacts", sa.Column("business_name", sa.String(160)))
    op.add_column("contacts", sa.Column("verified_name", sa.String(160)))
    op.add_column("contacts", sa.Column("about", sa.Text()))
    op.add_column("contacts", sa.Column("profile_picture_url", sa.Text()))
    op.add_column("contacts", sa.Column("is_on_whatsapp", sa.Boolean()))
    op.add_column("contacts", sa.Column("profile_synced_at", sa.DateTime(timezone=True)))
    op.add_column("contacts", sa.Column("profile_sync_error", sa.String(500)))
    op.execute("UPDATE contacts SET push_name = name WHERE name IS NOT NULL")


def downgrade() -> None:
    for column in (
        "profile_sync_error",
        "profile_synced_at",
        "is_on_whatsapp",
        "profile_picture_url",
        "about",
        "verified_name",
        "business_name",
        "push_name",
    ):
        op.drop_column("contacts", column)
