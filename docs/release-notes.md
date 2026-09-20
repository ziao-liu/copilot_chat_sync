# v0.1.1 Desktop Preview

Windows x64 desktop preview of Copilot Chat Sync, an unofficial tool for legacy
VS Code Copilot chat handoffs through OneDrive or another synced folder.

## Changes

- Fixed startup failure when an old `chatSessions` mount point raises WinError 448.
	Routine scanning no longer opens linked targets; unreadable folders become individual warnings.
- Transfers of other workspaces and removing bindings no longer inspect unselected chat folders.
- The main EXE opens a standalone WebView2 app window, without a browser tab or console.
	Closing the app stops its local service; active operations block premature close.
- Separate console CLI for diagnostics. No chat format or shared-pool changes.

## Downloads

- `CopilotChatSync-0.1.1-windows-x64-Setup.exe`: per-user installer and Start menu shortcut. No Python installation required. Offers the Microsoft-signed WebView2 Runtime installer if needed.
- `CopilotChatSync-0.1.1-windows-x64-portable.zip`: extract the entire folder, then open `CopilotChatSync.exe`. Keep all files together and install WebView2 Runtime if missing.
- `CopilotChatSync-0.1.1-desktop.png`: actual desktop-rendering screenshot from CI with synthetic data.
- `SHA256SUMS.txt`: download integrity checksums.

Double-clicking opens the desktop app. Close the app before upgrading or uninstalling.
Uninstall removes the program, not your chat history, shared store or local backups.
The bundled `CopilotChatSync-CLI.exe` retains the original command-line commands.

## Important Limits

- Our binaries remain unsigned and may trigger Windows SmartScreen. No publisher certificate is configured; switching to a desktop window does not create signing reputation. Do not disable Windows security to install.
- Old untrusted mount points remain protected by Windows. The app starts and lists warnings, but cannot import from blocked links until they are safely migrated. It does not delete or re-trust old links automatically.
- Only legacy extension-host chats are supported, not Agent Host/CLI sessions.
- Back up chats and code first. Apply still requires closing VS Code and explicit confirmation.
- One shared store is one chat pool, not automatic per-project matching.
- Wait for OneDrive on both computers. The app does not verify cloud delivery.
- Real two-PC OneDrive delivery and native Copilot continuation still need a pilot; automated fixtures and installer smoke tests are not that pilot.

See the [quick start](https://github.com/ziao-liu/copilot_chat_sync#readme) and
[advanced guide](https://github.com/ziao-liu/copilot_chat_sync/blob/main/docs/advanced.md)
for setup, old-link migration and recovery. Project license: MIT.