"""Command line interface. Mutating commands preview unless --apply is supplied."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import __version__
from .index import INDEX, merge_keys, read_keys
from .safety import code_processes, is_redirect
from .sessions import SyncError, canonical_bytes, json_loads, metadata
from .store import Store
from .sync import migrate, operation, pull, push, repair, resolve, restore
from .transaction import list_backups
from .workspace import Config, Workspace, default_config, default_storage, default_store, discover, expand_path


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="copilot-chat-sync", description=__doc__)
    root.add_argument("--version", action="version", version=__version__)
    root.add_argument("--config", type=expand_path, default=default_config(), help="Local-only config, never put it in OneDrive")
    commands = root.add_subparsers(dest="command", required=True)
    panel = commands.add_parser("panel", help="Open the authenticated local web panel")
    panel.add_argument("--port", type=int, default=8765, help="Preferred loopback port; a free port is used if occupied")
    panel.add_argument("--no-browser", action="store_true", help="Print the private URL without opening a browser")
    panel.add_argument("--demo", action="store_true", help="Read-only demonstration with isolated temporary data")
    scan = commands.add_parser("scan", help="Read actual VS Code workspace IDs and URIs")
    scan.add_argument("--storage-root", type=expand_path)
    scan.add_argument("--insiders", action="store_true")
    init = commands.add_parser("init", help="Configure an empty versioned shared folder (not the old junction target)")
    init.add_argument("--store", type=expand_path)
    init.add_argument("--storage-root", type=expand_path)
    init.add_argument("--insiders", action="store_true")
    init.add_argument("--apply", action="store_true")
    bind = commands.add_parser("bind", help="Bind an existing native workspace to this shared group")
    choice = bind.add_mutually_exclusive_group(required=True)
    choice.add_argument("--workspace", help="Actual ID printed by scan")
    choice.add_argument("--uri", help="Exact folder/workspace URI; encoded + and literal + are equivalent")
    choice.add_argument("--server", help="SSH alias from local workspace metadata")
    bind.add_argument("--path", help="Case-sensitive remote folder path, used with --server")
    bind.add_argument("--apply", action="store_true")
    for command in ("status", "doctor", "conflicts", "backups"):
        commands.add_parser(command)
    for command in ("push", "pull", "repair", "migrate"):
        action = commands.add_parser(command)
        action.add_argument("--workspace", action="append", help="Restrict to a bound ID; repeat for multiple workspaces")
        action.add_argument("--apply", action="store_true")
        if command in ("pull", "repair"):
            action.add_argument("--detach-edit-state", action="store_true", help="Explicitly quarantine affected edit snapshots; loses their undo/checkpoints, never changes code")
    resolution = commands.add_parser("resolve", help="Select one competing head; keep all other revisions in the archive")
    resolution.add_argument("session")
    resolution.add_argument("--revision", required=True)
    resolution.add_argument("--apply", action="store_true")
    restoration = commands.add_parser("restore", help="Restore chat files/keys from a local backup, only if not subsequently edited")
    restoration.add_argument("backup")
    restoration.add_argument("--apply", action="store_true")
    export = commands.add_parser("export-revision", help="Export a shared revision as JSON without opening the native chat")
    export.add_argument("session")
    export.add_argument("--revision")
    export.add_argument("--output", required=True, type=expand_path)
    export.add_argument("--apply", action="store_true")
    return root


def _scan(storage: Path) -> dict:
    workspaces, issues = discover(storage)
    rows = []
    for workspace in workspaces:
        try:
            files = workspace.session_files(allow_redirect=True)
            rows.append({"id": workspace.identifier, "uri": workspace.uri, "sessions": len(files),
                         "linked": is_redirect(workspace.chats)})
        except SyncError as error:
            issues.append(str(error))
    return {"storage": str(storage), "workspaces": rows, "issues": issues}


def _status(config: Config, doctor: bool) -> dict:
    issues, rows = [], []
    try:
        running = code_processes()
    except SyncError as error:
        running = []
        issues.append(str(error))
    for workspace in config.workspaces():
        try:
            linked = is_redirect(workspace.chats)
            files = workspace.session_files(allow_redirect=True)
            keys = read_keys(workspace.database)
            merge_keys(keys, {})
            index = json_loads(keys[INDEX]) if keys[INDEX] else {"entries": {}}
            editing = [identifier for identifier in files if workspace.editing_state(identifier)]
            rows.append({"id": workspace.identifier, "uri": workspace.uri, "sessions": len(files),
                         "indexed": len(index.get("entries", {})), "linked": linked, "editing_snapshots": len(editing)})
            if linked:
                issues.append(f"{workspace.identifier}: migrate old junction before push/pull")
            if editing:
                issues.append(f"{workspace.identifier}: editing snapshots may restore old buffers; pull/repair requires explicit quarantine")
            if doctor:
                for path in files.values():
                    from .sessions import load_session
                    load_session(path)
        except (SyncError, ValueError, OSError) as error:
            issues.append(str(error))
    shared = {}
    try:
        store = Store(config.store).load()
        shared = {"sessions": len(store.graphs), "revisions": sum(len(graph) for graph in store.graphs.values()),
                  "conflicts": sorted(store.conflicts())}
        if shared["conflicts"]:
            issues.append("Resolve divergent shared histories before pulling")
    except SyncError as error:
        issues.append(str(error))
    backups = list_backups(config)
    if any(entry["status"] in ("prepared", "needs-recovery") for entry in backups):
        issues.append("An interrupted local transaction needs restore; run backups")
    return {"python": sys.executable, "python_version": sys.version.split()[0], "device": config.device,
            "config": str(config.path), "shared_store": str(config.store), "native_workspaces": rows,
            "shared": shared, "code_processes": running, "issues": issues,
            "note": "Counts describe local files only. OneDrive must finish uploading/downloading before a handoff."}


def dispatch(args: argparse.Namespace) -> dict:
    if args.command == "scan":
        storage = args.storage_root
        if storage is None:
            storage = Config.load(args.config).storage if args.config.exists() and not args.insiders else default_storage(args.insiders)
        return _scan(storage)
    if args.command == "init":
        if args.config.exists():
            raise SyncError("Config already exists; it will not be overwritten")
        config = Config(args.config, args.store or default_store(), args.storage_root or default_storage(args.insiders))
        config.validate()
        if not config.storage.is_dir():
            raise SyncError("Open the folder once in VS Code, or provide the correct --storage-root")
        if args.apply:
            with operation(config, True):
                Store(config.store).initialize()
                config.save()
        return {"operation": "init", "applied": args.apply, "config": str(config.path),
                "store": str(config.store), "storage": str(config.storage), "next": "scan, then bind an existing workspace"}
    config = Config.load(args.config)
    if args.command == "bind":
        if bool(args.server) != bool(args.path):
            raise SyncError("--server and --path must be used together")
        if args.workspace:
            workspace = Workspace.open(config.storage, args.workspace)
        else:
            workspaces, issues = discover(config.storage)
            if args.uri:
                candidates = [workspace for workspace in workspaces if unquote(workspace.uri) == unquote(args.uri)]
            else:
                candidates = []
                for candidate in workspaces:
                    uri = urlsplit(unquote(candidate.uri))
                    if uri.scheme == "vscode-remote" and uri.netloc == "ssh-remote+" + args.server and uri.path == args.path:
                        candidates.append(candidate)
            if len(candidates) != 1:
                raise SyncError(f"Expected one workspace, found {len(candidates)}. Use scan and bind --workspace ID. " + " ".join(issues))
            workspace = candidates[0]
        config.bindings = [binding for binding in config.bindings if binding["id"] != workspace.identifier]
        config.bindings.append({"id": workspace.identifier, "uri": workspace.uri})
        if args.apply:
            with operation(config, True):
                config.save()
        return {"operation": "bind", "applied": args.apply, "bindings": config.bindings}
    if args.command in ("status", "doctor"):
        return _status(config, args.command == "doctor")
    if args.command in ("push", "pull", "repair", "migrate"):
        functions = {"push": push, "pull": pull, "repair": repair, "migrate": migrate}
        options = {"apply": args.apply, "selected": args.workspace}
        if args.command in ("pull", "repair"):
            options["detach"] = args.detach_edit_state
        return functions[args.command](config, **options)
    if args.command == "conflicts":
        store = Store(config.store).load()
        return {"conflicts": [{"session": identifier, "heads": [
            {"revision": head.revision, "writer": head.writer, "requests": len(head.session["requests"]),
             "last_message_date": metadata(head.session)["lastMessageDate"]} for head in heads]}
            for identifier, heads in store.conflicts().items()]}
    if args.command == "resolve":
        return resolve(config, args.session, args.revision, args.apply)
    if args.command == "backups":
        return {"directory": str(config.backups), "backups": list_backups(config)}
    if args.command == "restore":
        return restore(config, args.backup, args.apply)
    if args.command == "export-revision":
        store = Store(config.store).load()
        revision = store.graphs.get(args.session, {}).get(args.revision) if args.revision else store.chosen(args.session)
        if revision is None:
            raise SyncError("Shared revision not found")
        if args.output.suffix.lower() != ".json" or args.output.exists():
            raise SyncError("Export requires a new .json file; existing files are never overwritten")
        for root in (config.store.resolve(), config.storage.resolve(), config.path.parent.resolve()):
            if args.output.resolve().is_relative_to(root):
                raise SyncError("Export outside the shared store, native storage, and control directory")
        if args.apply:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb") as stream:
                stream.write(canonical_bytes(revision.session) + b"\n")
        return {"operation": "export-revision", "applied": args.apply, "output": str(args.output), "revision": revision.revision}
    raise SyncError("Unknown command")


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "panel":
            from .panel import serve
            serve(args.config, args.port, not args.no_browser, args.demo)
            return 0
        result = dispatch(args)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        if result.get("conflicts"):
            return 3
        if args.command == "doctor" and result.get("issues"):
            return 2
        return 0
    except (SyncError, OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted. Check backups before retrying an apply operation.", file=sys.stderr)
        return 130
