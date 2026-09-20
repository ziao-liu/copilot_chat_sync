# Windows Startup and Trust

## WinError 448

This is Windows rejecting traversal of an **untrusted directory mount point**, not
the publisher-signature check. Old OneDrive `chatSessions` junctions can trigger it.

Version 0.1.1 no longer traverses linked chat folders during routine scans. Other
workspaces remain available. An old link shows **Old link** with unknown chat count;
an inaccessible folder shows **Cannot read**. Opening the app does not migrate it.

1. Stop old link/sync scripts on every computer and close VS Code before any migration.
2. Independently back up current project code and original chat files. Do not delete
   the OneDrive source, the whole workspace storage folder or your SQLite database.
3. Select only the affected workspace and use **Review old setup**. Migration creates
   independent local copies when Windows permits reading the source, preserves the
   old shared folder, and requires explicit preview/confirmation.
4. If Windows still blocks the source, the app stops without applying changes. Locate
   the original shared folder and recover/verify its files first. Replacing a junction
   requires distinguishing the link itself from its target; get help with the actual
   link metadata rather than using recursive delete or trust-bypass commands.

Do not disable mount-point protection, Defender or controlled-folder policies.
The app cannot safely undo an inaccessible old setup without access to its source.

## Desktop Runtime

The main EXE hosts the interface in a native Windows WebView2 window. It does not
launch your browser or require Python. Its authenticated server binds only loopback
and stops when the window closes. The original browser interface remains an optional
CLI mode via `CopilotChatSync-CLI.exe panel`.

Windows 11 and most Windows 10 systems already have the Evergreen WebView2 Runtime.
The installer includes Microsoft's bootstrapper, verified during our build with
Windows Authenticode before bundling, and offers to install the runtime if missing.
The portable build does not install prerequisites. Get the Evergreen Runtime from
[Microsoft](https://developer.microsoft.com/microsoft-edge/webview2/consumer/).
There is no fallback to Internet Explorer/MSHTML.

## SmartScreen and Publisher Trust

Copilot Chat Sync binaries currently have **no trusted code-signing certificate**.
A native window, installer metadata, ZIP packaging and SHA256 checksums cannot make
an unsigned publisher trusted. A self-signed certificate is not a public-trust fix.
New, correctly signed software can also require reputation before SmartScreen stops
warning. Managed devices may require an administrator-approved distribution channel.

The supported publishing path is a CA-issued code-signing identity or Microsoft
Artifact Signing, configured by the repository owner. Sign both application EXEs and
the final Setup.exe with SHA256 and a trusted timestamp, verify Authenticode validity,
then generate ZIPs/checksums from the signed files. Store signing credentials only in
protected GitHub secrets or an identity-backed signing service, never in this repo,
chat, command output or the distributed application.

No signing identity is available for v0.1.1, so the release states `signed: false`.
Download only from this repository's release page and verify the listed hashes; do
not turn off Windows security or install an unverified root certificate.