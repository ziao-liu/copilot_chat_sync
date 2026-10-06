# Release Reviews

## v0.1.8 Overall Progress and Single-Pass Startup

The initial "reading local records" screen had no progress reporting. Startup
also loaded the shared store separately for status, counts and conflicts, with
one pass outside the verified metadata cache. It now validates the shared graph
once inside the cache scope and reuses that graph for counts/conflict summaries.
Regression coverage asserts one store load per state request and no JSON
reparsing on an unchanged subsequent startup. Fresh full-file checksums remain.

Startup and refresh now use the authenticated request-progress endpoint. Native
HTML bars explicitly fill left to right. Overall progress is based on completed
steps, subdivided into verified revisions and processed chats; individual file
byte counters remain details rather than resetting the bar. One-click transfers
continue through preflight (0-40%), execution (40-90%) and refresh (90-100%),
sharing elapsed time. These phase shares are not byte/time proportions or an
estimated remaining duration. Progress is local, not OneDrive cloud delivery.

Only the final successful response displays 100%. Exceptions retain partial
progress, clean nested contexts and stop polling; stale request IDs cannot
replace the active operation. Tests exercise nested work, file transitions,
empty stores, failures and real first/unchanged send-receive operations. Frontend
tests verify the complete three-request flow, refresh failures, stale responses
and the final-response completion boundary. All 114 Python tests pass locally
(three Windows-only skips), alongside frontend and syntax checks. Existing
cross-platform, real-size, memory and Windows packaging gates remain required.

## v0.1.7 Incremental Checks and Bounded Multi-Chat Memory

The v0.1.6 workload loaded all native chats and incoming snapshots simultaneously,
replayed unchanged logs, deep-copied owned requests, and repeatedly canonicalized
historical revisions. Four 65 MiB chats required 613.9 MiB RSS and 11.39 seconds
for an unchanged receive; one changed receive parsed 13 payloads (845 MiB).

v0.1.7 processes chats sequentially, stores import plans as checksummed temporary
files, retains only metadata in sync-owned revision graphs, and separates index
metadata from transcripts. A local SQLite cache reuses validated metadata only
after full raw SHA256 verification. It does not trust file size/mtime, skip
checksums, change the shared format, or delete old versions. Public normalization
copy semantics remain; owned parsing and validation avoid redundant deep copies.

The identical workload now completes unchanged receive with zero payload parsing
in 0.47 seconds at 30.7 MiB RSS. One changed receive parses two payloads (130 MiB)
in 3.00 seconds at 161.7 MiB. First-send time did not improve (8.19 to 8.61 seconds).
Four >129 MiB chats pass at <290 MiB peak RSS; these local measurements do not
guarantee user-file or Windows/cloud performance. CI asserts unchanged and
one-changed parsing counts plus a single-chat-scaled RSS ceiling.

Regression tests verify preserved-size/mtime corruption is rejected, dirty native
changes remain protected, damaged metadata cache fails explicitly and corrupted
staging triggers rollback. Staging is checksummed again before destination
replacement; cache seeding verifies the emitted file's expected checksum.
Progress, full raw backup/recovery, process locks, editor-state quarantine and
SQLite compare-and-swap remain. Single decoded models can still exceed the memory
budget; errors now disclose actual RSS, threshold and system available RAM.

## v0.1.6 Visible Check and Transfer Progress

Check/apply dialogs now use native HTML progress bars and an authenticated,
request-specific polling endpoint outside the operation lock. Worker-local
context reporting publishes actual file bytes, stage, elapsed time and verified
revision count. Unknown totals remain indeterminate; no overall percentage or
cloud transfer progress is claimed. Background reads cannot start a second
operation, and stale polling results cannot update a subsequent dialog.

Tests cover concurrent HTTP polling during a held operation, authentication,
request ID isolation, failure completion, byte counters, rendering and timer
cleanup. A real >129 MiB retained first snapshot passed the complete handoff
with reporting enabled at 285.6 MiB sampled peak RSS in 36.8 seconds locally.
This release retains all data-safety checks and does not remove repeated
full-history checks or promise a performance improvement.

## v0.1.5 Giant Initial Snapshots

The v0.1.4 large-log tests did not cover an initial snapshot above 128 MiB.
The reported first-line failure is reproduced by a physical, single-string
135,266,484-byte initial record, not just a large accumulated log. It now
completes Send/Receive, immutable store reload, re-send, plain JSON export and
checksummed raw backup/restore. A 537,919,668-byte first record followed by a
small replacement mutation also completes that chain. Local sampled peak RSS
was 286.0 MiB and 1056.5 MiB respectively. The >513 MiB first record also passes
with the giant string retained through the complete chain, at 1054.0 MiB RSS.
Cumulative-log coverage still passes at 32.3 MiB RSS. CI repeats all four scenarios.

Parsing uses bundled ijson/YAJL with strict one-record-per-line framing and
256-level nesting checks. Canonical serialization streams string escaping,
hashing and atomic writes; compatibility tests preserve existing revision hashes.
Native JSON, records, replayed state, compact imports and shared envelopes use
the same 2 GiB ceiling. Periodic RSS checks reject resource exhaustion explicitly;
the live model remains in RAM, and allocation between checks can exceed the soft
budget. This is not a guarantee for arbitrary multi-gigabyte chats on low-RAM PCs.

Windows packaging collects the parser backends and licenses. The actual bundled
CLI reads a >129 MiB first record during portable and installer verification.
Conflict previews are bounded and visibly labelled; stored/exported/synced chats
are not shortened. Program replacement and configuration/backup retention remain
gated. Real user-file compatibility and two-PC cloud/native continuation still
require a pilot; synthetic tests do not claim those outcomes.

## v0.1.4 Large JSONL Logs and Project Hierarchy

The previous 128 MiB whole-file read rejected otherwise replayable large native
JSONL logs. Parsing now consumes individual records with byte accounting for
mutations and an 8 GiB raw-log ceiling. Shared envelopes and compact imports
are checked against the retained 128 MiB limit before publication. Streaming
hashes/copies replace whole-file buffering in backup, recovery and migration;
source metadata and full checksums are verified before destination replacement.

Local real-size checks used 537,947,484-byte and 2,147,594,534-byte synthetic logs.
Both completed Send/Receive, original-log backup/restore and POSIX migration;
sampled peak RSS was 33.7 MiB, below the 256 MiB regression threshold.
This validates large accumulated logs, not arbitrary multi-gigabyte individual
JSON records or live conversation snapshots.

The picker now uses expandable connection/folder nodes with single-workspace
radio entries, retaining case-sensitive paths, encoded path segments, duplicate
IDs and separate SSH aliases. Installer verification now covers same-directory
reinstallation, stale-binary replacement and config/backup preservation.
Publication remains gated on full CI and native Windows checks.

## v0.1.3 First-Screen Layout

The v0.1.2 Windows release workflow succeeded, including native rendering and
installer checks. Its actual screenshot showed optional warnings pushing the
transfer buttons to the viewport edge. This follow-up places actions before
optional warnings, collapses technical messages and shortens long shared-folder
paths with full-path access retained. Conflict and migration actions remain visible;
no safety checks or acknowledgements are removed.

Native rendering now checks that both transfer buttons are fully inside the
initial viewport. Regressions cover offscreen-button rejection and frontend
ordering. Publication remains gated on the full test matrix and Windows smoke tests.

## v0.1.2 Simplified Interface

The daily panel is now a single-project, Chinese-language handoff page. Normal
Send/Receive still obtain and consume the existing server preview ticket; only
their redundant UI confirmation was removed. Risk-bearing actions retain explicit
confirmation, and checkpoint quarantine retains its acknowledgement checkbox.
Existing multi-workspace configs are not automatically changed. CLI and shared-store
semantics are unchanged.

Local validation covered 52 targeted panel, desktop, CLI and native-sync tests,
then the full 83-test suite (80 passed, 3 Windows-only skipped), plus JavaScript
syntax and frontend interaction checks. Checks exercise single-project selection,
one-click preview/apply ordering, errors, process guards, demo write refusal, conflicts,
ticket expiry, acknowledgement and migration. The source wheel's UI assets were verified.
The desktop-rendering smoke probe now checks the handoff page and two transfer buttons,
not the removed workspace rows and icon library.

Integrated browser access to the SSH host was unavailable. Local headless Chromium
could not launch because required system libraries were missing. No local visual
or native Windows result is claimed. Tag publication remains gated on the full CI
matrix, actual Windows packaging, native WebView2 rendering and installer smoke tests.
Real two-PC cloud delivery and native Copilot continuation remain pilot requirements.

## v0.1.1 Desktop and Mount-Point Fix

Date: 2026-09-21. Baseline: `3cb9f44`. OpenCodeReview delegation preview selected
13 files; 13 excluded tests, installer inputs and documents were manually checked.
`total_files=26`, `reviewed_files=26`, `skipped_files=0`, `coverage_rate=100%`.

The packaging follow-up includes the original upstream license omitted from the
`proxy_tools` 0.1.0 distribution, verified against its Git blob and tied to that
exact dependency version. All four files in that follow-up were reviewed, including
the three excluded by OCR. Runtime bootstrapper downloads use non-interactive basic
parsing and report PowerShell failures without removing the signature requirement.
Windows PowerShell child processes do not inherit PowerShell Core module paths;
a regression covers environment-key casing and preservation of the parent process.

The original startup failure was reproduced with an OSError carrying WinError 448.
Linked chat targets are no longer opened by normal scan/status; inaccessible workspaces
remain warnings rather than aborting the app. Preview stamping only inspects the
selected operation scope; binding changes do not traverse chat contents. Migration
still fails closed when Windows blocks the source. No mount trust or OS security
settings are modified, and no chat data is deleted to resolve the warning.

The default executable now hosts the authenticated loopback UI in a native WebView2
window, with no Python file-operation API exposed to JavaScript. Window close is
blocked during operations, server threads are joined on shutdown, file URLs are
disabled, and unsupported legacy renderers are rejected. The console CLI is separate.

Local validation: 82 tests, 79 passed and 3 Windows-only skipped; frontend hierarchy
checks passed. Windows packaging must additionally verify GUI PE subsystem, actual
WebView2 rendering, fonts/icons, nonblank screenshot, clean process exit and the
installed app before publication. The bundled runtime bootstrapper must have a valid
Microsoft Authenticode signature. This does not sign our own app or installer.

No code-signing identity was available, as confirmed by the user. `signed: false`
remains explicit. SmartScreen reputation and real two-PC legacy-chat continuation
cannot be certified by these tests. Native Windows build results are reported in
the release workflow, not inferred from mocked lifecycle tests.

## v0.1.0

Date: 2026-09-21. Baseline: `67a52c7`. Target: first unsigned Windows x64 preview.

## Method and Coverage

Used Alibaba OpenCodeReview v1.12.7 in **delegation mode**: its CLI selected files
and supplied review rules; GitHub Copilot performed the review. No separate LLM/API
provider was called. The project skill is pinned and licensed separately under Apache-2.0.
The host has Git 2.39.5, below OCR's supported 2.41 minimum; preview and rule commands
returned valid JSON with a warning. This is not an independent third-party certification.

The final pre-build checklist has 20 files: 9 selected by OCR, 9 excluded by its
default filters but manually inspected, plus the quick-start and this report.
`total_files=20`, `reviewed_files=20`, `skipped_files=0`, `coverage_rate=100%`.

| File                                                 | Review status                                                                   |
| ---------------------------------------------------- | ------------------------------------------------------------------------------- |
| `.github/workflows/ci.yml`                           | Reviewed: matrix, Windows gates, artifacts, timeout                             |
| `.github/workflows/release.yml`                      | Reviewed: tag-only publication, prerequisites, permissions, checksums           |
| `.gitignore`                                         | Reviewed: local OCR binary excluded                                             |
| `pyproject.toml`                                     | Reviewed: runtime requirements and project license                              |
| `LICENSE`                                            | Reviewed: user-selected MIT terms                                               |
| `.github/skills/open-code-review-delegate/LICENSE`   | Reviewed: upstream Apache-2.0 license                                           |
| `scripts/desktop.py`                                 | Reviewed: no-argument panel, argument and exit-code forwarding                  |
| `scripts/build_windows.py`                           | Reviewed: isolated packaging, licenses, installer lifecycle, hashes             |
| `scripts/smoke_bundle.py`                            | Reviewed: process cleanup, loopback/auth, packaged resources                    |
| `MANIFEST.in`                                        | Manually reviewed: build scripts/docs/installer inputs in source package        |
| `tests/test_cli.py`                                  | Manually reviewed: launcher and real source-process smoke                       |
| `packaging/windows.iss`                              | Manually reviewed: per-user install, no data deletion rules or forced app close |
| `packaging/requirements-windows.txt`                 | Manually reviewed: pinned PyInstaller build dependency                          |
| `.github/skills/open-code-review-delegate/SKILL.md`  | Upstream blob hash verified; delegation procedure read                          |
| `.github/skills/open-code-review-delegate/ORIGIN.md` | Manually reviewed: source, scope and limitations                                |
| `docs/advanced.md`                                   | Manually reviewed: binary usage and retained safety guidance                    |
| `docs/release-notes.md`                              | Manually reviewed: preview status, unsigned distribution, remaining pilot       |
| `docs/third-party-notices.md`                        | Manually reviewed: bundled dependencies keep their licenses                     |
| `README.md`                                          | Manually reviewed: binary-first quick start and shared-pool limitation          |
| `docs/release-review.md`                             | Manually reviewed: scope and evidence, no invented Windows results              |

## Finding Addressed

**Medium / test**: installer smoke originally used a marker in an unrelated temporary
folder, which did not prove preservation of the default user-data location. It now
creates a marker in `%LOCALAPPDATA%\CopilotChatSync`, refuses pre-existing data, verifies
the marker after uninstall and removes only its own file/empty directory. A local
contract test confirmed this behavior. Actual Inno Setup execution is a Windows CI gate.

No remaining critical/high/medium findings were identified in these changes after
the correction. The review did not change synchronization semantics or remove
closed-editor, preview, locking, conflict or recovery protections.

## Validation Boundary

Local checks cover launcher default/arguments/exit status, a real isolated panel
process, static assets, authentication, cross-origin rejection, demo write rejection,
and workflow/script syntax. Windows CI must build, extract, install, run and uninstall
the actual distributions before release. A tag triggers the full matrix again; the
publish job depends on its success. Do not infer Windows build success from this report.

Unsigned publisher warnings, private VS Code storage compatibility, and a real
two-PC OneDrive/native Copilot continuation pilot remain release limitations.