"""Content-addressed session revisions preserve divergent offline histories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .safety import atomic_write, is_regular, plain_path
from .sessions import SyncError, canonical_bytes, digest, json_loads, normalize, read_stable, session_id

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

    @property
    def session(self) -> dict[str, Any]:
        if self.data is not None:
            return self.data
        if self.path is None:
            raise SyncError("Revision has no payload")
        envelope = json_loads(read_stable(self.path).decode("utf-8"))
        if digest(envelope) != self.revision:
            raise SyncError(f"Revision changed after scanning: {self.path}")
        return envelope["session"]


class Store:
    def __init__(self, root: Path):
        self.root = root
        self.graphs: dict[str, dict[str, Revision]] = {}

    def initialize(self) -> None:
        plain_path(self.root, self.root)
        marker = self.root / "format.json"
        if marker.exists():
            self.load()
            return
        if self.root.exists() and any(self.root.iterdir()):
            raise SyncError("Choose an empty shared folder, not the old flat chatSessions folder")
        atomic_write(marker, canonical_bytes(MARKER) + b"\n")

    def load(self) -> Store:
        try:
            marker = plain_path(self.root / "format.json", self.root)
            if json_loads(read_stable(marker).decode("utf-8")) != MARKER:
                raise SyncError("Unsupported shared-store format")
            graphs: dict[str, dict[str, Revision]] = {}
            revisions_dir = plain_path(self.root / "revisions", self.root)
            if revisions_dir.exists():
                for directory in sorted(revisions_dir.iterdir()):
                    plain_path(directory, self.root)
                    identifier = session_id(directory.name)
                    if not directory.is_dir():
                        raise SyncError(f"Unexpected store entry: {directory}")
                    graph: dict[str, Revision] = {}
                    for path in sorted(directory.iterdir()):
                        if path.name.startswith(".pending-"):
                            continue
                        plain_path(path, self.root)
                        if path.suffix != ".json" or not REVISION_ID.fullmatch(path.stem) or not is_regular(path):
                            raise SyncError(f"Unexpected revision/conflict copy: {path}")
                        envelope = json_loads(read_stable(path).decode("utf-8"))
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
                        data = normalize(envelope["session"], identifier)
                        if data != envelope["session"]:
                            raise SyncError(f"Revision contains unsupported session-level state: {path}")
                        graph[path.stem] = Revision(path.stem, tuple(parents), envelope["writer"], digest(data), path=path)
                    for revision in graph.values():
                        missing = set(revision.parents) - graph.keys()
                        if missing:
                            raise SyncError(f"Incomplete OneDrive download for {identifier}; missing parent {sorted(missing)[0]}")
                    if graph:
                        graphs[identifier] = graph
            self.graphs = graphs
            for identifier in graphs:
                if not self.heads(identifier):
                    raise SyncError(f"Revision graph has no head: {identifier}")
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

    def publish(self, data: dict[str, Any], parents: list[str], writer: str, dry_run: bool = False) -> Revision:
        identifier = session_id(data["sessionId"])
        session_id(writer)
        data = normalize(data, identifier)
        graph = self.graphs.get(identifier, {})
        if set(parents) - graph.keys():
            raise SyncError(f"The last synced revision is not downloaded for {identifier}; wait for OneDrive")
        envelope = {"schema": 1, "session": data, "parents": sorted(set(parents)), "writer": writer}
        revision_id = digest(envelope)
        path = plain_path(self.root / "revisions" / identifier / (revision_id + ".json"), self.root)
        content = canonical_bytes(envelope) + b"\n"
        if path.exists():
            if read_stable(path) != content:
                raise SyncError(f"Refusing to replace a non-identical immutable revision: {path}")
        elif not dry_run:
            atomic_write(path, content)
        revision = Revision(revision_id, tuple(envelope["parents"]), writer, digest(data), data=data)
        self.graphs.setdefault(identifier, {})[revision_id] = revision
        return revision

    def conflicts(self) -> dict[str, list[Revision]]:
        return {identifier: self.heads(identifier) for identifier in self.graphs
                if len({head.content_hash for head in self.heads(identifier)}) > 1}
