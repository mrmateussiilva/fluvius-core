from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.common.enums import MessageDirection, MessageStatus
from app.messages.models import Message


def has_pending_predecessor(db: Session, message: Message) -> bool:
    predecessor = db.scalar(
        select(Message.id)
        .where(
            Message.tenant_id == message.tenant_id,
            Message.conversation_id == message.conversation_id,
            Message.direction == MessageDirection.OUTGOING,
            Message.status == MessageStatus.PENDING,
            Message.id != message.id,
            or_(
                Message.created_at < message.created_at,
                (
                    (Message.created_at == message.created_at)
                    & (Message.id < message.id)
                ),
            ),
        )
        .limit(1)
    )
    return predecessor is not None
