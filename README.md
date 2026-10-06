# Copilot Chat Sync

Move **legacy VS Code Copilot chats** between computers through OneDrive or another
synced folder. A Windows desktop app handles setup, transfers, conflicts and backups.

**Run it on each desktop computer, not your SSH servers.**

> Early preview, unofficial. Real Windows/OneDrive handoff
> and native Copilot continuation still need a pilot. Not for Agent Host or CLI sessions.

Version 0.1.8 adds overall progress from startup through handoff completion and
removes redundant startup scans, retaining the lower-memory checks, compact
interface and large-snapshot support.

## Start

**Windows 10/11 x64: no Python installation required.**

1. Open [Releases](https://github.com/ziao-liu/copilot_chat_sync/releases/tag/v0.1.8)
  and download `CopilotChatSync-0.1.8-windows-x64-Setup.exe`.
2. Install for your user, then open **Copilot Chat Sync** from the Start menu.
3. A standalone app window opens. No browser tab or console is needed; closing the app stops its local service.

Prefer no installer? Download the portable ZIP, extract the **whole folder**, and
open `CopilotChatSync.exe`. Keep all extracted files together. Microsoft WebView2
Runtime is required; Setup offers to install the Microsoft-signed runtime if missing.
Our binaries are still unsigned and may show a SmartScreen warning. See
[Windows trust and old links](docs/windows-help.md); SHA256 is not a signature.

<details>
<summary>Source install (Python 3.10+, Linux/macOS or development)</summary>

Use a local external terminal on each computer:

```powershell
git clone https://github.com/ziao-liu/copilot_chat_sync.git
cd copilot_chat_sync
python -m pip install .
python -m copilot_chat_sync panel
```

Your browser opens automatically. Keep this terminal running; `Ctrl+C` stops the panel.
For later launches, only the last command is needed.

</details>

## Set Up Once

1. Check the prefilled shared folder. The local VS Code data location is detected
   automatically; expand the data-location section only if detection is wrong.
2. Click **选择项目**, expand the server/folder hierarchy and select one project.
   Servers and sibling directories are listed alongside each other; only the selected
   project is bound, not every child of a folder. Missing project? Open it once in desktop
   VS Code using the intended SSH alias, then click **重新扫描**.
3. Close VS Code, click **完成设置**, review the project/shared folder and confirm.

Repeat on the other computer using the **same cloud folder** and its corresponding local workspace.
The local data folder on standard Windows VS Code is `%APPDATA%\Code\User\workspaceStorage`.

> **One shared folder = one chat pool.** The simplified UI binds one workspace per
> configuration. Existing multi-workspace configurations are not silently rewritten;
> select one before transferring. Changing the SSH workspace does not create a new pool.
> Use [separate groups](docs/advanced.md#separate-groups) for unrelated projects.

## Switch Computers

1. **Computer A:** close VS Code, click **发送本机记录**.
2. Wait for OneDrive to finish uploading and downloading on **both computers**.
3. **Computer B:** keep VS Code closed, send any existing local changes first,
   resolve conflicts if needed, then click **接收其他电脑记录**. Reopen VS Code afterward.

Ordinary transfers automatically preview and apply through the existing safety
checks, without additional confirmation dialogs. Conflicts and editing-checkpoint
quarantine still require explicit choices. The main page shows total chat counts,
not pending transfer counts, and the most recent operation in this app session.
Send/Receive works on the local sync folder; success does not confirm cloud delivery.
v0.1.8 uses a left-to-right **overall progress bar**, including
initial loading and refresh. A handoff keeps one percentage through preflight,
execution and final refresh; changing files does not reset it. Progress is based
on completed work steps, subdivided by verified revisions and processed chats,
not elapsed-time guesses or a prediction of remaining time. File bytes, current
stage and elapsed time remain in the details. Only a successful final response
reaches 100%; failed requests retain their partial progress.
Startup verifies the shared store once, reusing that graph for counts/conflicts,
instead of scanning it separately for status, totals and conflict summaries.
Progress is local, not OneDrive upload status.
Verified local metadata avoids parsing unchanged history and native logs again.
Every reuse still checks the complete file checksum, not just size/timestamps.
Chats are processed individually and imports staged on disk; the first cold check
and genuinely changed large chats can still take minutes.
Conflicting versions are kept for review, not silently overwritten or combined.
Backups are automatic; restore and diagnostics live under **设置**. Old-link migration
appears only when the selected project needs it. Index repair is offered only when
diagnostics identify an index/cache/schema issue.
Technical storage warnings can be expanded below the main controls. Long shared-folder
paths are shortened on the main page; hover or open Settings to see the full path.

## Before Your First Sync

- Back up your chats and project code. Test with one non-editing conversation first.
- Stop old sync/link scripts on **every computer**. For old directory links, use
  **检查并迁移旧配置**; use a new tool folder, not the old raw chat folder.
- Editing-snapshot quarantine needs explicit confirmation and removes access to old
  undo/checkpoints. This tool does not sync project code or live editing state.
- Keep the shared folder private. Chats/backups are not encrypted by this tool;
  do not share the panel's private URL.

## Large Chat Logs

Native `.jsonl` logs are replayed incrementally (up to 8 GiB), including initial
snapshots larger than 128 MiB. JSON records, the replayed state, native JSON,
compact imports and shared revisions now have a consistent 2 GiB ceiling.
Sending does not rewrite or truncate the source log; it publishes the resulting
conversation snapshot. Raw backups, restoration and old-link migration use
checksummed chunk copies, retaining the complete original log.

The live chat still needs RAM; this is not a disk-backed replay engine. Memory
checks stop at 2 GiB process RSS or half the initially available RAM added to
current RSS, whichever is lower. Token/object allocation can temporarily exceed
these checks, so file-size support is not a guarantee on every computer.
Capacity failures are explicit and never truncate chats. Large-log replay may
take minutes; keep VS Code closed throughout. Conflict previews show at most
100 turns and 4000 characters per message/reply, without shortening synced data.

v0.1.7 no longer keeps all workspace chats/import payloads in memory together.
On a local 4 x 65 MiB synthetic workload, unchanged receive improved from
11.39 s / 613.9 MiB peak RSS to 0.47 s / 30.7 MiB; receiving one changed chat
improved from 14.01 s / 615.6 MiB to 3.00 s / 161.7 MiB. First sends were not
faster in this test. Results are illustrative, not a guarantee on your computer.
The disposable `config.cache.sqlite` beside the local configuration stores only
verified hashes/index metadata, not transcripts. Keep it local and private.
Delete only that cache if a cache integrity error explicitly requests it; never
delete the sync state, shared revisions or backups to reset performance.

## More

From the portable folder, preview without touching your chats:

```powershell
.\CopilotChatSync.exe --demo
```

To update the installer version, close the app and install the new Setup into the
same directory; it replaces program files and retains chats, the shared store,
local configuration and backups. There is no need to uninstall first.
For a portable update, prefer extracting into a new folder to avoid leftover old
runtime files. Uninstalling keeps your chats, shared store and local configuration/backups.

[Migration, recovery, CLI and limitations](docs/advanced.md).
The demo uses synthetic data and is read-only. [MIT license](LICENSE).