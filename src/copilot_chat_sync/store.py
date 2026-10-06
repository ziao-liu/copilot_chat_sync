"""Content-addressed session revisions preserve divergent offline histories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from .progress import file_checked, report, steps
from .cache import current, signature
from .index import index_entry

from .safety import atomic_write, atomic_write_chunks, is_regular, plain_path
from .sessions import MAX_SNAPSHOT_BYTES, SyncError, _json_size, canonical_bytes, canonical_chunks, chunks_digest, digest, file_digest, json_loads, load_json, normalize, read_stable, session_id

REVISION_ID = re.compile(r"[0-9a-f]{64}\Z")
MARKER = {"format": "copilot-chat-sync", "version": 1}


@dataclass(frozen=True)
class Revision:
    revision: str
    parents: tuple[str, ...]
    writer: str
    content_hash: str
    path: Path | None = None
    data: dict[str, Any] | None = None
    entry: dict[str, Any] | None = None
    request_count: int = 0

    @property
    def session(self) -> dict[str, Any]:
        if self.data is not None:
            return self.data
        if self.path is None:
            raise SyncError("Revision has no payload")
        cache = current.get()
        before, _, saved = cache.lookup(self.path, "revision") if cache else (None, "", None)
        envelope = load_json(self.path)
        if before is not None and signature(self.path) != before:
            raise SyncError(f"Revision changed while reading: {self.path}")
        if (saved is None or saved.get("revision") != self.revision) and digest(envelope) != self.revision:
            raise SyncError(f"Revision changed after scanning: {self.path}")
        return envelope["session"]


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.graphs: dict[str, dict[str, Revision]] = {}

    def initialize(self, dry_run: bool = False) -> None:
        plain_path(self.root, self.root)
        marker = self.root / "format.json"
        if marker.exists():
            self.load()
            return
        if self.root.exists() and any(self.root.iterdir()):
            raise SyncError("Choose an empty shared folder, not the old flat chatSessions folder")
        if not dry_run:
            atomic_write(marker, canonical_bytes(MARKER) + b"\n")

    def load(self) -> Store:
        try:
            marker = plain_path(self.root / "format.json", self.root)
            if json_loads(read_stable(marker).decode("utf-8")) != MARKER:
                raise SyncError("Unsupported shared-store format")
            graphs: dict[str, dict[str, Revision]] = {}
            revisions_dir = plain_path(self.root / "revisions", self.root)
            directories: list[tuple[str, list[Path]]] = []
            report("列出共享聊天版本")
            if revisions_dir.exists():
                for directory in sorted(revisions_dir.iterdir()):
                    plain_path(directory, self.root)
                    identifier = session_id(directory.name)
                    if not directory.is_dir():
                        raise SyncError(f"Unexpected store entry: {directory}")
                    directories.append((identifier, [path for path in sorted(directory.iterdir())
                                                     if not path.name.startswith(".pending-")]))
            with steps(sum(len(paths) for _, paths in directories) + 1) as advance:
                for identifier, paths in directories:
                    graph: dict[str, Revision] = {}
                    for path in paths:
                        plain_path(path, self.root)
                        if path.suffix != ".json" or not REVISION_ID.fullmatch(path.stem) or not is_regular(path):
                            raise SyncError(f"Unexpected revision/conflict copy: {path}")
                        cache = current.get()
                        before, raw_hash, saved = cache.lookup(path, "revision") if cache else (None, "", None)
                        if saved is not None:
                            if saved.get("revision") != path.stem:
                                raise SyncError(f"Invalid cached revision ID: {path}")
                            graph[path.stem] = Revision(path.stem, tuple(saved["parents"]), saved["writer"],
                                                        saved["content_hash"], path=path, entry=saved["entry"], request_count=saved["requests"])
                            file_checked()
                            advance()
                            continue
                        envelope = load_json(path)
                        if not isinstance(envelope, dict) or set(envelope) != {"schema", "parents", "session", "writer"} or envelope["schema"] != 1:
                            raise SyncError(f"Unsupported revision format: {path}")
                        if digest(envelope) != path.stem:
                            raise SyncError(f"Revision checksum mismatch: {path}")
                        parents = envelope["parents"]
                        if not isinstance(parents, list) or any(not isinstance(parent, str) or not REVISION_ID.fullmatch(parent) for parent in parents):
                            raise SyncError(f"Invalid revision ancestry: {path}")
                        if len(set(parents)) != len(parents) or path.stem in parents:
                            raise SyncError(f"Invalid revision ancestry: {path}")
                        session_id(envelope["writer"])
                        data = normalize(envelope["session"], identifier, copy_requests=False)
                        if data != envelope["session"]:
                            raise SyncError(f"Revision contains unsupported session-level state: {path}")
                        content_hash = digest(data)
                        entry = index_entry(data)
                        graph[path.stem] = Revision(path.stem, tuple(parents), envelope["writer"], content_hash, path=path,
                                                    entry=entry, request_count=len(data["requests"]))
                        if cache is not None and before is not None:
                            cache.save(path, "revision", before, raw_hash, {"revision": path.stem, "parents": parents,
                                       "writer": envelope["writer"], "content_hash": content_hash, "entry": entry, "requests": len(data["requests"])})
                        del envelope, data
                        file_checked()
                        advance()
                    for revision in graph.values():
                        missing = set(revision.parents) - graph.keys()
                        if missing:
                            raise SyncError(f"Incomplete OneDrive download for {identifier}; missing parent {sorted(missing)[0]}")
                    if graph:
                        graphs[identifier] = graph
                self.graphs = graphs
                report("检查历史版本关系")
                for identifier in graphs:
                    if not self.heads(identifier):
                        raise SyncError(f"Revision graph has no head: {identifier}")
                advance()
            return self
        except (OSError, ValueError, UnicodeError) as error:
            raise SyncError(f"Shared store is unavailable/incomplete at {self.root}: {error}") from error

    def heads(self, identifier: str) -> list[Revision]:
        graph = self.graphs.get(identifier, {})
        parents = {parent for revision in graph.values() for parent in revision.parents}
        return [graph[key] for key in sorted(graph.keys() - parents)]

    def chosen(self, identifier: str) -> Revision:
        heads = self.heads(identifier)
        if not heads:
            raise SyncError(f"No shared revision for {identifier}")
        if len({head.content_hash for head in heads}) > 1:
            raise SyncError(f"Divergent history for {identifier}; use conflicts, export-revision, then resolve. No version was overwritten.")
        return heads[0]

    def publish(self, data: dict[str, Any], parents: list[str], writer: str, dry_run: bool = False,
                *, retain_data: bool = True, content_hash: str | None = None) -> Revision:
        identifier = session_id(data["sessionId"])
        session_id(writer)
        data = normalize(data, identifier, copy_requests=retain_data)
        graph = self.graphs.get(identifier, {})
        if set(parents) - graph.keys():
            raise SyncError(f"The last synced revision is not downloaded for {identifier}; wait for OneDrive")
        envelope = {"schema": 1, "session": data, "parents": sorted(set(parents)), "writer": writer}
        if _json_size(envelope) + 1 > MAX_SNAPSHOT_BYTES:
            raise SyncError("Shared revision exceeds 2 GiB after replay; no oversized revision was written")
        revision_id = digest(envelope)
        path = plain_path(self.root / "revisions" / identifier / (revision_id + ".json"), self.root)
        if path.exists():
            if file_digest(path) != chunks_digest(canonical_chunks(envelope, newline=True)):
                raise SyncError(f"Refusing to replace a non-identical immutable revision: {path}")
        elif not dry_run:
            atomic_write_chunks(path, canonical_chunks(envelope, newline=True))
        content_hash = content_hash or digest(data)
        entry = index_entry(data)
        revision = Revision(revision_id, tuple(envelope["parents"]), writer, content_hash,
                            data=data if retain_data else None, path=path if not dry_run else None, entry=entry,
                            request_count=len(data["requests"]))
        cache = current.get()
        if cache is not None and not dry_run:
            before, raw_hash, _ = cache.lookup(path, "revision")
            cache.save(path, "revision", before, raw_hash, {"revision": revision_id, "parents": envelope["parents"],
                       "writer": writer, "content_hash": content_hash, "entry": entry, "requests": len(data["requests"])})
        self.graphs.setdefault(identifier, {})[revision_id] = revision
        return revision

    def conflicts(self) -> dict[str, list[Revision]]:
        return {identifier: self.heads(identifier) for identifier in self.graphs
                if len({head.content_hash for head in self.heads(identifier)}) > 1}
