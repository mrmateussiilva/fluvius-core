import re
import uuid
from pathlib import Path

from app.config import settings
from app.storage.base import StorageProvider, StoredFile


class LocalStorageProvider(StorageProvider):
    def __init__(self) -> None:
        self.root = Path(settings.local_storage_path)

    async def save(self, tenant_id: str, file_name: str, content: bytes) -> StoredFile:
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file_name).name)
        key = f"{tenant_id}/{uuid.uuid4()}-{safe_name}"
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4()}.tmp")
        try:
            temporary.write_bytes(content)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
        return StoredFile(
            key=key,
            public_url=self.public_url_for(key),
            size_bytes=len(content),
        )

    def public_url_for(self, key: str) -> str:
        return f"{settings.public_api_url.rstrip('/')}/storage/{key}"

    def path_for(self, key: str) -> Path | None:
        relative = Path(key)
        if relative.is_absolute() or ".." in relative.parts:
            return None
        root = self.root.resolve()
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            return None
        return target
