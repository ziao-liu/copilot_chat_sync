# Advanced Guide

[Quick start](../README.md)

## Separate Groups

A shared store is one conversation pool. Send publishes chats from the selected
workspaces; Receive imports all converged chats in the pool into each selected
workspace. Workspace names, SSH aliases and the folder tree do not create isolation.

Use a different local config **and a different shared store** for each unrelated group:

```powershell
python -m copilot_chat_sync --config "$env:LOCALAPPDATA\CopilotChatSync\work.json" panel
```

Configure a separate shared folder in that panel. On another computer, choose the
same cloud folder but keep its config, device ID, bindings and backups local.
Do not put local config inside OneDrive, native storage or the shared store.

Conversations are identified by `sessionId`, not their title. Matching content for
the same ID is deduplicated; divergent versions are retained as conflicts. Separate
IDs remain separate even when their titles match. Direct/proxy SSH aliases and
case-sensitive remote paths are not automatically paired or rewritten.

## Command-Line Setup

The Windows release includes Python and `psutil`; run `CopilotChatSync.exe` without
arguments to open the native WebView2 application window. Use `CopilotChatSync-CLI.exe`
for the CLI arguments shown below. The browser panel remains available via the CLI's
`panel` command. Desktop startup failures appear in a native error dialog.
Source installs need Python 3.10+: `python -m pip install .` installs the package
and its runtime dependency. Use an external terminal on the desktop running VS Code,
not the SSH server's terminal.

On Windows, an activated Anaconda/Miniconda prompt is suitable. WindowsApps Python
may be a Store placeholder. Check the actual interpreter before troubleshooting:

```powershell
python -c "import sys; print(sys.executable); print(sys.version)"
```

The source-checkout PowerShell launcher probes a real interpreter and propagates failures:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\chat-sync.ps1 scan
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\chat-sync.ps1 -PythonExecutable "C:\Users\alice\miniconda3\python.exe" doctor
```

It does not install Python or dependencies.

Open each desired project once using its intended SSH alias in desktop VS Code.
Back up current chats and code, then close all VS Code windows before applying changes.

```powershell
python -m copilot_chat_sync scan
python -m copilot_chat_sync init --store "D:\OneDrive\CopilotChatSync"
python -m copilot_chat_sync init --store "D:\OneDrive\CopilotChatSync" --apply
python -m copilot_chat_sync bind --workspace ID_FROM_SCAN --apply
python -m copilot_chat_sync doctor
```

All mutating CLI commands preview unless `--apply` is supplied. `init --workspace ID`
can include discovered workspaces in setup; repeat the option for multiple IDs.
Use `--storage-root` or `--insiders` with `scan`/`init` for nonstandard installations.
If `--store` is omitted, OneDrive environment variables supply the default location.

Bindings can also use an exact URI or SSH alias plus case-sensitive path:

```powershell
python -m copilot_chat_sync bind --server gpu-server-proxy --path /home/alice/project --apply
```

Ambiguous matches require the actual storage ID from `scan`, including any `-1`
suffix. Mark the shared store **Always keep on this device** in OneDrive.

Default config locations:

| Platform    | Location                                                                                      |
| ----------- | --------------------------------------------------------------------------------------------- |
| Windows     | `%LOCALAPPDATA%\CopilotChatSync\config.json`                                                  |
| Linux/macOS | `$XDG_CONFIG_HOME/copilot-chat-sync/config.json` or `~/.config/copilot-chat-sync/config.json` |

`--config PATH` is a global option **before** the subcommand. Local config, shared
store and native workspace storage must be separate, non-nested directories.

## Old Directory Links

Stop previous sync/link scripts on **every computer** first. The tool does not
stop them automatically. Use a new shared tool folder, not an old raw chat folder.
After setup and workspace selection, while VS Code is closed:

```powershell
python -m copilot_chat_sync migrate
python -m copilot_chat_sync migrate --apply
python -m copilot_chat_sync push
python -m copilot_chat_sync push --apply
```

Migration validates and backs up linked chats, then replaces the link with an
independent local directory. The original shared folder remains untouched. The
retained link is named `chatSessions.link-before-TIMESTAMP-ID`; leave it in place
rather than recursively deleting it with an unverified script. Repeat on each PC.

If interrupted, inspect `backups` and run `restore BACKUP_ID --apply` before
reopening VS Code. Migration recovery completes independent local copies; it does
not reactivate the live link. Staging directories may retain redundant safe copies.

## Daily Handoff

Close VS Code and send from the computer you just used:

```powershell
python -m copilot_chat_sync push
python -m copilot_chat_sync push --apply
```

Wait for OneDrive to be **Up to date** on both computers. On the receiving computer,
keep VS Code closed, publish any existing local changes, and review the import:

```powershell
python -m copilot_chat_sync push --apply
python -m copilot_chat_sync pull
python -m copilot_chat_sync pull --apply
```

Resolve any conflict before pulling. Use repeatable `--workspace ID` with `push`,
`pull`, `repair` or `migrate` to restrict the bound workspaces affected. Changing
SSH aliases on one computer is also a handoff. Avoid editing the same chat on
multiple devices concurrently; this tool does not splice conversation branches.

## Editing Snapshots

Saving, accepting an edit and committing to Git are different operations. Closing
VS Code does not normally undo a saved but unaccepted edit. However,
[VS Code issue #313703](https://github.com/microsoft/vscode/issues/313703) describes
old pending snapshots restoring stale buffers; Save/Auto Save can then overwrite code.

This tool never synchronizes `chatEditingSessions`, worktree diffs, queued requests
or session-level execution/editing state. Pull/repair refuses affected sessions
with local editing snapshots, including some accepted historical snapshots.

Verify and independently back up current code **without reopening a suspect chat**.
Then, only if you accept losing the affected old undo/checkpoints:

```powershell
python -m copilot_chat_sync pull --detach-edit-state
python -m copilot_chat_sync pull --detach-edit-state --apply
```

Snapshots move to `workspaceStorage/ID/.chat-sync-quarantine/BACKUP_ID/SESSION_ID`.
Quarantine does not restore project code or remove conversation text. Backup
restoration does not automatically reactivate snapshots. `repair --detach-edit-state`
does the same for native chats in the selected workspaces.

This does not fix VS Code or protect unrelated stale sessions. If opening a chat
unexpectedly dirties buffers, stop before Save All/Keep All and compare with disk/Git.

## Conflicts and Recovery

Wait for OneDrive on every computer so competing revisions have arrived, then:

```powershell
python -m copilot_chat_sync conflicts
python -m copilot_chat_sync export-revision SESSION_ID --revision FULL_REVISION_ID --output "D:\chat-exports\candidate.json" --apply
python -m copilot_chat_sync resolve SESSION_ID --revision FULL_HEAD_REVISION_ID
python -m copilot_chat_sync resolve SESSION_ID --revision FULL_HEAD_REVISION_ID --apply
python -m copilot_chat_sync pull --apply
```

Resolution selects a payload and records every known competing head as ancestry.
Other versions remain exportable. It cannot resolve a branch not yet delivered.

For a local recovery journal:

```powershell
python -m copilot_chat_sync backups
python -m copilot_chat_sync restore BACKUP_ID
python -m copilot_chat_sync restore BACKUP_ID --apply
```

Restore verifies hashes and the three chat index/cache keys; newer edits cause
refusal. Unrelated SQLite keys remain unchanged. Restore clears local sync ancestry
conservatively, so a later push can report a conflict. Full SQLite snapshots are
for expert recovery, not automatic whole-database replacement.

## Panel Security

The panel binds only `127.0.0.1`, normally on port 8765. An occupied port falls back
to an available one. `--port 0` chooses a free port; `--no-browser` only prints the URL.
Keep the external terminal running and use `Ctrl+C` to stop it.

API requests need a random per-launch token and valid Host/Origin. The URL fragment
is removed from the address bar and kept in tab session storage. Do not share the
private URL or expose the port to untrusted networks. Restart invalidates old tokens.

Changes require a separate preview and confirmation. Tickets expire after two
minutes, are single-use and become invalid when input metadata changes. Closed-editor
checks, local locks, conflict checks and recovery rules still run on apply. Quarantine
also requires explicit acknowledgment. `--demo` refuses writes at the server.

Fonts and icons are bundled with their third-party licenses. No telemetry, CDN or
cloud API is used. Activity is kept in memory for the panel process; recovery
journals persist. Writer IDs are historical authors, not online devices or an ACL.

## Command Reference

| Command                 | Purpose                                                   |
| ----------------------- | --------------------------------------------------------- |
| `panel`                 | Browser interface; `--demo` uses read-only synthetic data |
| `scan`                  | Actual workspace IDs, URIs, chat counts and links         |
| `init` / `bind`         | Local configuration and workspace selection               |
| `status` / `doctor`     | State and diagnostics; doctor also parses native chats    |
| `push` / `pull`         | Publish revisions / import converged chats and indexes    |
| `repair` / `migrate`    | Repair native indexes / detach old links                  |
| `conflicts` / `resolve` | Inspect and explicitly choose competing histories         |
| `export-revision`       | Export an archived revision as JSON                       |
| `backups` / `restore`   | Inspect and recover local transactions                    |

Run `python -m copilot_chat_sync COMMAND --help` for options. Results are JSON;
errors go to stderr. Exit codes: `0` success/preview, `2` validation/safety/I/O error,
`3` divergent histories, `130` interrupted outside a journaled operation.

## Compatibility and Privacy

- Supports legacy extension-host, UUID-named `.json`/`.jsonl` chats, serialized
  versions 1-3, JSONL operations 0/1/2/3, index version 1 and list-shaped agent caches.
  Not Agent Host/CLI/cloud storage. Future private formats may change.
- New imports use `.jsonl`; existing `.json` chats keep their extension. Use the
  default `chat.useLogSessionStorage` setting for new imports. JSONL takes precedence
  when both formats exist.
- Shared format is version 1, using immutable, checksummed full snapshots. No garbage
  collector exists. Historical payloads load lazily but verification reads all revisions.
  Oversized/truncated files fail explicitly; the per-file limit is 128 MiB.
- Deletions do not propagate. A later receive can restore a locally deleted chat.
- No project code, live terminals, active requests, worktrees, external asset folders
  or checkpoints are migrated. Old links may refer to the original host or unavailable
  attachments. Restoring text does not guarantee all hidden model context is recreated.
- OneDrive delivery can be incomplete/out of order. Missing ancestry is blocked;
  entirely undelivered revisions are undetectable without a cloud service query.
- Local process checks/locks do not lock another PC or prevent VS Code starting
  during an operation. No forced shutdown, restart or process termination is performed.
- Chats can contain code, paths, tool output and secrets. Shared revisions, local
  backups and exports are not encrypted by this tool. Checksums detect corruption,
  not malicious replacement by somebody with write access. Use trusted private storage.
- Never commit real chats, configs, backups, exports or shared stores to this repository.

Prefer official [remote Agent Host](https://code.visualstudio.com/docs/agents/run/remote-agent-sessions)
for new sessions when it fits your workflow. This unofficial legacy adapter is not a
Microsoft/GitHub product or a real-time sync service.

## Development

Open this repository as its own VS Code folder for its `src` paths and unittest settings.
Node is only needed for frontend tests; it is not a runtime dependency.

```bash
python -m pip install .
python -m unittest discover -s tests -v
node tests/test_workspace_tree.js
python -m pip wheel --no-deps --wheel-dir dist .
```

Tests use temporary native SQLite/chat fixtures. CI targets Linux, Windows and macOS;
Windows-only tests cover NTFS junctions and the PowerShell launcher. A configured
workflow is not evidence of a successful remote run. Before bulk use, pilot an actual
two-PC OneDrive handoff/Copilot continuation. The project is MIT-licensed; bundled
dependencies retain their [third-party licenses](third-party-notices.md).

## Windows Builds

On a clean Windows x64 account with Python 3.12 and Inno Setup 6 installed:

```powershell
python -m pip install .
python -m pip install -r packaging/requirements-windows.txt
python scripts/build_windows.py
```

The build creates a portable ZIP, per-user Setup.exe, desktop screenshot and SHA256SUMS.txt under
`dist/release`. It runs the actual portable and installed executables with isolated
demo data and no Python on PATH, checks packaged resources and API protections,
opens the actual WebView2 window, verifies its rendered state and screenshot, then
uninstalls and verifies a marker in the real default data folder survives. It refuses
to run the installer test on an account with an existing installation or data folder.
Use a disposable build account; the test creates/removes a Start menu entry.

Tag `vX.Y.Z` must match the package and runtime versions. The release workflow reruns
the whole test matrix and Windows build, verifies artifact hashes and publishes only
after success. Releases are marked prerelease. No signing certificate is configured;
SmartScreen warnings may occur. The desktop EXE uses the Windows GUI subsystem;
the separate CLI keeps its console. Closing the desktop window stops the local server,
and closing during an active operation is blocked. See [Windows help](windows-help.md).

The project includes the official [OpenCodeReview delegation skill](../.github/skills/open-code-review-delegate/ORIGIN.md).
It is a development-only review aid, not an application dependency. Delegation mode
uses this assistant for review without configuring a separate LLM. See the
[release review](release-review.md) for coverage and validation boundaries.