"""Per-request progress; CLI calls leave reporting disabled."""

from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from time import monotonic
from typing import Iterator


class Progress:
    def __init__(self) -> None:
        self.lock = Lock()
        self.data: dict = {}

    def update(self, **values: object) -> None:
        with self.lock:
            self.data.update(values, updated=monotonic())

    def snapshot(self, identifier: str) -> dict:
        with self.lock:
            return dict(self.data) if self.data.get("id") == identifier else {}

    @contextmanager
    def track(self, identifier: str) -> Iterator[None]:
        with self.lock:
            self.data = {"id": identifier, "active": True, "stage": "准备检查", "file": "",
                         "done": 0, "total": 0, "files": 0, "started": monotonic()}
        token = current.set(self)
        try:
            yield
        finally:
            self.update(active=False)
            current.reset(token)


current: ContextVar[Progress | None] = ContextVar("sync_progress", default=None)


def report(stage: str, file: str | None = None, done: int = 0, total: int = 0) -> None:
    progress = current.get()
    if progress is not None:
        progress.update(stage=stage, done=done, total=total, **({"file": file} if file is not None else {}))


def file_checked() -> None:
    progress = current.get()
    if progress is not None:
        with progress.lock:
            progress.data["files"] += 1
