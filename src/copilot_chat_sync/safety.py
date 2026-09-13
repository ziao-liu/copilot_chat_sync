"""Local safety primitives. Cloud synchronization is not a distributed lock."""

from __future__ import annotations

import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .sessions import SyncError


def is_redirect(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return getattr(info, "st_reparse_tag", 0) in (0xA0000003, 0xA000000C)


def plain_path(path: Path, root: Path) -> Path:
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError as error:
        raise SyncError(f"Path is outside the allowed storage root: {path}") from error
    if ".." in relative.parts:
        raise SyncError(f"Parent traversal is not allowed in storage paths: {path}")
    current = root
    for part in ("", *relative.parts):
        current = current / part
        if is_redirect(current):
            raise SyncError(f"Refusing redirected storage: {current}. Run migrate first for old chatSessions junctions.")
    return path


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def local_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise SyncError("Another local sync process is using this configuration/storage") from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def code_processes() -> list[str]:
    try:
        import psutil
    except ImportError as error:
        raise SyncError("Process safety check unavailable. Install the package with its psutil dependency.") from error
    matches = []
    current_user = psutil.Process().username()
    for process in psutil.process_iter(["name", "username", "exe", "cmdline"]):
        try:
            info = process.info
            if info["username"] and info["username"] != current_user:
                continue
            name = (info["name"] or "").lower()
            executable = (info["exe"] or "").lower().replace("\\", "/")
            command = " ".join(info["cmdline"] or []).lower()
            is_code = name in {"code", "code.exe", "code-insiders", "code - insiders.exe", "code-insiders.exe", "code-oss", "code - oss.exe"}
            is_helper = name.startswith("code helper") or "/visual studio code" in executable
            is_server = name in {"node", "node.exe"} and (".vscode-server/" in command or ".vscode-server-insiders/" in command)
            if is_code or is_helper or is_server:
                matches.append(f"{process.pid}:{info['name']}")
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise SyncError("Cannot determine whether VS Code is running; refusing writes") from error
    return matches


def require_closed() -> None:
    running = code_processes()
    if running:
        raise SyncError("Close all VS Code windows yourself before syncing. No processes will be killed. Running: " + ", ".join(running))


def is_regular(path: Path) -> bool:
    return not is_redirect(path) and stat.S_ISREG(path.stat().st_mode)
