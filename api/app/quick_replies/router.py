from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext, get_auth_context
from app.database import get_db
from app.quick_replies.models import QuickReply
from app.quick_replies.schemas import QuickReplyCreate, QuickReplyResponse


router = APIRouter(prefix="/quick-replies", tags=["quick replies"])


@router.get("", response_model=list[QuickReplyResponse])
def list_quick_replies(
    context: AuthContext = Depends(get_auth_context), db: Session = Depends(get_db)
) -> list[QuickReply]:
    return list(
        db.scalars(
            select(QuickReply)
            .where(QuickReply.tenant_id == context.tenant_id)
            .order_by(QuickReply.title)
        )
    )


@router.post("", response_model=QuickReplyResponse, status_code=status.HTTP_201_CREATED)
def create_quick_reply(
    payload: QuickReplyCreate,
    context: AuthContext = Depends(get_auth_context),
    db: Session = Depends(get_db),
) -> QuickReply:
    quick_reply = QuickReply(
        tenant_id=context.tenant_id,
        created_by_user_id=context.user.id,
        shortcut=payload.shortcut,
        title=payload.title,
        content=payload.content,
    )
    db.add(quick_reply)
    db.commit()
    db.refresh(quick_reply)
    return quick_reply
