from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.attachments.models import MessageAttachment
from app.auth.dependencies import AuthContext, get_auth_context
from app.conversations.models import Conversation
from app.database import get_db
from app.messages.models import Message
from app.storage.local import LocalStorageProvider
from app.users.channel_access import ensure_channel_access


router = APIRouter(prefix="/attachments", tags=["attachments"])


@router.get("/{attachment_id}/content", response_class=FileResponse)
def get_attachment_content(
    attachment_id: UUID,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> FileResponse:
    row = db.execute(
        select(MessageAttachment, Conversation.channel_id)
        .join(
            Message,
            (Message.id == MessageAttachment.message_id)
            & (Message.tenant_id == context.tenant_id),
        )
        .join(
            Conversation,
            (Conversation.id == Message.conversation_id)
            & (Conversation.tenant_id == context.tenant_id),
        )
        .where(
            MessageAttachment.id == attachment_id,
            MessageAttachment.tenant_id == context.tenant_id,
            Message.tenant_id == context.tenant_id,
            Conversation.tenant_id == context.tenant_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Anexo não encontrado",
        )
    attachment, channel_id = row
    ensure_channel_access(db, context, channel_id)

    file_path = LocalStorageProvider().path_for(attachment.storage_key)
    if file_path is None or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Arquivo do anexo não encontrado",
        )
    return FileResponse(
        file_path,
        media_type=attachment.content_type,
        filename=attachment.file_name,
        content_disposition_type="inline",
        headers={
            "Cache-Control": "private, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
