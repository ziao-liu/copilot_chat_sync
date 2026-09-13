"""Discover actual local workspace metadata instead of guessing URI hashes."""

from __future__ import annotations

import os
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .safety import atomic_write, is_redirect, is_regular, plain_path
from .sessions import SyncError, canonical_bytes, json_loads, load_session, read_stable, session_id

WORKSPACE_ID = re.compile(r"[0-9a-f]{32}(?:-[0-9]+)?\Z")


def expand_path(value: str | Path) -> Path:
    return Path(os.path.expandvars(str(value))).expanduser().absolute()


def default_config() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "CopilotChatSync/config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "copilot-chat-sync/config.json"


def default_storage(insiders: bool = False) -> Path:
    application = "Code - Insiders" if insiders else "Code"
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library/Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / application / "User/workspaceStorage"


def default_store() -> Path:
    for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
        if os.environ.get(name):
            return Path(os.environ[name]) / "CopilotChatSync"
    raise SyncError("OneDrive location was not detected. Supply --store with an empty/shared tool folder.")


def workspace_id(value: str) -> str:
    if not isinstance(value, str) or not WORKSPACE_ID.fullmatch(value):
        raise SyncError(f"Invalid workspace storage ID: {value!r}; use scan to find the actual ID")
    return value


@dataclass(frozen=True)
class Workspace:
    directory: Path
    uri: str

    @property
    def identifier(self) -> str:
        return self.directory.name

    @property
    def chats(self) -> Path:
        return self.directory / "chatSessions"

    @property
    def database(self) -> Path:
        return self.directory / "state.vscdb"

    @classmethod
    def open(cls, storage: Path, identifier: str) -> Workspace:
        directory = plain_path(storage / workspace_id(identifier), storage)
        path = plain_path(directory / "workspace.json", storage)
        try:
            data = json_loads(read_stable(path).decode("utf-8-sig"))
            uri = data.get("folder") or data.get("workspace")
            if not isinstance(uri, str) or not uri:
                raise SyncError(f"Unsupported workspace metadata: {path}")
            return cls(directory, uri)
        except (OSError, ValueError, UnicodeError, AttributeError) as error:
            raise SyncError(f"Cannot open workspace metadata {path}: {error}") from error

    def session_files(self, allow_redirect: bool = False) -> dict[str, Path]:
        if not allow_redirect:
            plain_path(self.chats, self.directory)
        if not self.chats.exists():
            return {}
        result = {}
        for path in sorted(self.chats.iterdir()):
            if path.suffix not in (".json", ".jsonl"):
                continue
            identifier = session_id(path.stem)
            if not is_regular(path):
                raise SyncError(f"Session is not a regular, non-redirected file: {path}")
            if identifier not in result or path.suffix == ".jsonl":
                result[identifier] = path
        return result

    def sessions(self) -> dict[str, dict[str, Any]]:
        return {identifier: load_session(path) for identifier, path in self.session_files().items()}

    def editing_state(self, identifier: str) -> Path | None:
        path = plain_path(self.directory / "chatEditingSessions" / session_id(identifier), self.directory)
        return path if path.exists() else None


def discover(storage: Path) -> tuple[list[Workspace], list[str]]:
    workspaces, errors = [], []
    if not storage.is_dir():
        return [], [f"Workspace storage does not exist: {storage}"]
    for directory in sorted(storage.iterdir()):
        if WORKSPACE_ID.fullmatch(directory.name) and (directory / "workspace.json").exists():
            try:
                workspaces.append(Workspace.open(storage, directory.name))
            except SyncError as error:
                errors.append(str(error))
    return workspaces, errors


@dataclass
class Config:
    path: Path
    store: Path
    storage: Path
    device: str = field(default_factory=lambda: str(uuid.uuid4()))
    bindings: list[dict[str, str]] = field(default_factory=list)

    @property
    def state_path(self) -> Path:
        return self.path.with_suffix(".state.json")

    @property
    def backups(self) -> Path:
        return self.path.parent / (self.path.stem + ".backups")

    def validate(self) -> None:
        session_id(self.device)
        roots = [self.store.resolve(), self.storage.resolve(), self.path.parent.resolve()]
        for index, left in enumerate(roots):
            for right in roots[index + 1:]:
                if left == right or left in right.parents or right in left.parents:
                    raise SyncError("Shared store, workspaceStorage and local config directory must be separate, non-nested directories")
        for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial"):
            if os.environ.get(name) and self.path.resolve().is_relative_to(expand_path(os.environ[name]).resolve()):
                raise SyncError("Local config/state must not be stored in OneDrive; use the default local config path")
        for path in (self.path, self.state_path, self.backups):
            if is_redirect(path):
                raise SyncError(f"Local control files must not be links: {path}")
        seen = set()
        for binding in self.bindings:
            identifier = workspace_id(binding["id"])
            if identifier in seen or not isinstance(binding["uri"], str):
                raise SyncError("Duplicate or invalid workspace binding")
            seen.add(identifier)

    def save(self) -> None:
        self.validate()
        data = {"version": 1, "store": str(self.store), "storage": str(self.storage),
                "device": self.device, "bindings": self.bindings}
        atomic_write(self.path, canonical_bytes(data) + b"\n")

    @classmethod
    def load(cls, path: Path) -> Config:
        try:
            data = json_loads(read_stable(path).decode("utf-8"))
            if data["version"] != 1 or not isinstance(data["bindings"], list):
                raise SyncError("Unsupported configuration format")
            config = cls(path, expand_path(data["store"]), expand_path(data["storage"]), data["device"], data["bindings"])
            config.validate()
            return config
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise SyncError(f"Cannot load config {path}; run init first: {error}") from error

    def workspaces(self, selected: list[str] | None = None) -> list[Workspace]:
        if selected and set(selected) - {binding["id"] for binding in self.bindings}:
            raise SyncError("Selected workspace is not bound in this configuration")
        result = []
        for binding in self.bindings:
            if selected and binding["id"] not in selected:
                continue
            workspace = Workspace.open(self.storage, binding["id"])
            if unquote(workspace.uri) != unquote(binding["uri"]):
                raise SyncError(f"Workspace URI changed for {workspace.identifier}; inspect and bind again")
            result.append(workspace)
        if not result:
            raise SyncError("No workspaces are bound. Run scan, then bind --workspace ID.")
        return result
