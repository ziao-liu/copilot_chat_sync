# Third-Party Notices

Copilot Chat Sync is MIT-licensed. Bundled components keep their own licenses:

| Component                      | License                                                 | Bundled notice                |
| ------------------------------ | ------------------------------------------------------- | ----------------------------- |
| CPython and standard library   | Python Software Foundation License and included notices | `licenses/Python-LICENSE.txt` |
| psutil                         | BSD-3-Clause                                            | `licenses/psutil/`            |
| PyInstaller bootloader/runtime | GPL-2.0-or-later with distribution exception            | `licenses/pyinstaller/`       |
| Lucide 0.468.0                 | ISC                                                     | `licenses/lucide-LICENSE`     |
| IBM Plex Sans                  | SIL Open Font License 1.1                               | `licenses/plex-LICENSE`       |

The Windows desktop also bundles pywebview (BSD-3-Clause), pythonnet and clr_loader
(MIT), cffi (MIT), pycparser (BSD), Bottle (MIT), proxy_tools (BSD) and
typing_extensions (PSF). Their actual distribution licenses are copied under
`licenses/<package>/`. The WebView2 SDK and Runtime remain Microsoft components
under their own distribution terms. The runtime bootstrapper is Microsoft-signed;
that signature does not sign Copilot Chat Sync itself.

The Windows build collects the Python and bundled package license files from
the actual build environment. `BUILD_INFO.json` records their versions and the
source commit. Vendored font/icon sources are listed in `licenses/SOURCES.txt`.

`proxy_tools` 0.1.0 omits its license file from its PyPI package. The build includes
the unmodified upstream [LICENSE.txt](https://github.com/jtushman/proxy_tools/blob/master/LICENSE.txt)
from `packaging/licenses/proxy_tools-0.1.0.txt`, verified as Git blob
`078411c7399fbc0454f36cbe8c8cdbaaba7ebc95`. The source's BSD terms and notices are
preserved despite the package metadata naming MIT.

The installer is built with [Inno Setup](https://jrsoftware.org/isinfo.php).
The app and installer are unsigned; SHA256 hashes detect download changes but
are not a substitute for a trusted publisher signature.