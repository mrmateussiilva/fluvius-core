from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.dependencies import AuthContext
from app.channels.models import WhatsAppChannel
from app.common.audit_models import AuditLog
from app.common.enums import ChannelStatus
from app.database import get_db
from app.jobs.queue import default_queue
from app.sync.models import SyncRun
from app.sync.schemas import SyncRunCreate, SyncRunResponse
from app.sync.tasks import run_sync
from app.users.router import require_admin


router = APIRouter(prefix="/admin/sync-runs", tags=["admin-sync"])
ACTIVE_STATUSES = ("queued", "running")
STALE_AFTER = timedelta(hours=1)


@router.get("", response_model=list[SyncRunResponse])
def list_sync_runs(
    channel_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> list[SyncRun]:
    query = select(SyncRun).where(SyncRun.tenant_id == context.tenant_id)
    if channel_id is not None:
        query = query.where(SyncRun.channel_id == channel_id)
    return list(
        db.scalars(query.order_by(SyncRun.created_at.desc()).limit(limit))
    )


@router.get("/{sync_run_id}", response_model=SyncRunResponse)
def get_sync_run(
    sync_run_id: UUID,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SyncRun:
    run = db.scalar(
        select(SyncRun).where(
            SyncRun.id == sync_run_id,
            SyncRun.tenant_id == context.tenant_id,
        )
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sincronização não encontrada",
        )
    return run


@router.post(
    "",
    response_model=SyncRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def create_sync_run(
    payload: SyncRunCreate,
    context: AuthContext = Depends(require_admin),
    db: Session = Depends(get_db),
) -> SyncRun:
    channel = db.scalar(
        select(WhatsAppChannel).where(
            WhatsAppChannel.id == payload.channel_id,
            WhatsAppChannel.tenant_id == context.tenant_id,
        )
    )
    if channel is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Canal não encontrado",
        )
    if (
        payload.sync_type in {"contacts", "all"}
        and channel.status != ChannelStatus.CONNECTED
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conecte o canal antes de sincronizar contatos",
        )

    active = db.scalar(
        select(SyncRun)
        .where(
            SyncRun.tenant_id == context.tenant_id,
            SyncRun.channel_id == channel.id,
            SyncRun.status.in_(ACTIVE_STATUSES),
        )
        .with_for_update()
    )
    now = datetime.now(UTC)
    if active is not None and active.updated_at < now - STALE_AFTER:
        active.status = "failed"
        active.error = "A execução anterior expirou antes de concluir."
        active.finished_at = now
        db.add(
            AuditLog(
                tenant_id=context.tenant_id,
                user_id=context.user.id,
                action="sync.failed",
                entity_type="sync_run",
                entity_id=active.id,
                metadata_={
                    "channel_id": str(channel.id),
                    "sync_type": active.sync_type,
                    "expired": True,
                },
            )
        )
        db.commit()
        active = None
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma sincronização em andamento para este canal",
        )

    run = SyncRun(
        tenant_id=context.tenant_id,
        channel_id=channel.id,
        requested_by_user_id=context.user.id,
        sync_type=payload.sync_type,
        recent_days=payload.recent_days,
        status="queued",
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma sincronização em andamento para este canal",
        ) from exc
    db.add(
        AuditLog(
            tenant_id=context.tenant_id,
            user_id=context.user.id,
            action="sync.requested",
            entity_type="sync_run",
            entity_id=run.id,
            metadata_={
                "channel_id": str(channel.id),
                "sync_type": payload.sync_type,
                "recent_days": payload.recent_days,
            },
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe uma sincronização em andamento para este canal",
        ) from exc

    try:
        job = default_queue.enqueue(
            run_sync,
            str(run.id),
            str(context.tenant_id),
            job_id=f"sync-{run.id}",
            job_timeout=1800,
            result_ttl=3600,
            failure_ttl=86400,
        )
    except Exception as exc:
        run = db.scalar(
            select(SyncRun).where(
                SyncRun.id == run.id,
                SyncRun.tenant_id == context.tenant_id,
            )
        )
        if run is not None:
            run.status = "failed"
            run.error = "Não foi possível enfileirar a sincronização."
            run.finished_at = datetime.now(UTC)
            db.add(
                AuditLog(
                    tenant_id=context.tenant_id,
                    user_id=context.user.id,
                    action="sync.failed",
                    entity_type="sync_run",
                    entity_id=run.id,
                    metadata_={
                        "channel_id": str(channel.id),
                        "sync_type": run.sync_type,
                        "queue_error": True,
                    },
                )
            )
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Não foi possível iniciar a sincronização",
        ) from exc

    run.rq_job_id = job.id
    db.commit()
    return run
