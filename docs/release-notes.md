# v0.1.8 Overall Progress and Faster Startup Preview

Windows x64 preview of Copilot Chat Sync, an unofficial tool for legacy
VS Code Copilot chat handoffs through OneDrive or another synced folder.

## Changes

- Show an overall, left-to-right progress bar during initial loading and refresh,
  replacing the static "reading local records" message. Startup verifies the
  shared store once instead of separately scanning it for status, counts and
  conflicts. Unchanged startups reuse verified metadata without JSON reparsing;
  each cache reuse still verifies the full raw file checksum.
- Keep one percentage through preflight, execution and final refresh. Progress
  advances on completed work steps, with revision/chat subdivisions; changing
  files no longer resets it. Phase shares are not elapsed-time or byte proportions.
  Current stage, file bytes and elapsed time remain details; no guessed countdown.
- Display 100% only after the final successful response. Failure preserves
  partial progress, reports the error and stops polling. Stale request IDs cannot
  change the active progress; one-click handoffs retain total elapsed time.
- Existing configurations, shared format, backups, recovery and low-memory
  behavior remain compatible. No extra daily controls or dependencies.

## Retained v0.1.7 Optimizations

- Process native chats individually; shared publication no longer retains every
  new transcript in the revision graph. Normalize owned input without unnecessary
  deep copies while retaining the public normalization function's copy semantics.
- Plan received payloads as checksummed temporary disk files, not a list of large
  in-memory documents. Original-file checks, full backup, SQLite compare-and-swap
  and rollback remain. Corrupted staging files cannot replace the original chat.
- Cache only validated hashes and small index metadata locally. A cache hit
  requires a **fresh full-file SHA256**, never just size or timestamps. Unchanged
  receive skips transcript replay/JSON parsing; one changed chat only requires
  expensive work for changed content. Missing parents and conflicts still block.
- Reuse content hashes within each chat operation, release historical payloads
  before reading the next revision, and build indexes from compact metadata.
- Memory errors show actual process RSS, protection threshold and available system
  RAM. The 2 GiB process protection remains; this is not a cure for a single
  decoded conversation that itself exceeds the resource budget.
- No new buttons, dependencies or shared-store format. Existing stores remain
  compatible. Keep the local cache private; it is disposable, unlike sync state.

## Retained Features

- Check and apply dialogs retain actual file-byte counters, processing stages,
  verified revision counts and elapsed time beneath the overall bar. The progress
  concerns local work only; it does not confirm OneDrive cloud delivery.
- Authenticated progress polling remains responsive while a check holds the
  operation lock. Each request has its own progress ID; failed/completed requests
  stop polling and old request results cannot replace a new dialog's progress.
- No new daily controls or runtime dependencies. Existing safety checks remain.
  Full raw-byte integrity scans remain; the optimization skips repeated decoding
  and canonicalization, not integrity protection or OneDrive delivery checks.
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

- `CopilotChatSync-0.1.8-windows-x64-Setup.exe`: installer; no Python required.
- `CopilotChatSync-0.1.8-windows-x64-portable.zip`: extract the entire folder and
  open `CopilotChatSync.exe`. Keep all files together.
- `CopilotChatSync-0.1.8-desktop.png`: actual Windows CI screenshot with synthetic data.
- `SHA256SUMS.txt`: download integrity checksums.

**Upgrade:** close the app, then run the new Setup into the same directory.
No prior uninstall is needed. Program files are replaced; chat history, shared
stores, local configuration and backups are retained. Extract portable updates
into a new folder to avoid leftover old runtime files.

## Validation and Limits

v0.1.8 local validation: 114 Python tests (three Windows-only skips), frontend
behavior tests and syntax checks pass. Regressions assert one store scan per
startup, cache reuse without reparsing, nested overall-step progress, file
transitions, authenticated polling, complete preflight/apply/refresh continuity,
failure handling and 100% only on the final response.

Retained performance baseline from v0.1.7, not a new v0.1.8 timing measurement:
same local 4 x 65 MiB synthetic workload, v0.1.6 vs v0.1.7:

| Operation | Before | After | Peak RSS before / after |
| --- | --- | --- | --- |
| First receive/apply | 10.30 s | 8.98 s | 352.9 / 161.7 MiB |
| Unchanged receive | 11.39 s | 0.47 s | 613.9 / 30.7 MiB |
| Send one changed chat | 9.22 s | 2.54 s | 353.7 / 161.7 MiB |
| Receive one changed chat | 14.01 s | 3.00 s | 615.6 / 161.7 MiB |

Unchanged receive parses zero transcript payloads instead of 12; receiving one
changed chat parses two instead of 13. First sends are not faster in this test
(8.19 s before, 8.61 s after); cold validation and serialization still cost time.
Four >129 MiB chats also passed at <290 MiB peak RSS, with unchanged receive
at 0.92 s / 30.6 MiB. These are local synthetic measurements, not guarantees.
CI gates zero unchanged parsing, changed-chat parsing counts and multi-chat RSS.
Tests also preserve checksum failures with unchanged size/mtime, native dirty
destination protection, cache integrity errors, staging corruption rollback
and exact raw backups/restoration. A retained >513 MiB first record passed the
full handoff at 1056.5 MiB RSS; the cumulative >513 MiB log passed at 31.9 MiB.

Progress checks cover real byte counts, concurrent polling while startup or a
preview is blocked, authentication, request isolation, failure cleanup,
monotonic overall UI rendering and polling timer cleanup. Prior physical 135,266,484-byte
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
