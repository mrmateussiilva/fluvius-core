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
        target.write_bytes(content)
        return StoredFile(
            key=key,
            public_url=f"{settings.public_api_url}/storage/{key}",
            size_bytes=len(content),
        )
