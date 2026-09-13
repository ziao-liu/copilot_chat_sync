"""Update only known legacy chat keys, with SQLite compare-and-swap checks."""

from __future__ import annotations

import base64
import copy
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from .sessions import SyncError, canonical_bytes, json_loads, metadata

INDEX = "chat.ChatSessionStore.index"
MODEL_CACHE = "agentSessions.model.cache"
STATE_CACHE = "agentSessions.state.cache"
KEYS = (INDEX, MODEL_CACHE, STATE_CACHE)


def connect(path: Path, writable: bool = False) -> sqlite3.Connection:
    mode = "rw" if writable else "ro"
    try:
        connection = sqlite3.connect(path.absolute().as_uri() + f"?mode={mode}", uri=True, timeout=2)
        connection.execute("PRAGMA trusted_schema=OFF")
        return connection
    except sqlite3.Error as error:
        raise SyncError(f"Cannot open existing VS Code database {path}: {error}") from error


def _read(connection: sqlite3.Connection) -> dict[str, str | None]:
    result = {}
    for key in KEYS:
        row = connection.execute("SELECT value FROM ItemTable WHERE key = ?", (key,)).fetchone()
        value = row[0] if row else None
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        if value is not None and not isinstance(value, str):
            raise SyncError(f"Unsupported value type for {key}")
        result[key] = value
    return result


def read_keys(path: Path) -> dict[str, str | None]:
    try:
        with closing(connect(path)) as connection:
            if connection.execute("PRAGMA quick_check(1)").fetchone() != ("ok",):
                raise SyncError(f"Database integrity check failed: {path}")
            return _read(connection)
    except (sqlite3.Error, UnicodeError) as error:
        raise SyncError(f"Invalid VS Code database {path}: {error}") from error


def backup_database(path: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(connect(path)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)


def write_keys(path: Path, expected: dict[str, str | None], replacement: dict[str, str | None]) -> None:
    if set(expected) != set(KEYS) or set(replacement) != set(KEYS):
        raise SyncError("Only the three chat keys may be updated")
    with closing(connect(path, writable=True)) as connection:
        try:
            connection.execute("BEGIN IMMEDIATE")
            if _read(connection) != expected:
                raise SyncError("Chat index changed after preflight; close VS Code and retry")
            for key, value in replacement.items():
                if value is None:
                    connection.execute("DELETE FROM ItemTable WHERE key = ?", (key,))
                else:
                    connection.execute("INSERT OR REPLACE INTO ItemTable (key,value) VALUES (?,?)", (key, value))
            connection.commit()
        except (sqlite3.Error, SyncError):
            connection.rollback()
            raise


def merge_keys(before: dict[str, str | None], sessions: dict[str, dict[str, Any]]) -> dict[str, str | None]:
    try:
        index = json_loads(before[INDEX]) if before[INDEX] is not None else {"version": 1, "entries": {}}
        model = json_loads(before[MODEL_CACHE]) if before[MODEL_CACHE] is not None else []
        state = json_loads(before[STATE_CACHE]) if before[STATE_CACHE] is not None else []
    except (ValueError, TypeError) as error:
        raise SyncError("Corrupt chat index/cache; preserve the database and repair it separately") from error
    if not isinstance(index, dict) or index.get("version") != 1 or not isinstance(index.get("entries"), dict):
        raise SyncError("Unsupported chat index schema; refusing to rewrite it")
    if any(not isinstance(entry, dict) for entry in index["entries"].values()):
        raise SyncError("Invalid chat index entry")
    for cache in (model, state):
        if not isinstance(cache, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("resource"), str) for entry in cache):
            raise SyncError("Unsupported agent cache schema; refusing to rewrite it")
    index, model, state = copy.deepcopy(index), copy.deepcopy(model), copy.deepcopy(state)
    for identifier, data in sessions.items():
        entry = metadata(data)
        last_state = data["requests"][-1].get("modelState", {}) if data["requests"] else {}
        response_state = last_state.get("value", 1) if isinstance(last_state, dict) else 1
        entry["lastResponseState"] = response_state if response_state in (1, 2, 3) else 2
        entry["isImported"] = False
        index["entries"][identifier] = {**index["entries"].get(identifier, {}), **entry}
        resource = "vscode-chat-session://local/" + base64.urlsafe_b64encode(identifier.encode()).decode().rstrip("=")
        previous_model = next((item for item in model if item["resource"] == resource), {})
        previous_state = next((item for item in state if item["resource"] == resource), {})
        model = [item for item in model if item["resource"] != resource]
        state = [item for item in state if item["resource"] != resource]
        if not entry["isEmpty"]:
            model.append({**previous_model, "providerType": "local", "providerLabel": "Local", "resource": resource,
                          "icon": "vm", "label": entry["title"], "status": 1, "timing": entry["timing"]})
            state.append({"resource": resource, "archived": False, "read": entry["lastMessageDate"], **previous_state})
    return {key: canonical_bytes(value).decode("utf-8") for key, value in zip(KEYS, (index, model, state))}
