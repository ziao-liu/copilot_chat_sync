# Copilot Chat Sync

An offline-first tool with a CLI and local browser panel for handing **legacy
VS Code Copilot chat history** between computers through OneDrive or another
synchronized folder.

**Status: 0.1.0, pre-release.** This is an unofficial storage adapter, not a
Microsoft/GitHub product. Local automated fixtures are tested; real Windows
OneDrive synchronization and native Copilot continuation still need a pilot on
your installed VS Code versions. CI includes Windows, macOS and Linux, but a
configured CI workflow is not evidence that those jobs have run.

## Why not share a live chatSessions directory?

The original workaround linked several native `chatSessions` directories to one
OneDrive folder and periodically repaired their SQLite indexes. That allowed
multiple VS Code windows to overwrite the same mutable session file. A stale
editing snapshot could also affect project files when an old conversation opened.

This tool keeps OneDrive as the transport but replaces live junction sharing with
explicit, closed-editor **push/pull handoffs**:

```text
PC A native chats -- push --> immutable shared revisions <-- push -- PC B native chats
                 <-- pull --                            -- pull -->

Local only: config, sync ancestry, backups, VS Code indexes, editing checkpoints
Shared:    normalized conversation payloads and revision ancestry
```

- No forced shutdown, process termination, automatic restart or fixed-delay sync.
- Every mutating command previews by default. Add `--apply` to write.
- Apply requires VS Code to be closed. There is no bypass flag.
- Immutable, checksummed revisions retain both sides of an offline conflict.
- Pull refuses to overwrite unpublished local conversation changes.
- Native imports update only the three known chat index/cache keys.
- File backups, SQLite snapshots and a recovery journal precede local changes.
- Unknown formats, corrupt logs, missing parent revisions and conflict-copy names
  fail explicitly rather than becoming empty or truncated conversations.
- The tool does not follow paths embedded in conversations, run their commands,
  change project code, or execute downloaded repair scripts.

This is **not real-time sync, automatic deletion propagation, or a full migration
to Agent Host**. For new sessions, prefer the official
[remote Agent Host](https://code.visualstudio.com/docs/agents/run/remote-agent-sessions)
when that fits your workflow.

## Install

Requirements: Python 3.10+, `pip`, an installed OneDrive client (or equivalent
transport), and native legacy chats in a local VS Code installation.

Download/clone this repository, open an **external terminal** in its root, and run:

```powershell
python -c "import sys; print(sys.executable); print(sys.version)"
python -m pip install .
python -m copilot_chat_sync --help
```

The installed `copilot-chat-sync` command is equivalent to
`python -m copilot_chat_sync`. The only runtime dependency is `psutil`, used for
process safety checks. No account, token, telemetry or network API is used by this
tool; your OneDrive client performs the actual cloud upload/download.

On Windows, an activated Anaconda/Miniconda prompt is suitable. A path such as
`...\WindowsApps\python.exe` may be a Store placeholder, not an interpreter.
Do not trust a successful exit code without actual Python output.

An ASCII-only PowerShell 5.1+ launcher is included for source checkouts:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\chat-sync.ps1 scan
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\chat-sync.ps1 -PythonExecutable "C:\Users\alice\miniconda3\python.exe" doctor
```

It probes the interpreter by executing Python code, uses its resolved executable,
and propagates CLI failures. It does not install Python or dependencies for you.

## Local browser panel

After installing the package, launch this from an **external terminal on the
computer running VS Code**, not from the SSH server's terminal:

```powershell
python -m copilot_chat_sync panel
```

The command opens a browser and prints a private URL. The panel uses the same
local configuration and synchronization engine as the CLI. It remains available
after you close VS Code, which is still required before applying any changes.
Browsing, diagnostics and previews do not require closing the editor.

The four views are:

- **Synchronize**: filter discovered workspaces, select the handoff scope,
  preview push/pull, repair indexes or migrate old junctions.
- **Conflicts**: read competing conversation versions without opening a native
  Copilot session, download their JSON, and preview a version choice.
- **Backups**: inspect local recovery journals and preview restoration.
- **Settings**: view this computer's configuration and device ID; **Manage scope**
  adds/removes workspace bindings without deleting chat files. Revision writer
  IDs are historical authors, not a list of online devices or access permissions.

An unconfigured installation opens a setup form for the shared store and local
VS Code storage. A panel instance controls one config file. For another group:

```powershell
python -m copilot_chat_sync --config "$env:LOCALAPPDATA\CopilotChatSync\work.json" panel
```

Every change requires a successful preview and a separate **Confirm & apply**.
Preview tickets expire after two minutes and are single-use. Changes to input
file metadata invalidate the preview. Existing process checks, locks, conflict
checks and recovery rules still run on apply. Quarantining editing snapshots
additionally requires acknowledging loss of their old undo/checkpoints.

The server only binds `127.0.0.1`, prefers port 8765, and selects another free port
if it is occupied. There is no public bind option. API calls require a random
per-launch bearer token and matching Host/Origin; cross-origin access is rejected.
The token is passed in the URL fragment, removed from the address bar, and retained
in that tab's session storage. Do not share the private URL or forward this port
to an untrusted network. Restarting the panel invalidates previous tokens.

The UI bundles its font and Lucide icons with their third-party licenses. There
are no CDN requests, telemetry, or frontend build/runtime dependencies. Recent
operation activity is in-memory for that panel process; recovery journals persist
as before. Cloud delivery is explicitly unverified, not inferred from local counts.

For a read-only demonstration using disposable synthetic data:

```powershell
python -m copilot_chat_sync panel --demo
```

`--demo` refuses all apply requests at the server, not just in the interface.
Use `--no-browser` to print the URL only, or `--port 0` for an OS-assigned port.
Keep the terminal running while using the panel. Press Ctrl+C to stop it.

## First setup on each computer

First open every desired folder once using the intended SSH alias in VS Code.
Then finish/review your work, independently back up current code, and close all
VS Code windows. Do not restart VS Code until the operation finishes.

1. Create a new shared **tool** folder. Do not reuse the old flat junction target.

   ```powershell
   python -m copilot_chat_sync init --store "D:\OneDrive\CopilotChatSync"
   python -m copilot_chat_sync init --store "D:\OneDrive\CopilotChatSync" --apply
   ```

   Omitting `--store` uses the `OneDrive`, `OneDriveConsumer`, or
   `OneDriveCommercial` environment variable. No hardcoded drive is assumed.
   Use `--insiders` or `--storage-root` with `init` for another installation,
   portable mode, or custom `--user-data-dir`.

2. Find actual workspace IDs and URIs. IDs are never guessed from hashes.

   ```powershell
   python -m copilot_chat_sync scan
   ```

3. Bind the folders that should share this group of conversations. Repeat for
   direct/proxy aliases and additional server folders:

   ```powershell
   python -m copilot_chat_sync bind --server gpu-server --path /home/alice/project --apply
   python -m copilot_chat_sync bind --server gpu-server-proxy --path /home/alice/project --apply
   python -m copilot_chat_sync bind --server npu-server --path /home/alice/PROJECT --apply
   ```

   Alternatively, use `bind --workspace ID_FROM_SCAN` or `bind --uri FULL_URI`.
   Remote paths are case-sensitive. Duplicate URI matches require an explicit
   ID, including any `-1` suffix. Binding metadata is revalidated before use.

4. Run `doctor`. Mark the shared store **Always keep on this device** in OneDrive.
   On the second computer, wait for OneDrive before using the existing store.

   ```powershell
   python -m copilot_chat_sync doctor
   ```

Configuration is local to each computer:

| Platform    | Default config                                                                                 |
| ----------- | ---------------------------------------------------------------------------------------------- |
| Windows     | `%LOCALAPPDATA%\CopilotChatSync\config.json`                                                   |
| Linux/macOS | `$XDG_CONFIG_HOME/copilot-chat-sync/config.json`, or `~/.config/copilot-chat-sync/config.json` |

`--config PATH` is a **global option before the subcommand**. Use separate config
files and separate shared store folders for unrelated groups. Do not sync local
config/state files: each computer needs its own device ID and workspace bindings.
Do not place the config directory inside the shared store or native storage.

## Migrate an existing OneDrive junction setup

Disable your previous setup/link/sync scripts on **all** computers first. This
tool never runs alongside or replaces them automatically.

After `init` and `bind`, while VS Code is closed:

```powershell
python -m copilot_chat_sync migrate
python -m copilot_chat_sync migrate --apply
python -m copilot_chat_sync push
python -m copilot_chat_sync push --apply
python -m copilot_chat_sync pull
```

Migration reads the existing linked sessions, validates them, backs them up, and
replaces the junction with an independent local directory. The original shared
folder remains untouched. The old link is retained beside the new directory as
`chatSessions.link-before-TIMESTAMP-ID`. Do not recursively delete that retained
link with an unverified script. You can leave it in place.

Repeat on every computer. Sources that share the same session ID but have
different content produce a conflict, not a last-writer-wins overwrite. Resolve
it before pulling.

If migration is interrupted, `backups` lists its `prepared` journal. Run
`restore BACKUP_ID --apply` before reopening VS Code. Migration recovery completes
the backed-up **independent copies**; it never reactivates live junctions.
Staging directories may remain after recovery and contain redundant safe copies.

## Daily handoff

On the computer where you just worked, close VS Code and publish:

```powershell
python -m copilot_chat_sync push
python -m copilot_chat_sync push --apply
```

Wait for OneDrive to report **Up to date** on the sending computer and finish
downloading on the receiving computer. A successful push means a local revision
was written, **not** that the cloud has received it. The tool cannot detect an
entire remote revision that OneDrive has not delivered yet.

On the receiving computer, keep VS Code closed. Preserve any local conversations
by pushing first, then import:

```powershell
python -m copilot_chat_sync push --apply
python -m copilot_chat_sync pull
python -m copilot_chat_sync pull --apply
```

Reopen the correct folder and its Chat history. Use `--workspace ID` on push,
pull, repair, or migrate to affect only one bound workspace. Otherwise all bound
workspaces participate. On one computer, changing SSH aliases is also a handoff.

Do not have multiple devices editing the same session concurrently. Divergence
will be preserved, but the tool will not splice two conversations together.

## Editing checkpoints and code safety

Saving a file, accepting a Copilot edit, and committing to Git are different
operations. A saved but unaccepted edit is not normally undone just by closing
the window. However, [VS Code issue #313703](https://github.com/microsoft/vscode/issues/313703)
describes old pending snapshots restoring stale editor buffers; Save/Auto Save
can then overwrite newer project files.

This tool deliberately:

- Never synchronizes `chatEditingSessions`, working-tree diffs, draft permissions
  or queued requests.
- Preserves the session ID and conversational request/response payloads, while
  removing session-level editing/execution state.
- Refuses pull/repair when an affected local session has an editing-state folder.
  The check is conservative and also catches accepted historical snapshots.

After verifying/backing up current code **without reopening a suspect old chat**,
you can explicitly quarantine those snapshots:

```powershell
python -m copilot_chat_sync pull --detach-edit-state
python -m copilot_chat_sync pull --detach-edit-state --apply
```

Snapshots move locally to
`workspaceStorage/ID/.chat-sync-quarantine/BACKUP_ID/SESSION_ID`.
Conversation text and project files remain unchanged by quarantine, but old chat
undo/redo and checkpoints are no longer available. A manual backup restore does
not automatically reactivate these snapshots. `repair --detach-edit-state`
provides the same isolation for all native chats in selected workspaces.

This does **not** fix VS Code or protect unrelated sessions that still have stale
snapshots. If opening a chat unexpectedly dirties buffers, stop before Save All
or Keep All and compare against disk/Git. Keep independent code backups.

## Conflicts and recovery

```powershell
python -m copilot_chat_sync conflicts
python -m copilot_chat_sync export-revision SESSION_ID --revision FULL_REVISION_ID --output "D:\chat-exports\candidate.json" --apply
python -m copilot_chat_sync resolve SESSION_ID --revision FULL_HEAD_REVISION_ID
python -m copilot_chat_sync resolve SESSION_ID --revision FULL_HEAD_REVISION_ID --apply
python -m copilot_chat_sync pull --apply
```

`resolve` creates a new revision referencing every known competing head, using
the selected payload. Unchosen histories stay exportable. It cannot resolve an
undelivered branch; wait for OneDrive on every computer first.

Local restoration:

```powershell
python -m copilot_chat_sync backups
python -m copilot_chat_sync restore BACKUP_ID
python -m copilot_chat_sync restore BACKUP_ID --apply
```

Restore checks file hashes and the three chat keys. Newer edits cause refusal.
Unrelated SQLite keys are preserved, even if they changed since the backup.
Restoration clears local sync ancestry conservatively; push may then report a
conflict instead of silently downgrading shared history. Full SQLite backup
files are for expert/manual recovery only, not automatic wholesale replacement.

## Command reference

| Command               | Purpose                                                           |
| --------------------- | ----------------------------------------------------------------- |
| `panel`               | Open the local browser interface (`--demo` is read-only)          |
| `scan`                | List actual IDs, URIs, file counts, and links                     |
| `init`                | Create local config and initialize/reuse a versioned shared store |
| `bind`                | Add an existing local workspace to a shared group                 |
| `status`              | Report local/native/shared state and safety warnings              |
| `doctor`              | Also parse native chats and return nonzero for detected issues    |
| `push`                | Publish changed conversations as immutable revisions              |
| `pull`                | Import converged conversations and rebuild their indexes          |
| `repair`              | Rebuild chat indexes from local native files                      |
| `migrate`             | Safely detach a previous chatSessions junction                    |
| `conflicts`           | List competing heads and their originating device IDs             |
| `export-revision`     | Export any archived revision without opening a native chat        |
| `resolve`             | Explicitly choose a head without destroying other revisions       |
| `backups` / `restore` | Inspect and recover local transactions                            |

All results use JSON; errors go to stderr. Exit codes: `0` success/preview,
`2` validation/safety/I/O failure, `3` divergent shared histories, `130` interrupted
outside a journaled operation. No `[DONE]` message hides a failed subprocess.

## Compatibility and limitations

- Targets **legacy extension-host**, UUID-named native `.json` and `.jsonl` conversations,
  serialized versions 1-3; JSONL operations 0/1/2/3; chat index version 1 and
  list-shaped agent caches. Not Agent Host/CLI/cloud session storage.
- New imports use `.jsonl`; existing flat `.json` sessions keep their extension.
  If you disabled `chat.useLogSessionStorage`, new imports require the default
  log storage mode. When both native formats exist, JSONL takes precedence,
  matching the default VS Code reader.
- Shared store format is version 1. Complete snapshot payloads are immutable;
  updates to unchanged sessions are deduplicated. Historical payloads are loaded
  lazily, but store verification still reads every revision. There is no garbage
  collector yet; long-lived groups can consume substantial disk space.
- Default per-file limit: 128 MiB. Oversized and truncated files fail explicitly.
- **Deletion does not propagate.** Deleting a native chat only removes its local
  copy. A later pull can restore it. No distributed deletion or automatic pruning
  is implemented in 0.1.0.
- No automatic path rewriting across servers. Historical file/terminal links
  may still refer to the old host. Inspect the current workspace before editing.
- No live terminal, active request, checkpoint, worktree, image asset directory,
  or extension-private metadata migration. Embedded payloads remain; external
  attachment links may be unavailable on the new computer.
- No promise that every future VS Code release will accept this private format,
  or that a restored conversation recreates all hidden model context. Pilot one
  non-editing conversation and test restart/continuation before bulk use.
- Cloud delivery order is arbitrary. Missing ancestry is blocked. A branch not
  yet delivered is fundamentally undetectable without querying the cloud service.
- Local process checks and locks do not prevent somebody from launching VS Code
  midway through an operation, and do not lock other computers.

## Privacy

Chat payloads may contain source code, user paths, tool output, secrets and
attachments. Shared revisions, local backups and exports are **not encrypted by
this tool**. OneDrive's account/security controls are separate. Checksums detect
corruption, not malicious changes by somebody with write access to the store.
Use a private trusted folder and follow your organization's data policy.

Do not commit config, native storage, backups, exports, or the shared store to a
public Git repository. No personal conversation is included in this repository.

## Development and release checks

Open this repository as its own VS Code folder for the included `src` import
paths and unittest configuration. A parent workspace may use different Pylance
settings; do not modify unrelated projects to resolve nested-package imports.

```bash
python -m pip install .
python -m unittest discover -s tests -v
python -m pip wheel --no-deps --wheel-dir dist .
```

The tests create temporary native SQLite/session fixtures. They cover parser
compatibility, multiple workspace aliases, no-write preview, offline conflicts,
unknown schemas, snapshot quarantine, failure rollback, restore conflicts, and
junction migration. Windows-only tests exercise real NTFS junctions and the
PowerShell launcher. None of the tests intentionally open real conversation data.

Before publishing a release, run the CI matrix, test a real two-PC OneDrive
handoff and native Copilot restart/continuation, and select a distribution license.
No license has been selected and no remote repository or release is created by
the tool itself.