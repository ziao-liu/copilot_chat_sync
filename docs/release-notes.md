# Windows Preview

First Windows x64 preview of Copilot Chat Sync, an unofficial tool for legacy
VS Code Copilot chat handoffs through OneDrive or another synced folder.

## Downloads

- `CopilotChatSync-0.1.0-windows-x64-Setup.exe`: per-user installer and Start menu shortcut. No administrator privileges or Python installation required.
- `CopilotChatSync-0.1.0-windows-x64-portable.zip`: extract the entire folder, then open `CopilotChatSync.exe`. Keep `_internal` beside it.
- `SHA256SUMS.txt`: download integrity checksums.

Double-clicking opens the local browser panel. Keep its console window running;
close it or press Ctrl+C to stop. Close the app before upgrading or uninstalling.
Uninstall removes the program, not your chat history, shared store or local backups.

## Important Limits

- Unsigned binaries may trigger Windows SmartScreen. No signing certificate is provided.
- Only legacy extension-host chats are supported, not Agent Host/CLI sessions.
- Back up chats and code first. Apply still requires closing VS Code and explicit confirmation.
- One shared store is one chat pool, not automatic per-project matching.
- Wait for OneDrive on both computers. The app does not verify cloud delivery.
- Real two-PC OneDrive delivery and native Copilot continuation still need a pilot; automated fixtures and installer smoke tests are not that pilot.

See the [quick start](https://github.com/ziao-liu/copilot_chat_sync#readme) and
[advanced guide](https://github.com/ziao-liu/copilot_chat_sync/blob/main/docs/advanced.md)
for setup, old-link migration and recovery. Project license: MIT.