"""separate address book names from operational contact names

Revision ID: 20260802_0023
Revises: 20260731_0022
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260802_0023"
down_revision: str | None = "20260731_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("contacts", sa.Column("address_book_name", sa.String(160)))
    op.execute(
        """
        UPDATE contacts
        SET name = NULL
        WHERE kind = 'direct'
          AND name IS NOT NULL
          AND name !~ '[[:alpha:]]'
          AND regexp_replace(name, '[^0-9]', '', 'g') =
              regexp_replace(phone_number, '[^0-9]', '', 'g')
        """
    )


def downgrade() -> None:
    op.drop_column("contacts", "address_book_name")
