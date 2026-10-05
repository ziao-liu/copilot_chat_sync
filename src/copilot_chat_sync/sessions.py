"""Read VS Code JSON/JSONL transcripts without loading editing checkpoints."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import os
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, BinaryIO, Callable

import ijson
import psutil
from .progress import report

MAX_SESSION_BYTES = 128 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024 * 1024
MAX_LOG_BYTES = 8 * 1024 * 1024 * 1024
FILE_CHUNK_BYTES = 1024 * 1024
JSON_BUFFER_BYTES = 32 * 1024 * 1024
MAX_PROCESS_BYTES = 2 * 1024 * 1024 * 1024
SESSION_ID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")


class SyncError(Exception):
    """An actionable failure that must not be reported as successful sync."""


def session_id(value: str) -> str:
    if not isinstance(value, str) or not SESSION_ID.fullmatch(value):
        raise SyncError(f"Invalid legacy session ID: {value!r}")
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"Non-finite JSON value: {value}")


def json_loads(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class MemoryGuard:
    def __init__(self) -> None:
        self.process = psutil.Process()
        rss = self.process.memory_info().rss
        self.limit = min(MAX_PROCESS_BYTES, rss + psutil.virtual_memory().available // 2)
        self.calls = 0

    def check(self, force: bool = False) -> None:
        self.calls += 1
        if not force and self.calls % 256:
            return
        if self.process.memory_info().rss > self.limit:
            raise SyncError("Insufficient memory for this conversation; close other applications and retry on a computer with more RAM. No chat was truncated.")


def _canonical_parts(value: Any, depth: int = 0) -> Iterator[str]:
    if depth >= 256 and isinstance(value, (dict, list, tuple)):
        raise SyncError("JSON nesting exceeds 256 levels")
    if isinstance(value, str):
        yield '"'
        for start in range(0, len(value), 64 * 1024):
            yield json.dumps(value[start:start + 64 * 1024], ensure_ascii=False)[1:-1]
        yield '"'
    elif isinstance(value, dict):
        yield "{"
        for index, key in enumerate(sorted(value)):
            if index:
                yield ","
            name = key if isinstance(key, str) else json.dumps(key, allow_nan=False)
            yield from _canonical_parts(name, depth + 1)
            yield ":"
            yield from _canonical_parts(value[key], depth + 1)
        yield "}"
    elif isinstance(value, (list, tuple)):
        yield "["
        for index, item in enumerate(value):
            if index:
                yield ","
            yield from _canonical_parts(item, depth + 1)
        yield "]"
    else:
        yield json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def canonical_chunks(value: Any, newline: bool = False, check_size: bool = True) -> Iterator[bytes]:
    report("计算快照大小与校验值")
    guard = MemoryGuard()
    guard.check(force=True)
    total = 0
    for part in _canonical_parts(value):
        guard.check()
        for start in range(0, len(part), FILE_CHUNK_BYTES):
            chunk = part[start:start + FILE_CHUNK_BYTES].encode("utf-8")
            total += len(chunk)
            if check_size and total > MAX_SNAPSHOT_BYTES:
                raise SyncError("JSON snapshot exceeds 2 GiB; no oversized snapshot was written")
            yield chunk
    if newline:
        if check_size and total + 1 > MAX_SNAPSHOT_BYTES:
            raise SyncError("JSON snapshot exceeds 2 GiB; no oversized snapshot was written")
        yield b"\n"


def chunks_digest(chunks: Iterable[bytes]) -> str:
    checksum = hashlib.sha256()
    for chunk in chunks:
        checksum.update(chunk)
    return checksum.hexdigest()


def digest(value: Any) -> str:
    return chunks_digest(canonical_chunks(value))


def _json_size(value: Any) -> int:
    return sum(len(chunk) for chunk in canonical_chunks(value, check_size=False))


@contextmanager
def stable_file(path: Path, limit: int) -> Iterator[BinaryIO]:
    before = path.stat()
    if before.st_size > limit:
        raise SyncError(f"File exceeds {limit} bytes: {path}")
    def signature(info: os.stat_result) -> tuple[int, int, int, int]:
        return info.st_size, info.st_mtime_ns, info.st_ino, info.st_dev

    with path.open("rb") as stream:
        if signature(os.fstat(stream.fileno())) != signature(before):
            raise SyncError(f"File changed while opening: {path}")
        yield stream
        if signature(os.fstat(stream.fileno())) != signature(before) or signature(path.stat()) != signature(before):
            raise SyncError(f"File changed while reading; close VS Code and wait for OneDrive: {path}")


def file_chunks(path: Path) -> Iterator[bytes]:
    with stable_file(path, MAX_LOG_BYTES) as stream:
        total = 0
        size = os.fstat(stream.fileno()).st_size
        report("校验或复制原始文件", path.name, total, size)
        while chunk := stream.read(FILE_CHUNK_BYTES):
            total += len(chunk)
            if total > MAX_LOG_BYTES:
                raise SyncError(f"File exceeds {MAX_LOG_BYTES} bytes: {path}")
            report("校验或复制原始文件", path.name, total, size)
            yield chunk


def file_digest(path: Path) -> str:
    checksum = hashlib.sha256()
    for chunk in file_chunks(path):
        checksum.update(chunk)
    return checksum.hexdigest()


def read_stable(path: Path, limit: int = MAX_SESSION_BYTES) -> bytes:
    with stable_file(path, limit) as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise SyncError(f"File exceeds {limit} bytes: {path}")
    return data


class JSONReader:
    def __init__(self, stream: BinaryIO, guard: MemoryGuard, line: bool = False, prefix: bytes = b""):
        self.stream = stream
        self.guard = guard
        self.line = line
        self.prefix = prefix
        self.count = 0
        self.finished = False
        self.nonempty = False
        self.size = os.fstat(stream.fileno()).st_size

    def read(self, size: int = -1) -> bytes:
        if size == 0 or self.finished:
            return b""
        self.guard.check(force=True)
        size = JSON_BUFFER_BYTES if size < 0 else min(size, JSON_BUFFER_BYTES)
        head, self.prefix = self.prefix[:size], self.prefix[size:]
        if self.line and head.endswith(b"\n"):
            data = head
        elif self.line:
            data = head + self.stream.readline(size - len(head)) if len(head) < size else head
        else:
            data = head + self.stream.read(size - len(head)) if len(head) < size else head
        self.count += len(data)
        if self.count > MAX_SNAPSHOT_BYTES:
            raise SyncError("JSON record exceeds 2 GiB; the source file was not modified")
        self.finished = not data or (self.line and data.endswith(b"\n"))
        self.nonempty = self.nonempty or bool(data.strip(b" \t\r\n"))
        report("读取并重放聊天文件", Path(self.stream.name).name, self.stream.tell(), self.size)
        return data


_EMPTY = object()


def _read_json(reader: JSONReader, allow_empty: bool = False) -> Any:
    builder = ijson.ObjectBuilder()
    found = False
    depth = 0
    try:
        # Larger parser buffers avoid quadratic rescanning of giant string tokens.
        for event, value in ijson.basic_parse(reader, buf_size=JSON_BUFFER_BYTES):
            found = True
            if event in ("start_map", "start_array"):
                depth += 1
                if depth > 256:
                    raise SyncError("JSON nesting exceeds 256 levels")
            elif event in ("end_map", "end_array"):
                depth -= 1
            if isinstance(value, Decimal):
                value = float(value)
                if not math.isfinite(value):
                    raise SyncError("Non-finite JSON number")
            reader.guard.check(force=event == "string" and len(value) > 64 * 1024)
            builder.event(event, value)
    except ijson.IncompleteJSONError:
        if allow_empty and not reader.nonempty:
            return _EMPTY
        raise
    if not found:
        raise SyncError("Empty JSON document")
    reader.guard.check(force=True)
    return builder.value


def load_json(path: Path) -> Any:
    try:
        with stable_file(path, MAX_SNAPSHOT_BYTES) as stream:
            report("读取聊天快照", path.name, 0, os.fstat(stream.fileno()).st_size)
            prefix = stream.read(3)
            return _read_json(JSONReader(stream, MemoryGuard(), prefix=b"" if prefix == b"\xef\xbb\xbf" else prefix))
    except MemoryError as error:
        raise SyncError(f"Cannot read JSON {path}: Insufficient memory; no chat was truncated") from error
    except (OSError, ValueError, ijson.JSONError) as error:
        raise SyncError(f"Cannot read JSON {path}: {error}") from error


def _log_entries(stream: BinaryIO) -> Iterator[tuple[int, Any]]:
    guard = MemoryGuard()
    number = 0
    first = True
    total = 0
    while True:
        number += 1
        prefix = stream.readline(3 if first else 1)
        if first and prefix.startswith(b"\xef") and len(prefix) < 3:
            prefix += stream.read(3 - len(prefix))
        if first and prefix == b"\xef\xbb\xbf":
            prefix = stream.readline(1)
        first = False
        if not prefix:
            return
        if prefix.endswith(b"\n") and not prefix.strip():
            continue
        reader = JSONReader(stream, guard, line=True, prefix=prefix)
        try:
            entry = _read_json(reader, allow_empty=True)
            total += reader.count
            if total > MAX_LOG_BYTES:
                raise SyncError("JSONL log exceeds 8 GiB")
            if entry is not _EMPTY:
                yield number, entry
        except (ValueError, ijson.JSONError, SyncError) as error:
            raise SyncError(f"Invalid JSONL at line {number}: {error}") from error


def _parent(state: Any, keys: Any) -> tuple[Any, str | int]:
    if not isinstance(keys, list) or not keys:
        raise SyncError("Mutation paths must be non-empty arrays")
    current = state
    for key in keys[:-1]:
        current = _get(current, key)
    key = keys[-1]
    if isinstance(current, dict) and isinstance(key, str):
        return current, key
    if isinstance(current, list) and type(key) is int and 0 <= key < len(current):
        return current, key
    raise SyncError("Invalid mutation path or array index")


def _get(container: Any, key: Any) -> Any:
    if isinstance(container, dict) and isinstance(key, str) and key in container:
        return container[key]
    if isinstance(container, list) and type(key) is int and 0 <= key < len(container):
        return container[key]
    raise SyncError("Mutation traverses a missing or invalid path")


def _replay(entries: Iterable[tuple[int, Any]], size_of: Callable[[Any], int]) -> dict[str, Any]:
    state: Any = None
    initialized = False
    state_bytes = 0
    for line_number, entry in entries:
        try:
            if not isinstance(entry, dict) or type(entry.get("kind")) is not int:
                raise SyncError("Invalid mutation entry")
            kind = entry["kind"]
            allowed = {0: {"kind", "v"}, 1: {"kind", "k", "v"}, 2: {"kind", "k", "v", "i"}, 3: {"kind", "k"}}
            if kind not in allowed or set(entry) - allowed[kind]:
                raise SyncError("Unsupported mutation kind or fields; update the tool before syncing")
            if kind == 0:
                if initialized or not isinstance(entry.get("v"), dict):
                    raise SyncError("Expected exactly one initial object as the first entry")
                state = entry["v"]
                state_bytes = size_of(state)
                if state_bytes > MAX_SNAPSHOT_BYTES:
                    raise SyncError("Replayed session exceeds 2 GiB; refusing an oversized live snapshot")
                initialized = True
                continue
            if not initialized:
                raise SyncError("Log is missing its initial snapshot")
            parent, key = _parent(state, entry.get("k"))
            present = not isinstance(parent, dict) or key in parent
            previous = parent[key] if present else None
            previous_bytes = size_of(previous) if kind != 2 or not isinstance(previous, list) else 0
            previous_count = len(parent)
            delta = 0
            if kind == 1:
                if "v" not in entry:
                    if isinstance(parent, dict):
                        parent.pop(key, None)
                    else:
                        parent[key] = None
                else:
                    parent[key] = entry["v"]
            elif kind == 2:
                array = parent.get(key, []) if isinstance(parent, dict) else parent[key]
                if array is None:
                    array = []
                if not isinstance(array, list):
                    raise SyncError("Push operation must target an array")
                if "i" in entry:
                    start = entry["i"]
                    if type(start) is not int or not 0 <= start <= len(array):
                        raise SyncError("Invalid array truncation index")
                    delta -= sum(size_of(value) for value in array[start:])
                    delta += max(0, start - 1) - max(0, len(array) - 1)
                    del array[start:]
                values = entry.get("v", [])
                if not isinstance(values, list):
                    raise SyncError("Push values must be an array")
                delta += sum(size_of(value) for value in values)
                delta += max(0, len(array) + len(values) - 1) - max(0, len(array) - 1)
                array.extend(values)
                parent[key] = array
                if not isinstance(previous, list):
                    delta += 2 - (previous_bytes if present else 0)
            elif kind == 3:
                if isinstance(parent, dict):
                    parent.pop(key, None)
                else:
                    parent[key] = None
            else:
                raise SyncError(f"Unsupported mutation kind {kind}; update the tool before syncing")
            remains = not isinstance(parent, dict) or key in parent
            if kind != 2:
                delta = (size_of(parent[key]) if remains else 0) - (previous_bytes if present else 0)
            if isinstance(parent, dict) and present != remains:
                overhead = size_of(key) + 1
                delta += overhead + int(previous_count > 0) if remains else -overhead - int(previous_count > 1)
            state_bytes += delta
            if state_bytes > MAX_SNAPSHOT_BYTES:
                raise SyncError("Replayed session exceeds 2 GiB; refusing an oversized live snapshot")
        except (ValueError, TypeError, KeyError, SyncError) as error:
            raise SyncError(f"Invalid JSONL at line {line_number}: {error}") from error
    if not initialized:
        raise SyncError("Empty session log")
    return state


def parse_log(text: str | Iterable[str]) -> dict[str, Any]:
    lines = io.StringIO(text) if isinstance(text, str) else text

    def entries() -> Iterator[tuple[int, Any]]:
        for number, line in enumerate(lines, 1):
            if line.strip():
                try:
                    yield number, json_loads(line)
                except ValueError as error:
                    raise SyncError(f"Invalid JSONL at line {number}: {error}") from error

    return _replay(entries(), _json_size)


def normalize(data: Any, expected_id: str) -> dict[str, Any]:
    session_id(expected_id)
    if not isinstance(data, dict) or not isinstance(data.get("requests"), list):
        raise SyncError("Not a native Copilot session (expected an object with requests)")
    version = data.get("version", 1)
    if type(version) is not int or version not in (1, 2, 3):
        raise SyncError(f"Unsupported native session version: {version!r}")
    if data.get("sessionId") != expected_id:
        raise SyncError("Session ID does not match the file name")
    if any(not isinstance(request, dict) or "message" not in request for request in data["requests"]):
        raise SyncError("Invalid request in transcript")
    created = data.get("creationDate", 0)
    if type(created) not in (int, float) or not math.isfinite(created) or created < 0:
        raise SyncError("Invalid session creation date")
    location = data.get("initialLocation", "panel")
    if location not in ("panel", "editing-session"):
        raise SyncError(f"Only legacy panel sessions are supported, not {location!r}")
    result = {
        "version": 3,
        "sessionId": expected_id,
        "creationDate": created,
        "initialLocation": "panel",
        "responderUsername": data.get("responderUsername", "GitHub Copilot"),
        "requests": copy.deepcopy(data["requests"]),
    }
    title = data.get("customTitle", data.get("computedTitle"))
    if isinstance(title, str) and title:
        result["customTitle"] = title
    if not isinstance(result["responderUsername"], str):
        raise SyncError("Invalid responder name")
    return result


def load_session(path: Path) -> dict[str, Any]:
    try:
        if path.suffix == ".jsonl":
            with stable_file(path, MAX_LOG_BYTES) as stream:
                data = _replay(_log_entries(stream), _json_size)
        else:
            data = load_json(path)
        return normalize(data, path.stem)
    except MemoryError as error:
        raise SyncError(f"Cannot read session {path}: Insufficient memory; no chat was truncated") from error
    except (OSError, UnicodeError, ValueError, ijson.JSONError, SyncError) as error:
        raise SyncError(f"Cannot read session {path}: {error}") from error


def native_document(data: dict[str, Any], suffix: str = ".jsonl") -> dict[str, Any]:
    document = {"kind": 0, "v": data} if suffix == ".jsonl" else data
    if _json_size(document) + 1 > MAX_SNAPSHOT_BYTES:
        raise SyncError("Compacted session exceeds 2 GiB; refusing an unreadable import")
    return document


def native_bytes(data: dict[str, Any], suffix: str = ".jsonl") -> bytes:
    return b"".join(canonical_chunks(native_document(data, suffix), newline=True))


def metadata(data: dict[str, Any]) -> dict[str, Any]:
    requests = data["requests"]
    title = data.get("customTitle", "")
    if not title and requests:
        message = requests[0]["message"]
        if isinstance(message, str):
            title = message
        elif isinstance(message, dict):
            title = message.get("text", "")
            if not title:
                title = " ".join(part.get("text", "") for part in message.get("parts", []) if isinstance(part, dict))
    if not isinstance(title, str):
        title = ""
    created = data["creationDate"]
    timestamp = requests[-1].get("timestamp", created) if requests else created
    if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
        timestamp = created
    return {
        "sessionId": data["sessionId"],
        "title": (title.splitlines()[0][:200] if title.strip() else "New Chat"),
        "lastMessageDate": timestamp,
        "timing": {"created": created, "lastRequestStarted": timestamp, "lastRequestEnded": timestamp},
        "initialLocation": "panel",
        "isEmpty": not requests,
        "isExternal": False,
        "hasPendingEdits": False,
    }
