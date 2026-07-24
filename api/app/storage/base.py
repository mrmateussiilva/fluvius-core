from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredFile:
    key: str
    public_url: str
    size_bytes: int


class StorageProvider(ABC):
    @abstractmethod
    async def save(self, tenant_id: str, file_name: str, content: bytes) -> StoredFile:
        raise NotImplementedError
