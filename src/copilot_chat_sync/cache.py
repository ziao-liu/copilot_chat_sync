"""Local verified metadata, reused only after a fresh full-file checksum."""

import hashlib
import sqlite3
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Iterator

from .sessions import SyncError, canonical_bytes, file_digest, json_loads


def signature(path: Path) -> tuple[int, ...]:
    info = path.stat()
    return info.st_size, info.st_mtime_ns, info.st_ctime_ns, info.st_ino, info.st_dev


class VerifiedCache:
    def __init__(self, path: Path, persist: bool):
        self.path = path
        if persist:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path if persist else ":memory:", timeout=5)
        if not persist and path.exists():
            source = sqlite3.connect(path.absolute().as_uri() + "?mode=ro", uri=True, timeout=5)
            try:
                source.backup(self.connection)
            finally:
                source.close()
        self.connection.execute("PRAGMA trusted_schema=OFF")
        self.connection.execute("CREATE TABLE IF NOT EXISTS verified_v2 (path TEXT, kind TEXT, checksum TEXT, data TEXT, data_hash TEXT, PRIMARY KEY(path,kind))")

    def lookup(self, path: Path, kind: str) -> tuple[tuple[int, ...], str, dict[str, Any] | None]:
        before = signature(path)
        checksum = file_digest(path)
        if signature(path) != before:
            raise SyncError(f"File changed while verifying cache: {path}")
        row = self.connection.execute("SELECT checksum,data,data_hash FROM verified_v2 WHERE path=? AND kind=?",
                                      (str(path.absolute()), kind)).fetchone()
        if row is None or row[0] != checksum:
            return before, checksum, None
        if hashlib.sha256(row[1].encode("utf-8")).hexdigest() != row[2]:
            raise SyncError(f"Local verified cache checksum mismatch; remove only this cache file and retry: {self.path}")
        data = json_loads(row[1])
        fields = {"content_hash", "entry"} | ({"revision", "parents", "writer", "requests"} if kind == "revision" else set())
        if not isinstance(data, dict) or set(data) != fields or not isinstance(data["entry"], dict):
            raise SyncError(f"Invalid local verified cache; remove only this cache file and retry: {self.path}")
        return before, checksum, data

    def save(self, path: Path, kind: str, before: tuple[int, ...], checksum: str, data: dict[str, Any]) -> None:
        if signature(path) != before:
            raise SyncError(f"File changed after validation: {path}")
        content = canonical_bytes(data)
        self.connection.execute("INSERT OR REPLACE INTO verified_v2 VALUES (?,?,?,?,?)",
                                (str(path.absolute()), kind, checksum, content.decode("utf-8"), hashlib.sha256(content).hexdigest()))
        self.connection.commit()


current: ContextVar[VerifiedCache | None] = ContextVar("verified_cache", default=None)


@contextmanager
def cache_scope(path: Path, persist: bool = True) -> Iterator[None]:
    from .safety import plain_path
    plain_path(path, path.parent)
    if current.get() is not None:
        yield
        return
    cache = VerifiedCache(path, persist)
    token = current.set(cache)
    try:
        yield
    finally:
        current.reset(token)
        cache.connection.close()
