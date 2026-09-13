"""Read VS Code JSON/JSONL transcripts without loading editing checkpoints."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

MAX_SESSION_BYTES = 128 * 1024 * 1024
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


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_stable(path: Path, limit: int = MAX_SESSION_BYTES) -> bytes:
    before = path.stat()
    if before.st_size > limit:
        raise SyncError(f"File exceeds {limit} bytes: {path}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    after = path.stat()
    if len(data) > limit:
        raise SyncError(f"File exceeds {limit} bytes: {path}")
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise SyncError(f"File changed while reading; close VS Code and wait for OneDrive: {path}")
    return data


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


def parse_log(text: str) -> dict[str, Any]:
    state: Any = None
    initialized = False
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            entry = json_loads(line)
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
                initialized = True
                continue
            if not initialized:
                raise SyncError("Log is missing its initial snapshot")
            parent, key = _parent(state, entry.get("k"))
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
                    del array[start:]
                values = entry.get("v", [])
                if not isinstance(values, list):
                    raise SyncError("Push values must be an array")
                array.extend(values)
                parent[key] = array
            elif kind == 3:
                if isinstance(parent, dict):
                    parent.pop(key, None)
                else:
                    parent[key] = None
            else:
                raise SyncError(f"Unsupported mutation kind {kind}; update the tool before syncing")
        except (ValueError, TypeError, KeyError, SyncError) as error:
            raise SyncError(f"Invalid JSONL at line {line_number}: {error}") from error
    if not initialized:
        raise SyncError("Empty session log")
    return state


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
        text = read_stable(path).decode("utf-8-sig")
        data = parse_log(text) if path.suffix == ".jsonl" else json_loads(text)
        return normalize(data, path.stem)
    except (OSError, UnicodeError, ValueError, SyncError) as error:
        raise SyncError(f"Cannot read session {path}: {error}") from error


def native_bytes(data: dict[str, Any], suffix: str = ".jsonl") -> bytes:
    return canonical_bytes({"kind": 0, "v": data} if suffix == ".jsonl" else data) + b"\n"


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
