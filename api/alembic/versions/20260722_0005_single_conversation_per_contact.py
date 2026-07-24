"""Keep one continuous conversation per contact and channel.

Revision ID: 20260722_0005
Revises: 20260722_0004
Create Date: 2026-07-22
"""

import sqlalchemy as sa
from alembic import op


revision = "20260722_0005"
down_revision = "20260722_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    groups = bind.execute(
        sa.text(
            """
            SELECT tenant_id, channel_id, contact_id
            FROM conversations
            GROUP BY tenant_id, channel_id, contact_id
            HAVING count(*) > 1
            """
        )
    ).mappings().all()

    for group in groups:
        params = {
            "tenant_id": group["tenant_id"],
            "channel_id": group["channel_id"],
            "contact_id": group["contact_id"],
        }
        conversations = bind.execute(
            sa.text(
                """
                SELECT id, status, last_message_at, created_at
                FROM conversations
                WHERE tenant_id = :tenant_id
                  AND channel_id = :channel_id
                  AND contact_id = :contact_id
                ORDER BY
                  CASE WHEN status = 'closed' THEN 1 ELSE 0 END,
                  last_message_at DESC NULLS LAST,
                  created_at DESC
                """
            ),
            params,
        ).mappings().all()
        survivor_id = conversations[0]["id"]
        duplicate_ids = [row["id"] for row in conversations[1:]]
        last_message_values = [
            row["last_message_at"]
            for row in conversations
            if row["last_message_at"] is not None
        ]
        if last_message_values:
            bind.execute(
                sa.text(
                    "UPDATE conversations SET last_message_at = :last_message_at "
                    "WHERE id = :survivor_id AND tenant_id = :tenant_id"
                ),
                {
                    "last_message_at": max(last_message_values),
                    "survivor_id": survivor_id,
                    "tenant_id": group["tenant_id"],
                },
            )

        reads = bind.execute(
            sa.text(
                """
                SELECT cr.id, cr.conversation_id, cr.user_id, cr.last_read_at
                FROM conversation_reads cr
                JOIN conversations c ON c.id = cr.conversation_id
                WHERE c.tenant_id = :tenant_id
                  AND c.channel_id = :channel_id
                  AND c.contact_id = :contact_id
                ORDER BY cr.last_read_at DESC
                """
            ),
            params,
        ).mappings().all()
        reads_by_user: dict[object, list] = {}
        for read in reads:
            reads_by_user.setdefault(read["user_id"], []).append(read)
        for user_reads in reads_by_user.values():
            keeper = next(
                (
                    read
                    for read in user_reads
                    if read["conversation_id"] == survivor_id
                ),
                user_reads[0],
            )
            for read in user_reads:
                if read["id"] != keeper["id"]:
                    bind.execute(
                        sa.text("DELETE FROM conversation_reads WHERE id = :id"),
                        {"id": read["id"]},
                    )
            bind.execute(
                sa.text(
                    """
                    UPDATE conversation_reads
                    SET conversation_id = :survivor_id,
                        last_read_at = :last_read_at
                    WHERE id = :id
                    """
                ),
                {
                    "survivor_id": survivor_id,
                    "last_read_at": max(read["last_read_at"] for read in user_reads),
                    "id": keeper["id"],
                },
            )

        for duplicate_id in duplicate_ids:
            bind.execute(
                sa.text(
                    """
                    UPDATE messages
                    SET conversation_id = :survivor_id
                    WHERE conversation_id = :duplicate_id
                      AND tenant_id = :tenant_id
                    """
                ),
                {
                    "survivor_id": survivor_id,
                    "duplicate_id": duplicate_id,
                    "tenant_id": group["tenant_id"],
                },
            )
            bind.execute(
                sa.text(
                    "DELETE FROM conversations "
                    "WHERE id = :duplicate_id AND tenant_id = :tenant_id"
                ),
                {
                    "duplicate_id": duplicate_id,
                    "tenant_id": group["tenant_id"],
                },
            )

    op.create_unique_constraint(
        "uq_conversations_tenant_channel_contact",
        "conversations",
        ["tenant_id", "channel_id", "contact_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_conversations_tenant_channel_contact",
        "conversations",
        type_="unique",
    )
