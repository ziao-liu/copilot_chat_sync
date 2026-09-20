"""Build and verify Windows release artifacts on a clean Windows x64 account."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from importlib.metadata import distribution
from pathlib import Path

from smoke_bundle import smoke


def installer_process(executable: Path, arguments: list[str]) -> None:
    environment = dict(os.environ, CCS_INSTALLER=str(executable), CCS_INSTALL_ARGS=subprocess.list2cmdline(arguments))
    script = "$ErrorActionPreference='Stop'; $process = Start-Process -FilePath $env:CCS_INSTALLER -ArgumentList $env:CCS_INSTALL_ARGS -Wait -PassThru; exit $process.ExitCode"
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                   env=environment, check=True, timeout=180)


def verify_installer(installer: Path, version: str) -> None:
    import winreg
    key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ziao-liu.CopilotChatSync_is1"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, key, access=winreg.KEY_READ | view):
                    raise RuntimeError("Installer smoke requires an account without an existing Copilot Chat Sync installation")
            except FileNotFoundError:
                pass
    data_directory = Path(os.environ["LOCALAPPDATA"]) / "CopilotChatSync"
    if data_directory.exists():
        raise RuntimeError("Installer smoke requires an account without existing Copilot Chat Sync user data")
    data_directory.mkdir()
    marker = data_directory / "release-smoke.txt"
    try:
        marker.write_text("User data must survive uninstall", encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="chat-sync-install-") as temporary:
            target = Path(temporary) / "installed app"
            try:
                installer_process(installer, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", f"/DIR={target}"])
                smoke([str(target / "CopilotChatSync.exe")], version)
            finally:
                uninstaller = target / "unins000.exe"
                if uninstaller.exists():
                    installer_process(uninstaller, ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"])
            if (target / "CopilotChatSync.exe").exists() or marker.read_text(encoding="utf-8") != "User data must survive uninstall":
                raise RuntimeError("Installer removal or user-data preservation check failed")
    finally:
        marker.unlink(missing_ok=True)
        if data_directory.exists():
            data_directory.rmdir()


def main() -> None:
    if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Build on Windows with x64 Python; PyInstaller is not a cross-compiler")
    from copilot_chat_sync import __version__
    version = distribution("copilot-chat-sync").version
    if version != __version__ or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise RuntimeError("Package metadata and runtime versions must match a numeric release version")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ.get("GITHUB_REF_NAME") != "v" + version:
        raise RuntimeError("Release tag must match the package version")
    root = Path(__file__).resolve().parents[1]
    bundle = root / "dist/CopilotChatSync"
    output = root / "dist/release"
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--noupx",
                    "--name=CopilotChatSync", "--collect-data=copilot_chat_sync", "--hidden-import=psutil._psutil_windows",
                    "--distpath", str(root / "dist"), "--workpath", str(root / "build"), "--specpath", str(root / "build"),
                    str(root / "scripts/desktop.py")], cwd=root, check=True)
    for filename in ("LICENSE", "README.md"):
        shutil.copy2(root / filename, bundle / filename)
    shutil.copytree(root / "docs", bundle / "docs")
    licenses = bundle / "licenses"
    licenses.mkdir()
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.is_file():
        raise RuntimeError("Python distribution license is missing")
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
    for package in ("psutil", "pyinstaller"):
        metadata = distribution(package)
        files = [entry for entry in metadata.files or [] if entry.name.upper().startswith(("LICENSE", "COPYING"))]
        if not files:
            raise RuntimeError(f"Distribution license is missing: {package}")
        destination = licenses / package
        destination.mkdir()
        for index, entry in enumerate(files):
            shutil.copy2(metadata.locate_file(entry), destination / f"{index:02d}-{entry.name}")
    vendor = root / "src/copilot_chat_sync/web/vendor"
    for filename in ("lucide-LICENSE", "plex-LICENSE", "SOURCES.txt"):
        shutil.copy2(vendor / filename, licenses / filename)
    build_info = {"version": version, "commit": os.environ.get("GITHUB_SHA", "local"), "target": "windows-x64",
                  "python": platform.python_version(), "pyinstaller": distribution("pyinstaller").version,
                  "psutil": distribution("psutil").version, "signed": False}
    (bundle / "BUILD_INFO.json").write_text(json.dumps(build_info, indent=2) + "\n", encoding="utf-8")
    portable = Path(shutil.make_archive(str(output / f"CopilotChatSync-{version}-windows-x64-portable"),
                                       "zip", root_dir=bundle.parent, base_dir=bundle.name))
    with tempfile.TemporaryDirectory(prefix="chat-sync-portable-") as temporary:
        extracted = Path(temporary) / "portable app"
        with zipfile.ZipFile(portable) as archive:
            archive.extractall(extracted)
        smoke([str(extracted / "CopilotChatSync/CopilotChatSync.exe")], version)
    compiler = shutil.which("ISCC.exe") or str(Path(os.environ["ProgramFiles(x86)"]) / "Inno Setup 6/ISCC.exe")
    subprocess.run([compiler, f"/DAppVersion={version}", f"/DBundleDir={bundle}", f"/DOutputDir={output}",
                    str(root / "packaging/windows.iss")], cwd=root, check=True)
    installer = output / f"CopilotChatSync-{version}-windows-x64-Setup.exe"
    if not installer.is_file():
        raise RuntimeError("Installer was not produced")
    verify_installer(installer, version)
    checksums = []
    for artifact in (installer, portable):
        checksum = hashlib.sha256(artifact.read_bytes()).hexdigest()
        checksums.append(f"{checksum}  {artifact.name}\n")
    (output / "SHA256SUMS.txt").write_text("".join(checksums), encoding="ascii", newline="\n")
    print("Windows installer and portable ZIP verified; SHA256SUMS.txt written.")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error::" + message)
        raise