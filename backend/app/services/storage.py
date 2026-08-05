"""All file access goes through here.

Local filesystem now; S3 later is a second implementation of the same three
methods, not a change to any caller. Layout is `{STORAGE_DIR}/{paper_id}/{filename}`
per docs/DESIGN.md, and `storage_key` is the `{paper_id}/{filename}` suffix —
callers never build absolute paths themselves.
"""
from pathlib import Path

from app.core.config import settings


class LocalStorageService:
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.STORAGE_DIR)

    def write(self, paper_id, filename: str, data: bytes) -> str:
        """Persist bytes and return the storage key to record on the paper row."""
        key = f"{paper_id}/{filename}"
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def read(self, storage_key: str) -> bytes:
        return (self.root / storage_key).read_bytes()

    def path(self, storage_key: str) -> Path:
        """Absolute path, for handing a file to Starlette's FileResponse."""
        return self.root / storage_key


storage = LocalStorageService()
