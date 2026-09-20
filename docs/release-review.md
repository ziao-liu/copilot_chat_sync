# Release Reviews

## v0.1.1 Desktop and Mount-Point Fix

Date: 2026-09-21. Baseline: `3cb9f44`. OpenCodeReview delegation preview selected
13 files; 13 excluded tests, installer inputs and documents were manually checked.
`total_files=26`, `reviewed_files=26`, `skipped_files=0`, `coverage_rate=100%`.

The packaging follow-up includes the original upstream license omitted from the
`proxy_tools` 0.1.0 distribution, verified against its Git blob and tied to that
exact dependency version. All four files in that follow-up were reviewed, including
the three excluded by OCR. Runtime bootstrapper downloads use non-interactive basic
parsing and report PowerShell failures without removing the signature requirement.

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

Local validation: 81 tests, 78 passed and 3 Windows-only skipped; frontend hierarchy
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