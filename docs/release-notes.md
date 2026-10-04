# v0.1.2 Simplified Desktop Preview

Windows x64 preview of Copilot Chat Sync, an unofficial tool for legacy
VS Code Copilot chat handoffs through OneDrive or another synced folder.

## Changes

- Compact Chinese-language, single-page interface: current project, shared folder,
  status, Send and Receive. No sidebar, workspace tree or decorative statistics.
- Ordinary Send/Receive automatically preview and apply with one click. Existing
  single-use tickets, expiry, changed-file detection, closed-editor checks and locks remain.
- Setup selects one workspace per configuration. Existing multi-workspace bindings
  are not silently rewritten; select one before using the simplified transfers.
  The CLI still supports multi-workspace groups.
- Restore and diagnostics move into Settings. Conflicts and old-link migration
  appear only when needed; index repair is offered for relevant diagnostic issues.
- Conflicts, setup, binding changes, migration, restore and checkpoint quarantine
  still require confirmation. Checkpoint quarantine requires explicit acknowledgement.
- Common errors have actionable Chinese messages with technical details available.
  Chat counts are totals, not pending transfers; cloud delivery remains unknown.
- Updated desktop-rendering smoke checks and isolated demo for the two-button layout.
  No native chat format or shared-pool format changes.

## Downloads

- `CopilotChatSync-0.1.2-windows-x64-Setup.exe`: per-user installer and Start menu shortcut.
  No Python installation required; offers the Microsoft-signed WebView2 Runtime installer if needed.
- `CopilotChatSync-0.1.2-windows-x64-portable.zip`: extract the entire folder, then open
  `CopilotChatSync.exe`. Keep all files together; install WebView2 Runtime if missing.
- `CopilotChatSync-0.1.2-desktop.png`: desktop-rendering screenshot from Windows CI using synthetic data.
- `SHA256SUMS.txt`: download integrity checksums.

Close the app before upgrading or uninstalling. Uninstall removes the program,
not chat history, shared stores or local backups. The bundled console CLI retains
its original commands.

## Important Limits

- Binaries remain unsigned and may trigger SmartScreen. Do not disable Windows security to install.
- Only legacy extension-host chats are supported, not Agent Host/CLI sessions.
- Back up chats and code first. All writes still require closing VS Code.
- One shared store is one chat pool. Selecting another workspace does not create
  project isolation; use separate configurations and stores for unrelated projects.
- SSH aliases are not automatically paired or rewritten.
- Wait for OneDrive on both computers. Sending only writes the local sync folder,
  not proof of upload or delivery to the other computer.
- Code, terminals, live requests and editing checkpoints are not synchronized.
- Real two-PC OneDrive delivery and native Copilot continuation still need a pilot;
  automated fixtures and installer smoke tests are not that pilot.

See the [quick start](https://github.com/ziao-liu/copilot_chat_sync#readme) and
[advanced guide](https://github.com/ziao-liu/copilot_chat_sync/blob/main/docs/advanced.md).
Project license: MIT.
