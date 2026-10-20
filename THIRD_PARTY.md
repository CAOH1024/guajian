# Third-party software and source access

The application code, C# launcher/installer and build scripts are MIT licensed.
Third-party runtime components retain their own licenses; they are not
relicensed under MIT. See `licenses/` in the Windows release.

## Qt / PySide6 / Shiboken6 6.10.3

The application dynamically loads the separate, replaceable Qt and binding
libraries under `runtime/_internal`. This release uses the LGPLv3 option for
Qt Core, Gui, Widgets and Network and the PySide6/Shiboken6 bindings. Copies of
LGPLv3 and GPLv3, binding distribution notices and third-party license notices
are provided. No Qt libraries are modified.

Corresponding upstream sources (same version as the supplied libraries):

- https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.10.3-src/
- https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.10.3
- https://download.qt.io/official_releases/qt/6.10/6.10.3/submodules/
- https://code.qt.io/cgit/qt/qtbase.git/tag/?h=v6.10.3
- https://doc.qt.io/qtforpython-6/licenses.html

You may modify or replace these libraries, and reverse engineer this application
to debug those modifications. Replace the separate DLLs/PYD files with compatible
builds of the same Python ABI and architecture; do not change their relative
layout. The launcher contains no integrity lock and performs no signature check
on replacement libraries. Build instructions are in README.md and the build script.

## Python

The Windows build includes an unmodified CPython runtime, with its matching PSF
license included. The exact Python version is recorded in BUILD-INFO.json.
GitHub Actions uses Python 3.12; offline builds may use another compatible version.
CPython source: https://www.python.org/downloads/source/

## Tooling

PyInstaller 6.22.0 is used only to collect runtime dependencies during builds;
its bootloader is discarded and is not used by the distributed launcher.
https://pyinstaller.org/en/stable/license.html

The C# EXEs target .NET Framework, supplied by Windows (not redistributed here).
Microsoft runtime DLLs supplied by Qt/Python remain separate files.

## Reference and assets

UI inspiration: https://github.com/MeteorNOX/DeepSeek-Balance-Whale-Widget
(MIT; upstream license retained in licenses/Reference-MIT.txt). This application
is an independent implementation and does not bundle the upstream character.
Generated mascot provenance and scope of asset permission: assets/LICENSE.md.

Before publishing rebuilt binaries, keep these notices and the exact runtime
version/source information alongside the download. Do not include local account
snapshots, credentials, logs or the `state/` directory.
