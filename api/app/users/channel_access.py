from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext
from app.channels.models import WhatsAppChannel
from app.users.models import TenantUserChannel


def accessible_channel_ids(
    db: Session,
    context: AuthContext,
) -> set[UUID] | None:
    """Return None for unrestricted admins and an explicit set for agents."""
    if context.membership.role == "admin":
        return None
    return set(
        db.scalars(
            select(TenantUserChannel.channel_id).where(
                TenantUserChannel.tenant_id == context.tenant_id,
                TenantUserChannel.user_id == context.user.id,
            )
        )
    )


def ensure_channel_access(
    db: Session,
    context: AuthContext,
    channel_id: UUID,
) -> None:
    allowed = accessible_channel_ids(db, context)
    if allowed is not None and channel_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal não encontrado",
        )


def validate_tenant_channel_ids(
    db: Session,
    tenant_id: UUID,
    channel_ids: set[UUID],
) -> set[UUID]:
    if not channel_ids:
        return set()
    found = set(
        db.scalars(
            select(WhatsAppChannel.id).where(
                WhatsAppChannel.tenant_id == tenant_id,
                WhatsAppChannel.id.in_(channel_ids),
            )
        )
    )
    if found != channel_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Um ou mais canais não pertencem à empresa",
        )
    return found


def user_channel_ids(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    role: str,
) -> list[UUID]:
    if role == "admin":
        return list(
            db.scalars(
                select(WhatsAppChannel.id)
                .where(WhatsAppChannel.tenant_id == tenant_id)
                .order_by(WhatsAppChannel.created_at, WhatsAppChannel.id)
            )
        )
    return list(
        db.scalars(
            select(TenantUserChannel.channel_id)
            .where(
                TenantUserChannel.tenant_id == tenant_id,
                TenantUserChannel.user_id == user_id,
            )
            .order_by(TenantUserChannel.created_at, TenantUserChannel.channel_id)
        )
    )
