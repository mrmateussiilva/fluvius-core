from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles

from app.auth.router import router as auth_router
from app.channels.router import router as channels_router
from app.config import settings
from app.contacts.router import router as contacts_router
from app.conversations.router import router as conversations_router
from app.database import load_all_models
from app.messages.router import router as messages_router
from app.providers.webhook_router import router as webhook_router
from app.quick_replies.router import router as quick_replies_router
from app.realtime.router import router as realtime_router


load_all_models()

app = FastAPI(title=settings.app_name, default_response_class=ORJSONResponse)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/storage", StaticFiles(directory=settings.local_storage_path, check_dir=False), name="storage")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(channels_router, prefix=settings.api_v1_prefix)
app.include_router(contacts_router, prefix=settings.api_v1_prefix)
app.include_router(conversations_router, prefix=settings.api_v1_prefix)
app.include_router(messages_router, prefix=settings.api_v1_prefix)
app.include_router(quick_replies_router, prefix=settings.api_v1_prefix)
app.include_router(webhook_router, prefix=settings.api_v1_prefix)
app.include_router(realtime_router)
