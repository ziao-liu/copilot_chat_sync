# v0.1.4 Large-Log and Project-Picker Preview

Windows x64 preview of Copilot Chat Sync, an unofficial tool for legacy
VS Code Copilot chat handoffs through OneDrive or another synced folder.

## Changes

- Native JSONL logs are replayed incrementally instead of reading the whole file.
  Logs up to 8 GiB are supported; individual records, replayed live state and
  compact/shared snapshots retain a 128 MiB safety limit.
- Large append-only logs no longer fail merely because total file size exceeds
  128 MiB. Sending publishes the reconstructed chat without rewriting the original log.
- File hashing, raw backups, restore/rollback and old-link migration use checksummed
  chunk copies, preserving all original bytes without whole-log buffering.
- Oversized records/live snapshots fail explicitly before an unreadable revision
  is published. Malformed logs, changed sources, conflicts and recovery protections remain.
- Project selection uses expandable server/folder hierarchies with sibling directories
  shown alongside each other. One radio selection binds one workspace; parent folders
  do not select every child. SSH aliases and duplicate workspaces stay separate.
- Windows installer smoke now checks same-directory program replacement and
  preservation of local configuration/backups during reinstall and uninstall.
- The simple two-button main page is unchanged; no additional daily controls.

## Downloads

- `CopilotChatSync-0.1.4-windows-x64-Setup.exe`: installer; no Python required.
- `CopilotChatSync-0.1.4-windows-x64-portable.zip`: extract the entire folder and
  open `CopilotChatSync.exe`. Keep all files together.
- `CopilotChatSync-0.1.4-desktop.png`: actual Windows CI screenshot with synthetic data.
- `SHA256SUMS.txt`: download integrity checksums.

**Upgrade:** close the app, then run the new Setup into the same directory.
No prior uninstall is needed. Program files are replaced; chat history, shared
stores, local configuration and backups are retained. Extract portable updates
into a new folder to avoid leftover old runtime files.

## Validation and Limits

Real synthetic logs of 537,947,484 bytes and 2,147,594,534 bytes passed local
Send/Receive, complete raw backup/restore and POSIX migration with sampled peak RSS
of 33.7 MiB. CI repeats the above-513-MiB check and gates publication on the full
test matrix and actual Windows packaging, rendering and installation checks.
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
