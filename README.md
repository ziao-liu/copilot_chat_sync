# Copilot Chat Sync

Move **legacy VS Code Copilot chats** between computers through OneDrive or another
synced folder. A local browser panel handles setup, transfers, conflicts and backups.

**Run it on each desktop computer, not your SSH servers.**

> Early preview, unofficial. Python 3.10+ is required. Real Windows/OneDrive handoff
> and native Copilot continuation still need a pilot. Not for Agent Host or CLI sessions.

![Workspace folders and chat transfers](docs/images/workspaces.png)

## Start

On each computer, open a local PowerShell or Anaconda Prompt:

```powershell
git clone https://github.com/ziao-liu/copilot_chat_sync.git
cd copilot_chat_sync
python -m pip install .
python -m copilot_chat_sync panel
```

Your browser opens automatically. Keep this terminal running; `Ctrl+C` stops the panel.
For later launches, only the last command is needed.

## Set Up Once

1. Check the detected OneDrive folder and local VS Code data location.
   Use **Change locations** only when needed.
2. Click **Continue**, then choose workspaces in the server/folder tree.
   Missing project? Open it once in desktop VS Code, then **Scan again**.
3. Click **Review setup**, close VS Code, and **Confirm & apply**.

![Choose workspaces by server and folder](docs/images/choose-workspaces.png)

Repeat on the other computer using the **same cloud folder** and its own local workspaces.
The local data folder on standard Windows VS Code is `%APPDATA%\Code\User\workspaceStorage`.

> **One shared folder = one chat pool.** Receive imports that pool into every selected
> workspace. The directory tree is visual grouping, not per-project isolation.
> Use [separate groups](docs/advanced.md#separate-groups) for unrelated projects.

## Switch Computers

1. **Computer A:** close VS Code, select **Send**, review and confirm.
2. Wait for OneDrive to finish uploading and downloading on **both computers**.
3. **Computer B:** keep VS Code closed, send any existing local changes first,
   resolve conflicts if needed, then **Receive**. Reopen VS Code afterward.

Send/Receive works on the local sync folder; success does not confirm cloud delivery.
Conflicting versions are kept for review, not silently overwritten or combined.

![Review competing chat versions](docs/images/conflicts.png)

## Before Your First Sync

- Back up your chats and project code. Test with one non-editing conversation first.
- Stop old sync/link scripts on **every computer**. For old directory links, use
  **Review old setup**; use a new tool folder, not the old raw chat folder.
- Editing-snapshot quarantine needs explicit confirmation and removes access to old
  undo/checkpoints. This tool does not sync project code or live editing state.
- Keep the shared folder private. Chats/backups are not encrypted by this tool;
  do not share the panel's private URL.

## More

Preview the interface without touching your chats:

```powershell
python -m copilot_chat_sync panel --demo
```

Update an existing checkout, then restart the panel:

```powershell
git pull --ff-only
python -m pip install .
```

[Migration, recovery, CLI and limitations](docs/advanced.md).
All screenshots use synthetic demo data.