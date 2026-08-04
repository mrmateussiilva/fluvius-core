import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.attachments.router import router as attachments_router
from app.auth.router import router as auth_router
from app.channels.router import router as channels_router
from app.config import settings
from app.contacts.router import router as contacts_router
from app.conversations.router import router as conversations_router
from app.database import engine, load_all_models
from app.delivery.dispatcher import delivery_dispatcher_loop
from app.messages.router import router as messages_router
from app.operations.router import router as operations_router
from app.platform.router import router as platform_router
from app.providers.history_reconcile import history_reconcile_loop
from app.providers.inbox_dispatcher import provider_inbox_dispatcher_loop
from app.providers.reconcile import webhook_reconcile_loop
from app.providers.webhook_router import router as webhook_router
from app.quick_replies.router import router as quick_replies_router
from app.realtime.broker import consume_realtime_events
from app.realtime.router import router as realtime_router
from app.sync.router import router as sync_router
from app.users.router import router as users_router

load_all_models()


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop_event = asyncio.Event()
    tasks: list[asyncio.Task] = []
    if settings.environment != "test":
        tasks = [
            asyncio.create_task(delivery_dispatcher_loop(stop_event)),
            asyncio.create_task(provider_inbox_dispatcher_loop(stop_event)),
            asyncio.create_task(webhook_reconcile_loop(stop_event)),
            asyncio.create_task(history_reconcile_loop(stop_event)),
            asyncio.create_task(consume_realtime_events(stop_event)),
        ]
    try:
        yield
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount(
    "/storage",
    StaticFiles(directory=settings.local_storage_path, check_dir=False),
    name="storage",
)


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/live", tags=["health"])
def liveness() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict[str, str]:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        redis = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=1,
            socket_timeout=2,
        )
        try:
            redis.ping()
        finally:
            redis.close()
    except (SQLAlchemyError, RedisError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dependências indisponíveis",
        ) from exc
    return {"status": "ready"}


app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(attachments_router, prefix=settings.api_v1_prefix)
app.include_router(channels_router, prefix=settings.api_v1_prefix)
app.include_router(contacts_router, prefix=settings.api_v1_prefix)
app.include_router(conversations_router, prefix=settings.api_v1_prefix)
app.include_router(messages_router, prefix=settings.api_v1_prefix)
app.include_router(operations_router, prefix=settings.api_v1_prefix)
app.include_router(platform_router, prefix=settings.api_v1_prefix)
app.include_router(quick_replies_router, prefix=settings.api_v1_prefix)
app.include_router(users_router, prefix=settings.api_v1_prefix)
app.include_router(sync_router, prefix=settings.api_v1_prefix)
app.include_router(webhook_router, prefix=settings.api_v1_prefix)
app.include_router(realtime_router)
