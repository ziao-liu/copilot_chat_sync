# Third-Party Notices

Copilot Chat Sync is MIT-licensed. Bundled components keep their own licenses:

| Component                      | License                                                 | Bundled notice                |
| ------------------------------ | ------------------------------------------------------- | ----------------------------- |
| CPython and standard library   | Python Software Foundation License and included notices | `licenses/Python-LICENSE.txt` |
| psutil                         | BSD-3-Clause                                            | `licenses/psutil/`            |
| PyInstaller bootloader/runtime | GPL-2.0-or-later with distribution exception            | `licenses/pyinstaller/`       |
| Lucide 0.468.0                 | ISC                                                     | `licenses/lucide-LICENSE`     |
| IBM Plex Sans                  | SIL Open Font License 1.1                               | `licenses/plex-LICENSE`       |

The Windows build collects the Python, psutil and PyInstaller license files from
the actual build environment. `BUILD_INFO.json` records their versions and the
source commit. Vendored font/icon sources are listed in `licenses/SOURCES.txt`.

The installer is built with [Inno Setup](https://jrsoftware.org/isinfo.php).
The app and installer are unsigned; SHA256 hashes detect download changes but
are not a substitute for a trusted publisher signature.