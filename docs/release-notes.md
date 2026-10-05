# v0.1.6 Check and Transfer Progress Preview

Windows x64 preview of Copilot Chat Sync, an unofficial tool for legacy
VS Code Copilot chat handoffs through OneDrive or another synced folder.

## Changes

- Adds a progress bar to the check and apply dialogs. Shows the current processing
  stage, file name, actual bytes read/written, verified shared revision count and
  elapsed time. The percentage is for the current file's reading pass, **not**
  the whole operation. Hashing/serialization and writes without a known total
  use an indeterminate bar; there is no estimated countdown.
- Authenticated progress polling remains responsive while a check holds the
  operation lock. Each request has its own progress ID; failed/completed requests
  stop polling and old request results cannot replace a new dialog's progress.
- No new daily controls or runtime dependencies. Existing safety checks remain.
  This release provides visibility, not a full-history scanning speed improvement.
- Retains the v0.1.5 fix for `JSONL record at line 1 exceeds 128 MiB`: initial records use an
  incremental JSON parser, including giant individual strings. The limit is
  consistent across native JSON, records, live state, shared revisions and
  compact imports: 2 GiB. Total native JSONL logs retain an 8 GiB ceiling.
- Canonical serialization, hashing, publication, import and export stream output,
  including string escaping, instead of building giant serialized byte copies.
  Existing shared format and revision hashes remain compatible.
- File hashing, raw backups, restore/rollback and old-link migration use checksummed
  chunk copies, preserving all original bytes without whole-log buffering.
- Malformed records, non-finite numbers, changed sources, conflicts and recovery
  protections remain. Capacity errors are explicit; no chat content is silently skipped.
- Live data still requires RAM. Periodic RSS checks use the lower of 2 GiB or
  starting RSS plus half the available RAM. Allocations can temporarily exceed
  these soft checks, and low-RAM computers can reject files below the size ceiling.
- Conflict preview shows at most the last 100 turns and 4000 characters per
  message/reply, with a visible notice. Synced/exported data is not shortened.
- Project selection uses expandable server/folder hierarchies with sibling directories
  shown alongside each other. One radio selection binds one workspace; parent folders
  do not select every child. SSH aliases and duplicate workspaces stay separate.
- Windows installer smoke now checks same-directory program replacement and
  preservation of local configuration/backups during reinstall and uninstall.
- The simple two-button main page is unchanged; no additional daily controls.

## Downloads

- `CopilotChatSync-0.1.6-windows-x64-Setup.exe`: installer; no Python required.
- `CopilotChatSync-0.1.6-windows-x64-portable.zip`: extract the entire folder and
  open `CopilotChatSync.exe`. Keep all files together.
- `CopilotChatSync-0.1.6-desktop.png`: actual Windows CI screenshot with synthetic data.
- `SHA256SUMS.txt`: download integrity checksums.

**Upgrade:** close the app, then run the new Setup into the same directory.
No prior uninstall is needed. Program files are replaced; chat history, shared
stores, local configuration and backups are retained. Extract portable updates
into a new folder to avoid leftover old runtime files.

## Validation and Limits

Progress checks cover real byte counts, concurrent polling while a preview is
blocked, authentication, request isolation, failure cleanup, determinate and
indeterminate UI rendering, and polling timer cleanup. A physical 135,266,484-byte
first record passed the complete handoff with reporting enabled at 285.6 MiB
sampled peak RSS. The full existing platform/packaging gates remain in place.

Prior v0.1.5 large-file validation:
Physical synthetic FIRST records of 135,266,484 bytes (retained giant chat) and
537,919,668 bytes (later reduced by a valid mutation) passed local Send/Receive,
shared reload, re-send, plain JSON export and complete raw backup/restore.
Sampled peak RSS was 286.0 MiB and 1056.5 MiB respectively. The cumulative
537,947,484-byte log regression also passed at 32.3 MiB RSS.
A retained 537,919,668-byte first record also passed the entire chain, including
giant shared revisions and received/exported chats, at 1054.0 MiB peak RSS.
CI repeats all four checks, and Windows packaging verifies a >129 MiB first record
using the actual executable. Publication is gated on the full test matrix,
native rendering and same-directory installation checks.
These checks do not validate every real VS Code format or prove cloud delivery.

- Only legacy extension-host chats are supported, not Agent Host/CLI sessions.
- Binaries remain unsigned and may trigger SmartScreen; do not disable Windows security.
- Back up chats and code first. Keep VS Code closed throughout; large logs can take minutes.
- One shared store is one chat pool. Use separate configurations/stores for unrelated projects.
- SSH aliases are not automatically paired. Code, terminals and edit checkpoints are not synced.
- Wait for OneDrive on both computers. Local success does not prove cloud delivery.
- Real two-PC OneDrive delivery and native Copilot continuation still require a pilot.

See the [quick start](https://github.com/ziao-liu/copilot_chat_sync#readme) and
[advanced guide](https://github.com/ziao-liu/copilot_chat_sync/blob/main/docs/advanced.md).
Project license: MIT.
