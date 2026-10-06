"""Explicit handoffs between native local sessions and an immutable shared store."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator

from .cache import cache_scope, current, signature
from .index import index_entry, merge_entries, read_keys
from .progress import report, steps
from .safety import atomic_copy, atomic_write, atomic_write_chunks, is_redirect, local_lock, plain_path, require_closed
from .sessions import SyncError, canonical_bytes, canonical_chunks, digest, file_digest, json_loads, load_session, native_document, read_stable
from .store import REVISION_ID, Store
from .transaction import FileUpdate, WorkspaceUpdate, apply_updates, fingerprint, new_backup_id, require_recovered, restore_backup
from .workspace import Config, Workspace, workspace_id


def load_state(config: Config) -> dict:
    if not config.state_path.exists():
        return {"version": 1, "store": str(config.store), "workspaces": {}}
    try:
        data = json_loads(read_stable(config.state_path).decode("utf-8"))
        if data["version"] != 1 or data["store"] != str(config.store) or not isinstance(data["workspaces"], dict):
            raise SyncError("Local sync state belongs to a different store or version")
        for identifier, revisions in data["workspaces"].items():
            workspace_id(identifier)
            if not isinstance(revisions, dict) or any(not isinstance(revision, str) or not REVISION_ID.fullmatch(revision) for revision in revisions.values()):
                raise SyncError("Invalid local sync state")
        return data
    except (ValueError, KeyError, TypeError) as error:
        raise SyncError(f"Corrupt local sync state; preserve it before repair: {error}") from error


@contextmanager
def operation(config: Config, apply: bool, recovery: bool = False) -> Iterator[None]:
    config.validate()
    if not apply:
        with cache_scope(config.path.with_suffix(".cache.sqlite"), persist=False):
            yield
        return
    require_closed()
    storage_key = hashlib.sha256(str(config.storage.resolve()).encode()).hexdigest()
    lock_root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "copilot-chat-sync-locks"
    with local_lock(lock_root / (storage_key + ".lock")), local_lock(config.path.with_suffix(".lock")):
        if not recovery:
            require_recovered(config)
        require_closed()
        with cache_scope(config.path.with_suffix(".cache.sqlite")):
            yield


def _local(path: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    cache = current.get()
    before, raw_hash, saved = cache.lookup(path, "native") if cache else (None, file_digest(path), None)
    if saved is not None:
        return {**saved, "raw_hash": raw_hash}, None
    data = load_session(path)
    saved = {"content_hash": digest(data), "entry": index_entry(data)}
    if cache is not None and before is not None:
        cache.save(path, "native", before, raw_hash, saved)
    return {**saved, "raw_hash": raw_hash}, data


def _base(store: Store, state: dict, workspace: Workspace, identifier: str):
    revision = state["workspaces"].get(workspace.identifier, {}).get(identifier)
    if revision is None:
        return None
    graph = store.graphs.get(identifier, {})
    if revision not in graph:
        raise SyncError(f"Last synced revision for {identifier} is missing. Wait for OneDrive; do not reset local state.")
    return graph[revision]


def push(config: Config, apply: bool = False, selected: list[str] | None = None) -> dict:
    with operation(config, apply), steps(3) as advance:
        store = Store(config.store).load()
        advance()
        state = load_state(config)
        sources = [(workspace, workspace.session_files()) for workspace in config.workspaces(selected)]
        for workspace, paths in sources:
            for identifier in paths:
                _base(store, state, workspace, identifier)
        published = 0
        unchanged = 0
        with steps(sum(len(paths) for _, paths in sources)) as session_done:
            for workspace, paths in sources:
                local = state["workspaces"].setdefault(workspace.identifier, {})
                for identifier, path in paths.items():
                    summary, data = _local(path)
                    content_hash = summary["content_hash"]
                    base = _base(store, state, workspace, identifier)
                    heads = store.heads(identifier)
                    matching = next((head for head in heads if head.content_hash == content_hash), None)
                    if matching is not None:
                        local[identifier] = matching.revision
                        unchanged += 1
                    elif base is not None and base.content_hash == content_hash:
                        unchanged += 1
                    else:
                        published += 1
                        if apply:
                            require_closed()
                        if data is None:
                            data = load_session(path)
                            if digest(data) != content_hash:
                                raise SyncError(f"Session changed after validation: {path}")
                        revision = store.publish(data, [base.revision] if base else [], config.device, dry_run=not apply,
                                                 retain_data=False, content_hash=content_hash)
                        local[identifier] = revision.revision
                    del data
                    session_done()
        advance()
        report("保存发送状态" if apply else "完成发送方案", "")
        if apply:
            atomic_write(config.state_path, canonical_bytes(state) + b"\n")
        advance()
        return {"operation": "push", "applied": apply, "published" if apply else "would_publish": published,
                "unchanged": unchanged, "conflicts": sorted(store.conflicts()),
                "note": "This reports the local OneDrive folder, not confirmation of cloud upload."}


def _update(workspace: Workspace, sessions: dict[str, dict[str, Any]], files: list[FileUpdate], detach: bool) -> WorkspaceUpdate:
    return _update_entries(workspace, {identifier: index_entry(data) for identifier, data in sessions.items()}, files, detach)


def _update_entries(workspace: Workspace, entries: dict[str, dict[str, Any]], files: list[FileUpdate], detach: bool) -> WorkspaceUpdate:
    plain_path(workspace.database, workspace.directory)
    editing = [identifier for identifier in entries if workspace.editing_state(identifier) is not None]
    if editing and not detach:
        raise SyncError(f"Editing snapshots exist in {workspace.identifier} for {editing[0]}. Verify code, then explicitly use --detach-edit-state to quarantine snapshots (loses old undo/checkpoints, not code).")
    before = read_keys(workspace.database)
    after = merge_entries(before, entries)
    return WorkspaceUpdate(workspace, before, after, files, editing)


def pull(config: Config, apply: bool = False, selected: list[str] | None = None, detach: bool = False) -> dict:
    with operation(config, apply), TemporaryDirectory(prefix="chat-sync-stage-") as temporary, steps(3) as advance:
        store = Store(config.store).load()
        advance()
        state = load_state(config)
        heads = {identifier: store.chosen(identifier) for identifier in store.graphs}
        updates = []
        workspaces = config.workspaces(selected)
        with steps(len(workspaces) * (len(heads) + 1)) as session_done:
            for workspace in workspaces:
                paths = workspace.session_files()
                files = []
                imported = {}
                for identifier, head in heads.items():
                    base = _base(store, state, workspace, identifier)
                    summary = None
                    if identifier in paths:
                        summary, data = _local(paths[identifier])
                        del data
                    if summary is not None and summary["content_hash"] != head.content_hash:
                        if base is None or summary["content_hash"] != base.content_hash:
                            raise SyncError(f"Unpublished local changes in {workspace.identifier}/{identifier}. Push them first; pull will not overwrite them.")
                    if head.entry is None:
                        raise SyncError("Shared revision has no validated index metadata")
                    imported[identifier] = head.entry
                    if summary is None or summary["content_hash"] != head.content_hash:
                        incoming = head.session
                        path = paths.get(identifier, workspace.chats / (identifier + ".jsonl"))
                        document = native_document(incoming, path.suffix)
                        staged = Path(temporary) / f"{workspace.identifier}-{identifier}{path.suffix}"
                        after_hash = None
                        if apply:
                            atomic_write_chunks(staged, canonical_chunks(document, newline=True))
                            after_hash = file_digest(staged)
                        files.append(FileUpdate(path, staged if apply else b"", summary["raw_hash"] if summary else None, after_hash))
                        del incoming, document
                    state["workspaces"].setdefault(workspace.identifier, {})[identifier] = head.revision
                    session_done()
                if imported:
                    updates.append(_update_entries(workspace, imported, files, detach))
                session_done()
        advance()
        report("写入聊天、索引与同步状态" if apply else "完成接收方案", "")
        backup = None
        if apply:
            require_closed()
            backup = apply_updates(config, updates)
            atomic_write(config.state_path, canonical_bytes(state) + b"\n")
            for update in updates:
                for file in update.files:
                    cache = current.get()
                    if cache is not None:
                        before = signature(file.path)
                        raw_hash = file_digest(file.path)
                        if raw_hash != file.after_hash:
                            raise SyncError(f"Session changed after import; newer edits were preserved: {file.path}")
                        head = heads[file.path.stem]
                        cache.save(file.path, "native", before, raw_hash,
                                   {"content_hash": head.content_hash, "entry": head.entry})
        advance()
        return {"operation": "pull", "applied": apply, "files": sum(len(update.files) for update in updates),
                "indexes": sum(update.before != update.after for update in updates),
                "editing_snapshots_to_quarantine": sum(len(update.detach) for update in updates), "backup": backup}


def repair(config: Config, apply: bool = False, selected: list[str] | None = None, detach: bool = False) -> dict:
    with operation(config, apply):
        updates = []
        for workspace in config.workspaces(selected):
            entries = {}
            for identifier, path in workspace.session_files().items():
                summary, data = _local(path)
                entries[identifier] = summary["entry"]
                del data
            updates.append(_update_entries(workspace, entries, [], detach))
        backup = apply_updates(config, updates) if apply else None
        return {"operation": "repair", "applied": apply, "indexes": sum(update.before != update.after for update in updates),
                "editing_snapshots_to_quarantine": sum(len(update.detach) for update in updates), "backup": backup}


def resolve(config: Config, identifier: str, revision: str, apply: bool = False) -> dict:
    with operation(config, apply):
        store = Store(config.store).load()
        heads = store.heads(identifier)
        chosen = next((head for head in heads if head.revision == revision), None)
        if chosen is None:
            raise SyncError("Choose a full head revision ID from conflicts; old versions remain exportable")
        if len(heads) < 2:
            raise SyncError("This session has no competing heads")
        result = store.publish(chosen.session, [head.revision for head in heads], config.device,
                               retain_data=False, content_hash=chosen.content_hash) if apply else None
        return {"operation": "resolve", "applied": apply, "session": identifier,
                "chosen": revision, "new_revision": result.revision if result else None,
                "note": "Unchosen revisions are retained. Pull to update local sessions."}


def restore(config: Config, identifier: str, apply: bool = False) -> dict:
    with operation(config, apply, recovery=True):
        result = restore_backup(config, identifier, apply)
        if apply:
            state = load_state(config)
            state["workspaces"] = {}
            atomic_write(config.state_path, canonical_bytes(state) + b"\n")
        return result


def migrate(config: Config, apply: bool = False, selected: list[str] | None = None) -> dict:
    with operation(config, apply):
        workspaces = [workspace for workspace in config.workspaces(selected) if is_redirect(workspace.chats)]
        prepared = []
        for workspace in workspaces:
            paths = workspace.session_files(allow_redirect=True)
            files = {path.name: file_digest(path) for path in paths.values()}
            for path in paths.values():
                load_session(path)
            if not files:
                raise SyncError(f"Linked session folder is empty/unavailable: {workspace.chats}")
            prepared.append((workspace, files))
        identifier = new_backup_id()
        directory = config.backups / identifier
        journal = {"version": 1, "storage": str(config.storage), "status": "prepared",
                   "files": [], "databases": [], "quarantined": [], "migrations": []}
        results = []
        for workspace, files in prepared:
            retained = workspace.directory / ("chatSessions.link-before-" + identifier)
            staging = plain_path(workspace.directory / ("chatSessions.staging-" + identifier), config.storage)
            if retained.exists() or is_redirect(retained) or staging.exists():
                raise SyncError("Migration staging/backup path already exists")
            target = str(workspace.chats.resolve())
            journal["migrations"].append({"workspace": workspace.identifier, "target": target, "files": files})
            if apply:
                for name, expected in files.items():
                    source = workspace.chats / name
                    atomic_copy(source, directory / "migration-files" / workspace.identifier / "chatSessions" / name, expected)
                    atomic_copy(source, staging / name, expected)
            results.append({"workspace": workspace.identifier, "files": len(files), "retained_link": str(retained) if apply else None})
        if apply and prepared:
            atomic_write(directory / "journal.json", canonical_bytes(journal) + b"\n")
            try:
                for (workspace, files), entry in zip(prepared, journal["migrations"]):
                    require_closed()
                    if not is_redirect(workspace.chats) or str(workspace.chats.resolve()) != entry["target"]:
                        raise SyncError("Junction changed during migration")
                    current = workspace.session_files(allow_redirect=True)
                    if {path.name for path in current.values()} != set(files):
                        raise SyncError("Shared session files changed during migration")
                    if any(fingerprint(workspace.chats / name) != expected for name, expected in entry["files"].items()):
                        raise SyncError("Shared sessions changed during migration")
                    retained = workspace.directory / ("chatSessions.link-before-" + identifier)
                    staging = workspace.directory / ("chatSessions.staging-" + identifier)
                    workspace.chats.rename(retained)
                    staging.rename(workspace.chats)
                journal["status"] = "complete"
                atomic_write(directory / "journal.json", canonical_bytes(journal) + b"\n")
            except BaseException as error:
                raise SyncError(f"Migration interrupted; shared data is untouched. Run restore {identifier} --apply before reopening VS Code: {error}") from error
        return {"operation": "migrate", "applied": apply, "workspaces": results, "backup": identifier if apply and prepared else None,
                "note": "Old shared targets are untouched. Disable previous sync/link scripts on every PC; now use push/pull."}
