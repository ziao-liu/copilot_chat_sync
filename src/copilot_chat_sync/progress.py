"""Per-request progress; CLI calls leave reporting disabled."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Callable, Iterator


@dataclass
class _Steps:
    start: float
    span: float
    total: int
    done: int = 0


class Progress:
    def __init__(self) -> None:
        self.lock = Lock()
        self.data: dict = {}
        self.steps: list[_Steps] = []

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
                         "done": 0, "total": 0, "files": 0, "overall": 0, "finished": False,
                         "started": monotonic()}
            self.steps = []
        token = current.set(self)
        finished = False
        try:
            yield
            finished = True
        finally:
            with self.lock:
                self.data.update(active=False, finished=finished)
                if finished:
                    self.data["overall"] = 1
            current.reset(token)


current: ContextVar[Progress | None] = ContextVar("sync_progress", default=None)


@contextmanager
def steps(total: int) -> Iterator[Callable[[], None]]:
    """Divide the current task into completed work units, not elapsed-time estimates."""
    if type(total) is not int or total < 0:
        raise ValueError("Progress steps must be a non-negative integer")
    progress = current.get()
    if progress is None:
        yield lambda: None
        return
    with progress.lock:
        parent = progress.steps[-1] if progress.steps else None
        if parent is not None and parent.done >= parent.total:
            raise RuntimeError("No remaining progress step")
        frame = _Steps(parent.start + parent.span * parent.done / parent.total if parent else 0,
                       parent.span / parent.total if parent else 1, max(total, 1))
        progress.steps.append(frame)

    def advance() -> None:
        with progress.lock:
            if frame.done >= frame.total:
                raise RuntimeError("Too many completed progress steps")
            frame.done += 1
            progress.data["overall"] = max(progress.data["overall"],
                                          min(.999, frame.start + frame.span * frame.done / frame.total))

    finished = False
    try:
        yield advance
        finished = True
    finally:
        with progress.lock:
            if finished:
                progress.data["overall"] = max(progress.data["overall"], min(.999, frame.start + frame.span))
            progress.steps.pop()


def report(stage: str, file: str | None = None, done: int = 0, total: int = 0) -> None:
    progress = current.get()
    if progress is not None:
        progress.update(stage=stage, done=done, total=total, **({"file": file} if file is not None else {}))


def file_checked() -> None:
    progress = current.get()
    if progress is not None:
        with progress.lock:
            progress.data["files"] += 1
