"""Journal local chat changes before touching files or SQLite keys."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .index import backup_database, read_keys, write_keys
from .safety import atomic_write, is_redirect, plain_path
from .sessions import SyncError, canonical_bytes, json_loads, read_stable, session_id
from .workspace import Config, Workspace, workspace_id

BACKUP_ID = re.compile(r"[0-9]{8}T[0-9]{6}-[0-9a-f]{8}\Z")


def fingerprint(path: Path) -> str | None:
    return hashlib.sha256(read_stable(path)).hexdigest() if path.exists() else None


def new_backup_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


@dataclass
class FileUpdate:
    path: Path
    data: bytes
    before_hash: str | None


@dataclass
class WorkspaceUpdate:
    workspace: Workspace
    before: dict[str, str | None]
    after: dict[str, str | None]
    files: list[FileUpdate] = field(default_factory=list)
    detach: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.files or self.detach or self.before != self.after)


def _chat_path(root: Path, relative: str) -> Path:
    parts = relative.split("/")
    if len(parts) != 3 or parts[1] != "chatSessions":
        raise SyncError("Backup contains a path outside chatSessions")
    workspace_id(parts[0])
    name = Path(parts[2])
    if name.suffix not in (".json", ".jsonl"):
        raise SyncError("Backup contains an unsupported file type")
    session_id(name.stem)
    return plain_path(root.joinpath(*parts), root)


def list_backups(config: Config) -> list[dict]:
    if not config.backups.exists():
        return []
    result = []
    for directory in sorted(config.backups.iterdir()):
        if BACKUP_ID.fullmatch(directory.name):
            path = plain_path(directory / "journal.json", config.backups)
            if path.exists():
                data = json_loads(read_stable(path).decode("utf-8"))
                result.append({"id": directory.name, "status": data.get("status", "unknown"),
                               "files": len(data.get("files", [])), "databases": len(data.get("databases", [])),
                               "migrations": len(data.get("migrations", []))})
    return result


def require_recovered(config: Config) -> None:
    pending = [entry["id"] for entry in list_backups(config) if entry["status"] in ("prepared", "needs-recovery")]
    if pending:
        raise SyncError("An interrupted operation needs recovery: restore " + pending[0] + " --apply")


def apply_updates(config: Config, updates: list[WorkspaceUpdate]) -> str | None:
    updates = [update for update in updates if update.changed]
    if not updates:
        return None
    identifier = new_backup_id()
    directory = config.backups / identifier
    journal = {"version": 1, "storage": str(config.storage), "status": "prepared",
               "files": [], "databases": [], "quarantined": []}
    for update in updates:
        workspace = update.workspace
        plain_path(workspace.database, config.storage)
        if read_keys(workspace.database) != update.before:
            raise SyncError("Database changed after planning; no changes applied")
        for file in update.files:
            relative = file.path.relative_to(config.storage).as_posix()
            _chat_path(config.storage, relative)
            if fingerprint(file.path) != file.before_hash:
                raise SyncError(f"Session changed after planning: {file.path}")
            if file.before_hash is not None:
                atomic_write(directory / "files" / relative, read_stable(file.path))
            journal["files"].append({"path": relative, "before": file.before_hash,
                                     "after": hashlib.sha256(file.data).hexdigest()})
        if update.before != update.after:
            backup_database(workspace.database, directory / "databases" / (workspace.identifier + ".sqlite"))
            journal["databases"].append({"workspace": workspace.identifier, "before": update.before, "after": update.after})
        for session in update.detach:
            source = workspace.editing_state(session)
            if source is not None:
                destination = plain_path(workspace.directory / ".chat-sync-quarantine" / identifier / session, config.storage)
                if destination.exists():
                    raise SyncError(f"Quarantine destination already exists: {destination}")
                journal["quarantined"].append({"workspace": workspace.identifier, "session": session})
    atomic_write(directory / "journal.json", canonical_bytes(journal) + b"\n")
    try:
        for item in journal["quarantined"]:
            source = config.storage / item["workspace"] / "chatEditingSessions" / item["session"]
            destination = config.storage / item["workspace"] / ".chat-sync-quarantine" / identifier / item["session"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
        for update in updates:
            for file in update.files:
                if fingerprint(file.path) != file.before_hash:
                    raise SyncError(f"Session changed during apply: {file.path}")
                atomic_write(file.path, file.data)
            if update.before != update.after:
                write_keys(update.workspace.database, update.before, update.after)
        journal["status"] = "complete"
        atomic_write(directory / "journal.json", canonical_bytes(journal) + b"\n")
        return identifier
    except BaseException as error:
        try:
            restore_backup(config, identifier, apply=True, restore_quarantine=True)
        except BaseException as recovery_error:
            raise SyncError(f"Apply failed; recovery required. Run restore {identifier} --apply. Original: {error}; recovery: {recovery_error}") from error
        raise SyncError(f"Apply failed and chat changes were rolled back; backup {identifier}: {error}") from error


def restore_backup(config: Config, identifier: str, apply: bool = False, restore_quarantine: bool = False) -> dict:
    if not BACKUP_ID.fullmatch(identifier):
        raise SyncError("Invalid backup ID; use backups to list available snapshots")
    directory = plain_path(config.backups / identifier, config.backups)
    journal_path = plain_path(directory / "journal.json", config.backups)
    journal = json_loads(read_stable(journal_path).decode("utf-8"))
    if journal.get("version") != 1 or journal.get("storage") != str(config.storage):
        raise SyncError("Backup belongs to another storage root or has an unsupported format")
    migration_plans = []
    for item in journal.get("migrations", []):
        workspace = plain_path(config.storage / workspace_id(item["workspace"]), config.storage)
        chats = workspace / "chatSessions"
        retained = workspace / ("chatSessions.link-before-" + identifier)
        if is_redirect(chats):
            if str(chats.resolve()) != item["target"] or retained.exists() or is_redirect(retained):
                raise SyncError("The junction changed since migration; recovery refused")
        else:
            plain_path(chats, config.storage)
        files = []
        for name, expected in item["files"].items():
            relative = item["workspace"] + "/chatSessions/" + name
            backup = _chat_path(directory / "migration-files", relative)
            if fingerprint(backup) != expected:
                raise SyncError("Migration backup checksum mismatch")
            if fingerprint(chats / name) not in (None, expected):
                raise SyncError("Newer chat content prevents migration recovery; original shared data is retained")
            files.append((chats / name, read_stable(backup)))
        migration_plans.append((chats, retained, files))
    for item in journal["files"]:
        path = _chat_path(config.storage, item["path"])
        if fingerprint(path) not in (item["before"], item["after"]):
            raise SyncError(f"Newer local changes prevent restoration: {path}")
        if item["before"] is not None:
            backup = _chat_path(directory / "files", item["path"])
            if fingerprint(backup) != item["before"]:
                raise SyncError(f"Backup checksum mismatch: {backup}")
    for item in journal["databases"]:
        path = plain_path(config.storage / workspace_id(item["workspace"]) / "state.vscdb", config.storage)
        if read_keys(path) not in (item["before"], item["after"]):
            raise SyncError("Chat index changed since this snapshot; automatic restoration refused")
    quarantine_paths = []
    for item in journal["quarantined"]:
        workspace = config.storage / workspace_id(item["workspace"])
        session = session_id(item["session"])
        source = plain_path(workspace / "chatEditingSessions" / session, config.storage)
        destination = plain_path(workspace / ".chat-sync-quarantine" / identifier / session, config.storage)
        if restore_quarantine and destination.exists() and source.exists():
            raise SyncError("Cannot rollback quarantine over a newly created editing session")
        quarantine_paths.append((source, destination))
    if apply:
        for chats, retained, files in migration_plans:
            if is_redirect(chats):
                chats.rename(retained)
            chats.mkdir(parents=True, exist_ok=True)
            for path, content in files:
                atomic_write(path, content)
        for item in journal["files"]:
            path = _chat_path(config.storage, item["path"])
            if item["before"] is None:
                path.unlink(missing_ok=True)
            else:
                atomic_write(path, read_stable(directory / "files" / item["path"]))
        for item in journal["databases"]:
            path = config.storage / item["workspace"] / "state.vscdb"
            write_keys(path, read_keys(path), item["before"])
        if restore_quarantine:
            for source, destination in quarantine_paths:
                if destination.exists():
                    source.parent.mkdir(parents=True, exist_ok=True)
                    destination.rename(source)
        journal["status"] = "restored"
        atomic_write(journal_path, canonical_bytes(journal) + b"\n")
    return {"backup": identifier, "applied": apply, "files": len(journal["files"]),
            "databases": len(journal["databases"]), "editing_snapshots_reactivated": restore_quarantine and apply,
            "migrations": len(migration_plans), "note": "Migration recovery completes independent local copies; live junctions are never reactivated."}
