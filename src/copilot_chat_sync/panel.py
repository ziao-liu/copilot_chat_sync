"""Authenticated loopback panel over the existing CLI safety boundary."""

from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import secrets
import socket
import sqlite3
import threading
import time
import tempfile
import uuid
import webbrowser
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .safety import code_processes, is_redirect
from .sessions import SyncError, canonical_bytes, native_bytes, normalize, session_id
from .store import REVISION_ID, Store
from .sync import operation
from .transaction import BACKUP_ID
from .workspace import Config, Workspace, default_storage, default_store, expand_path, workspace_id

PLAN_TTL = 120
MAX_BODY = 32 * 1024
ASSETS = Path(__file__).with_name("web")


class PanelError(SyncError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _options(data: object) -> dict:
    if not isinstance(data, dict):
        raise PanelError("Expected a JSON object")
    fields = {
        "init": {"store", "storage", "workspaces"}, "bindings": {"workspaces"},
        "push": {"workspaces"}, "pull": {"workspaces", "detach"},
        "repair": {"workspaces", "detach"}, "migrate": {"workspaces"},
        "resolve": {"session", "revision"}, "restore": {"backup"},
    }
    action = data.get("action")
    if not isinstance(action, str) or action not in fields or set(data) - fields[action] - {"action"}:
        raise PanelError("Unsupported action or action fields")
    result = copy.deepcopy(data)
    for key, value in result.items():
        if key == "workspaces":
            if not isinstance(value, list) or len(value) > 200:
                raise PanelError("Select at most 200 workspaces")
            for identifier in value:
                workspace_id(identifier)
            if len(set(value)) != len(value):
                raise PanelError("Duplicate workspace selection")
        elif key == "detach":
            if type(value) is not bool:
                raise PanelError("detach must be a boolean")
        elif not isinstance(value, str) or not value or len(value) > 4096 or "\x00" in value:
            raise PanelError(f"Invalid {key}")
    if action in ("push", "pull", "repair", "migrate", "bindings") and "workspaces" not in result:
        raise PanelError("An explicit workspace selection is required")
    if action in ("push", "pull", "repair", "migrate") and not result["workspaces"]:
        raise PanelError("Select at least one bound workspace")
    if action == "init" and "workspaces" in result and not result["workspaces"]:
        raise PanelError("Select at least one workspace")
    for key in ({"store", "storage"} if action == "init" else {"session", "revision"} if action == "resolve" else {"backup"} if action == "restore" else set()):
        if key not in result:
            raise PanelError(f"Missing {key}")
    if action == "resolve":
        session_id(result["session"])
        if not REVISION_ID.fullmatch(result["revision"]):
            raise PanelError("Select a full revision ID")
    if action == "restore" and not BACKUP_ID.fullmatch(result["backup"]):
        raise PanelError("Select a valid backup ID")
    return result


class Panel:
    def __init__(self, config_path: Path, demo: bool = False):
        self.config_path = config_path
        self.demo = demo
        self.token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.plan: dict | None = None
        self.activity: list[dict] = []

    @contextmanager
    def exclusive(self) -> Iterator[None]:
        if not self.lock.acquire(blocking=False):
            raise PanelError("Another panel operation is in progress", 409)
        try:
            yield
        finally:
            self.lock.release()

    def _dispatch(self, arguments: list[str]) -> dict:
        from .cli import dispatch, parser
        return dispatch(parser().parse_args(["--config", str(self.config_path), *arguments]))

    def _execute(self, options: dict, apply: bool) -> dict:
        action = options["action"]
        if action == "bindings":
            config = Config.load(self.config_path)
            selected = [Workspace.open(config.storage, identifier) for identifier in options["workspaces"]]
            previous = {binding["id"] for binding in config.bindings}
            current = set(options["workspaces"])
            result = {"operation": action, "applied": apply, "added": sorted(current - previous),
                      "removed": sorted(previous - current), "bound": len(current)}
            config.bindings = [{"id": workspace.identifier, "uri": workspace.uri} for workspace in selected]
            config.validate()
            if apply:
                with operation(config, True):
                    config.save()
            return result
        arguments = [action]
        if action == "init":
            arguments.extend(["--store=" + options["store"], "--storage-root=" + options["storage"]])
            arguments.extend("--workspace=" + identifier for identifier in options.get("workspaces", []))
        elif action in ("push", "pull", "repair", "migrate"):
            for identifier in options["workspaces"]:
                arguments.append("--workspace=" + identifier)
            if options.get("detach"):
                arguments.append("--detach-edit-state")
        elif action == "resolve":
            arguments.extend([options["session"], "--revision=" + options["revision"]])
        elif action == "restore":
            arguments.append(options["backup"])
        if apply:
            arguments.append("--apply")
        return self._dispatch(arguments)

    def _stamp(self, options: dict) -> str:
        paths = [self.config_path]
        trees: list[Path] = []
        if options["action"] == "init":
            trees.append(expand_path(options["store"]))
            storage = expand_path(options["storage"])
            paths.append(storage)
            for identifier in sorted(options.get("workspaces", [])):
                paths.extend(storage / identifier / name for name in ("workspace.json", "chatSessions"))
        else:
            config = Config.load(self.config_path)
            paths.extend([config.state_path, config.store / "format.json"])
            trees.append(config.store / "revisions")
            selected = set(options.get("workspaces", [])) | {binding["id"] for binding in config.bindings}
            for identifier in sorted(selected):
                directory = config.storage / identifier
                paths.extend(directory / name for name in ("workspace.json", "state.vscdb", "state.vscdb-wal", "state.vscdb-shm"))
                trees.extend(directory / name for name in ("chatSessions", "chatEditingSessions"))
            if options["action"] == "restore":
                trees.append(config.backups)
        digest = hashlib.sha256()
        count = 0

        def include(path: Path) -> None:
            nonlocal count
            count += 1
            if count > 100000:
                raise PanelError("Preview input exceeds 100,000 files; use the CLI for this group")
            try:
                info = path.lstat()
                record = (str(path), info.st_size, info.st_mtime_ns, info.st_ino, info.st_mode)
            except FileNotFoundError:
                record = (str(path), None)
            digest.update(canonical_bytes(record))

        for path in paths:
            include(path)
        for root in trees:
            include(root)
            if is_redirect(root):
                include(root.resolve())
                if root.name == "chatSessions" and root.is_dir():
                    for path in sorted(root.iterdir()):
                        include(path)
                continue
            for directory, subdirectories, files in os.walk(root, followlinks=False):
                subdirectories.sort()
                for name in [*subdirectories, *sorted(files)]:
                    include(Path(directory) / name)
                subdirectories[:] = [name for name in subdirectories if not is_redirect(Path(directory) / name)]
        return digest.hexdigest()

    def snapshot(self) -> dict:
        warnings = []
        try:
            suggested_store = str(default_store())
        except SyncError:
            suggested_store = ""
        result = {"version": __version__, "demo": self.demo, "configured": self.config_path.exists(),
                  "config_path": str(self.config_path), "hostname": socket.gethostname(),
                  "defaults": {"store": suggested_store, "storage": str(default_storage())},
                  "workspaces": [], "conflicts": [], "backups": [], "activity": self.activity[-30:][::-1],
                  "issues": warnings, "code_processes": [], "process_check_ok": True}
        try:
            result["code_processes"] = code_processes()
        except SyncError as error:
            result["process_check_ok"] = False
            warnings.append(str(error))
        if not self.config_path.exists():
            return result
        config = Config.load(self.config_path)
        result["config"] = {"store": str(config.store), "storage": str(config.storage), "device": config.device}
        scanned = self._dispatch(["scan"])
        warnings.extend(scanned["issues"])
        bindings = {binding["id"]: binding["uri"] for binding in config.bindings}
        rows = {row["id"]: {**row, "bound": row["id"] in bindings} for row in scanned["workspaces"]}
        for identifier, uri in bindings.items():
            if identifier not in rows:
                rows[identifier] = {"id": identifier, "uri": uri, "bound": True, "missing": True, "sessions": 0, "linked": False}
        if bindings:
            try:
                status = self._dispatch(["status"])
                warnings.extend(status["issues"])
                for row in status["native_workspaces"]:
                    rows[row["id"]].update(row)
            except SyncError as error:
                warnings.append(str(error))
        result["workspaces"] = list(rows.values())
        try:
            store = Store(config.store).load()
            result["shared"] = {"sessions": len(store.graphs), "revisions": sum(len(graph) for graph in store.graphs.values()),
                                "writers": sorted({revision.writer for graph in store.graphs.values() for revision in graph.values()})}
            result["conflicts"] = self._dispatch(["conflicts"])["conflicts"]
        except SyncError as error:
            warnings.append(str(error))
        try:
            result["backups"] = self._dispatch(["backups"])["backups"]
        except (SyncError, ValueError, OSError) as error:
            warnings.append(str(error))
        result["issues"] = list(dict.fromkeys(warnings))
        return result

    def preview(self, data: object) -> dict:
        options = _options(data)
        self.plan = None
        before = self._stamp(options)
        result = self._execute(options, False)
        if self._stamp(options) != before:
            raise PanelError("Files changed during preview. Refresh and preview again.", 409)
        identifier = secrets.token_urlsafe(24)
        self.plan = {"id": identifier, "options": options, "stamp": before, "result": result,
                     "expires": time.monotonic() + PLAN_TTL}
        return {"plan": identifier, "expires_in": PLAN_TTL, "action": options["action"], "result": result,
                "read_only": self.demo, "needs_acknowledgement": bool(options.get("detach"))}

    def apply(self, data: object) -> dict:
        if self.demo:
            raise PanelError("The demo is read-only. No synchronization will be applied.", 403)
        if not isinstance(data, dict) or set(data) - {"plan", "acknowledge"} or not isinstance(data.get("plan"), str):
            raise PanelError("Apply requires a preview ticket")
        plan = self.plan
        if plan is None or not hmac.compare_digest(plan["id"].encode(), data["plan"].encode()):
            raise PanelError("Preview ticket is missing, consumed or replaced. Preview again.", 409)
        if plan["options"].get("detach") and data.get("acknowledge") is not True:
            raise PanelError("Confirm loss of the affected chat undo/checkpoints before quarantine")
        self.plan = None
        if time.monotonic() > plan["expires"] or self._stamp(plan["options"]) != plan["stamp"]:
            raise PanelError("Preview expired or files changed. Refresh and preview again.", 409)
        try:
            result = self._execute(plan["options"], True)
        except (SyncError, OSError, ValueError, sqlite3.Error) as error:
            self.record(plan["options"]["action"], "error", str(error))
            raise
        self.record(plan["options"]["action"], "conflict" if result.get("conflicts") else "complete", result)
        return result

    def record(self, action: str, status: str, result: object) -> None:
        self.activity.append({"time": datetime.now(timezone.utc).isoformat(), "action": action, "status": status, "result": result})
        self.activity = self.activity[-30:]

    def revision(self, identifier: str, revision_id: str) -> dict:
        session_id(identifier)
        if not REVISION_ID.fullmatch(revision_id):
            raise PanelError("Invalid revision ID")
        config = Config.load(self.config_path)
        revision = Store(config.store).load().graphs.get(identifier, {}).get(revision_id)
        if revision is None:
            raise PanelError("Revision not found", 404)
        return revision.session


class PanelServer(ThreadingHTTPServer):
    daemon_threads = False
    allow_reuse_address = False

    def __init__(self, port: int, panel: Panel):
        self.panel = panel
        super().__init__(("127.0.0.1", port), PanelHandler)
        self.origin = f"http://127.0.0.1:{self.server_port}"


class PanelHandler(BaseHTTPRequestHandler):
    server: PanelServer

    def log_message(self, format: str, *args: object) -> None:
        pass

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def _reply(self, status: int, content: bytes, content_type: str = "application/json; charset=utf-8") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(content)

    def _authorize(self, api: bool, write: bool = False) -> None:
        authority = self.server.origin.removeprefix("http://")
        if self.headers.get("Host") != authority:
            raise PanelError("Invalid Host header", 403)
        origin = self.headers.get("Origin")
        if (write or origin is not None) and origin != self.server.origin:
            raise PanelError("Cross-origin requests are not allowed", 403)
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise PanelError("Cross-site requests are not allowed", 403)
        if api:
            expected = "Bearer " + self.server.panel.token
            if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode()):
                raise PanelError("Open the private URL printed by the panel command", 401)

    def _body(self) -> object:
        if self.headers.get("Transfer-Encoding") or self.headers.get_content_type() != "application/json":
            raise PanelError("Only JSON request bodies are accepted", 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise PanelError("Invalid content length") from error
        if not 0 < length <= MAX_BODY:
            raise PanelError("Request body is empty or too large", 413)
        try:
            return json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError) as error:
            raise PanelError("Invalid JSON request") from error

    def _request(self, write: bool) -> None:
        try:
            url = urlsplit(self.path)
            api = url.path.startswith("/api/")
            self._authorize(api, write)
            if not api:
                if write:
                    raise PanelError("Not found", 404)
                static = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                          "/style.css": ("style.css", "text/css; charset=utf-8"),
                          "/vendor/lucide.js": ("vendor/lucide.js", "text/javascript; charset=utf-8"),
                          "/vendor/plex-sans.woff2": ("vendor/plex-sans.woff2", "font/woff2")}
                asset = static.get(url.path)
                if asset is None or not (ASSETS / asset[0]).is_file():
                    raise PanelError("Not found", 404)
                self._reply(200, (ASSETS / asset[0]).read_bytes(), asset[1])
                return
            with self.server.panel.exclusive():
                if write:
                    data = self._body()
                    if url.path == "/api/preview":
                        result = self.server.panel.preview(data)
                    elif url.path == "/api/apply":
                        result = self.server.panel.apply(data)
                    elif url.path == "/api/scan":
                        if not isinstance(data, dict) or set(data) != {"storage"} or not isinstance(data["storage"], str) or len(data["storage"]) > 4096:
                            raise PanelError("Provide a storage root")
                        if self.server.panel.demo and expand_path(data["storage"]) != Config.load(self.server.panel.config_path).storage:
                            raise PanelError("Demo scans are limited to the temporary demonstration storage", 403)
                        result = self.server.panel._dispatch(["scan", "--storage-root=" + data["storage"]])
                    elif url.path == "/api/doctor":
                        result = self.server.panel._dispatch(["doctor"])
                    else:
                        raise PanelError("Not found", 404)
                elif url.path == "/api/state":
                    result = self.server.panel.snapshot()
                elif url.path == "/api/revision":
                    query = parse_qs(url.query)
                    if set(query) != {"session", "revision"} or any(len(values) != 1 for values in query.values()):
                        raise PanelError("Provide one session and revision")
                    result = self.server.panel.revision(query["session"][0], query["revision"][0])
                else:
                    raise PanelError("Not found", 404)
            self._reply(200, canonical_bytes(result))
        except (PanelError, SyncError, OSError, ValueError, sqlite3.Error) as error:
            status = error.status if isinstance(error, PanelError) else 400
            self._reply(status, canonical_bytes({"error": str(error)}))

    def do_GET(self) -> None:
        self._request(False)

    def do_POST(self) -> None:
        self._request(True)


def demo_config(root: Path) -> Path:
    from .index import merge_keys, read_keys
    from .transaction import WorkspaceUpdate, apply_updates
    storage = root / "native"
    config = Config(root / "control/config.json", root / "shared/Research", storage,
                    device="22222222-2222-4222-8222-222222222222")
    writer = "33333333-3333-4333-8333-333333333333"
    store = Store(config.store)
    store.initialize()
    topics = ["Review the retrieval evaluation", "Align the training configuration", "Audit the dataset split",
              "Check the temporal encoder", "Plan the ablation study", "Trace the feature cache",
              "Review deployment requirements", "Validate the sampling strategy", "Inspect the loss function",
              "Compare the evaluation runs", "Prepare release checks", "Document the experiment settings"]
    sessions = []
    for number, topic in enumerate(topics):
        identifier = str(uuid.uuid5(uuid.NAMESPACE_URL, f"copilot-chat-sync/demo/{number}"))
        data = normalize({"version": 3, "sessionId": identifier, "creationDate": 1789254000000 + number * 3600000,
                          "customTitle": topic, "requests": [{"requestId": "demo-request", "message": {"text": topic},
                          "timestamp": 1789254000000 + number * 3600000,
                          "response": [{"value": "The current configuration is consistent. The next step is a focused check with a small fixture before changing the experiment."}]}]}, identifier)
        revision = store.publish(data, [], config.device if number < 8 else writer)
        if number == 10:
            for author, message in ((config.device, "Add a CPU smoke test before packaging."), (writer, "Validate the Windows launcher first.")):
                branch = copy.deepcopy(data)
                branch["requests"].append({"message": message, "timestamp": data["creationDate"] + 600000})
                store.publish(branch, [revision.revision], author)
        sessions.append(data)
    for number, (host, folder) in enumerate((("atlas-proxy", "research"), ("atlas", "research"),
                                            ("nova-proxy", "research-next"), ("nova", "research-next"))):
        identifier = hashlib.md5(f"demo-{host}".encode()).hexdigest()
        directory = storage / identifier
        chats = directory / "chatSessions"
        chats.mkdir(parents=True)
        uri = f"vscode-remote://ssh-remote%2B{host}/home/demo/{folder}"
        (directory / "workspace.json").write_bytes(canonical_bytes({"folder": uri}))
        with closing(sqlite3.connect(directory / "state.vscdb")) as connection, connection:
            connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        local = {data["sessionId"]: data for data in sessions[:(8 if number < 2 else 5)]}
        for data in local.values():
            (chats / (data["sessionId"] + ".jsonl")).write_bytes(native_bytes(data))
        workspace = Workspace.open(storage, identifier)
        before = read_keys(workspace.database)
        apply_updates(config, [WorkspaceUpdate(workspace, before, merge_keys(before, local))])
        if number < 3:
            config.bindings.append({"id": identifier, "uri": uri})
    config.save()
    return config.path


def serve(config_path: Path, port: int = 8765, open_browser: bool = True, demo: bool = False) -> None:
    if not 0 <= port <= 65535:
        raise SyncError("Port must be between 0 and 65535")
    temporary = tempfile.TemporaryDirectory(prefix="copilot-chat-sync-panel-") if demo else None
    try:
        panel = Panel(demo_config(Path(temporary.name)) if temporary else config_path, demo=demo)
        try:
            server = PanelServer(port, panel)
        except OSError:
            if port == 0:
                raise
            server = PanelServer(0, panel)
        url = server.origin + "/#token=" + panel.token
        print(f"{'Read-only demo' if demo else 'Local panel'}: {url}", flush=True)
        print("Keep this terminal open. Press Ctrl+C to stop. Do not share the private URL.", flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    finally:
        if temporary:
            temporary.cleanup()