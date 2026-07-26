"""Track message edits and remove synthetic provider-event messages.

Revision ID: 20260726_0008
Revises: 20260724_0007
Create Date: 2026-07-26
"""

import sqlalchemy as sa

from alembic import op

revision = "20260726_0008"
down_revision = "20260724_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column(
            "edit_content_unavailable",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_table(
        "message_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("provider_event_id", sa.String(length=255), nullable=False),
        sa.Column("previous_body", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("content_available", sa.Boolean(), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["message_id"], ["messages.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "provider_event_id",
            name="uq_message_revisions_provider_event",
        ),
    )
    op.create_index(
        op.f("ix_message_revisions_tenant_id"),
        "message_revisions",
        ["tenant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_message_revisions_message_id"),
        "message_revisions",
        ["message_id"],
        unique=False,
    )

    op.execute(
        """
        WITH edits AS (
            SELECT
                event.tenant_id,
                event.channel_id,
                event.created_at,
                event.payload::jsonb
                    #>> '{data,Message,secretEncryptedMessage,targetMessageKey,ID}'
                    AS target_message_id
            FROM provider_events AS event
            WHERE event.provider = 'evolution_go'
              AND event.payload::jsonb #>> '{data,Info,Edit}' = '1'
        )
        UPDATE messages AS message
        SET edited_at = edits.created_at,
            edit_content_unavailable = TRUE
        FROM edits, conversations AS conversation
        WHERE edits.target_message_id IS NOT NULL
          AND conversation.id = message.conversation_id
          AND conversation.tenant_id = message.tenant_id
          AND conversation.channel_id = edits.channel_id
          AND message.tenant_id = edits.tenant_id
          AND message.provider_message_id = edits.target_message_id
        """
    )
    op.execute(
        """
        DELETE FROM messages AS message
        USING provider_events AS event, conversations AS conversation
        WHERE conversation.id = message.conversation_id
          AND conversation.tenant_id = message.tenant_id
          AND conversation.channel_id = event.channel_id
          AND message.tenant_id = event.tenant_id
          AND message.provider_message_id = event.provider_event_id
          AND message.message_type::text = 'text'
          AND COALESCE(BTRIM(message.body), '') = ''
          AND event.provider = 'evolution_go'
          AND (
              event.payload::jsonb #>> '{data,Info,Edit}' IN ('1', '7')
              OR LOWER(
                  COALESCE(
                      event.payload::jsonb #>> '{data,Info,Type}',
                      ''
                  )
              ) = 'reaction'
          )
        """
    )
    op.execute(
        """
        UPDATE provider_events
        SET payload = (
            payload::jsonb
            #- '{data,Message,secretEncryptedMessage,encIV}'
            #- '{data,Message,secretEncryptedMessage,encPayload}'
            #- '{data,Message,messageContextInfo,deviceListMetadata}'
        )::json
        WHERE provider = 'evolution_go'
          AND (
              payload::jsonb #> '{data,Message,secretEncryptedMessage,encIV}'
                  IS NOT NULL
              OR payload::jsonb
                    #> '{data,Message,secretEncryptedMessage,encPayload}'
                    IS NOT NULL
              OR payload::jsonb
                    #> '{data,Message,messageContextInfo,deviceListMetadata}'
                    IS NOT NULL
          )
        """
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_message_revisions_message_id"),
        table_name="message_revisions",
    )
    op.drop_index(
        op.f("ix_message_revisions_tenant_id"),
        table_name="message_revisions",
    )
    op.drop_table("message_revisions")
    op.drop_column("messages", "edit_content_unavailable")
    op.drop_column("messages", "edited_at")
