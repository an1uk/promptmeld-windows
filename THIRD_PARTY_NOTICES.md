# Third-party notices

PromptMeld's original source code is licensed under MIT. The components below
remain under their own licences; they are not relicensed as MIT.

The exact package versions and selected licence terms for a portable build are
recorded in `LICENSES/DEPENDENCY_AUDIT.txt` inside that build.

## Runtime components

| Component | Selected licence | Notes |
|---|---|---|
| Python | PSF-2.0 | The portable release includes the Python runtime. |
| PySide6, PySide6 Essentials/Addons, Shiboken6, and the included Qt libraries | LGPL-3.0-only | Used under the LGPL option offered by Qt for Python. |
| pywin32 | PSF-2.0 | Windows API integration. |
| pywinauto | BSD-3-Clause | UI Automation companion. |
| comtypes | MIT | Transitive pywinauto dependency. |
| six | MIT | Transitive pywinauto dependency. |
| OpenSSL | Apache-2.0 | Used by the packaged Python/Qt networking libraries. |
| libffi | MIT-style permissive licence | Used by Python's `ctypes` support. |
| Mesa llvmpipe | Permissive component licences documented by Qt | Packaged by Qt as the optional `opengl32sw.dll` software renderer. |
| Lucide Icons | ISC and MIT | Curated action and folder icons. |
| Microsoft Visual C++ Runtime | Microsoft redistributable terms | Toolchain runtime shipped by the upstream Python/Qt wheels. |

Python's full licence and incorporated-software acknowledgements, package
licence files, the Lucide notice, the Apache 2.0 text, and the GNU GPLv3/LGPLv3
texts are shipped in the release's `LICENSES` directory.

## Qt and LGPL compliance

The community PySide6 packages offer LGPLv3, GPL, and commercial alternatives.
PromptMeld selects **LGPL-3.0-only** for the Qt/PySide components it uses.

PromptMeld:

- uses Qt as separately loaded DLLs under `_internal\PySide6`;
- does not modify Qt or PySide6;
- does not prohibit reverse engineering for debugging modifications to those
  LGPL components;
- leaves the one-folder package open so users can replace the LGPL libraries
  with compatible modified builds; and
- removes the unused, GPL-only Qt Virtual Keyboard module from releases.

Corresponding source for the exact Qt and PySide6 versions is available from
the official [Qt source archive](https://download.qt.io/official_releases/qt/)
and [Qt for Python source archive](https://download.qt.io/official_releases/QtForPython/pyside6/).
Qt's component-level third-party notices and SPDX SBOM information are
available from the official [Qt licensing documentation](https://doc.qt.io/qt-6/licensing.html).

## Build and test tools

PyInstaller is GPL-2.0-or-later with its Bootloader Exception, which permits
the generated executable to be distributed under other terms. Its runtime
hooks are Apache-2.0. PyInstaller Community Hooks uses GPL for build-time hooks
and Apache-2.0 for runtime hooks.

The remaining build and test dependencies currently use MIT, BSD-2-Clause,
BSD-3-Clause, Apache-2.0, or PSF-2.0 terms. They are reviewed by
`dependency-license-policy.json` and are not treated as PromptMeld runtime
dependencies.

## Automated policy

`tools/check_licenses.py` resolves the declared runtime, development, and build
dependency graph from `pyproject.toml`. It fails when:

- a new direct or transitive dependency has not been reviewed;
- a dependency is used in a new scope;
- installed package metadata no longer contains the approved licence evidence;
- the bundled Lucide notice or official licence texts change;
- an unreviewed Qt framework or plugin binary enters the release; or
- any other unreviewed native DLL enters the release; or
- required notices are missing from the portable package.

The setup and release build scripts run this check automatically. It is a
practical safeguard, not legal advice or a guarantee that upstream metadata is
complete.
