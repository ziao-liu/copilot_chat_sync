"""Exercise a distributed executable using isolated, synthetic data."""

from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def smoke_desktop(executable: Path, version: str, screenshot: Path) -> None:
    from PIL import Image
    binary = executable.read_bytes()
    offset = struct.unpack_from("<I", binary, 0x3c)[0]
    if binary[:2] != b"MZ" or struct.unpack_from("<H", binary, offset + 24 + 68)[0] != 2:
        raise RuntimeError("Desktop executable must use the Windows GUI subsystem, without a console")
    with tempfile.TemporaryDirectory(prefix="chat-sync-native-smoke-") as temporary:
        root = Path(temporary)
        environment = dict(os.environ)
        for name in ("PYTHONPATH", "PYTHONHOME"):
            environment.pop(name, None)
        for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "OneDrive", "OneDriveConsumer", "OneDriveCommercial", "TMP", "TEMP", "TMPDIR"):
            directory = root / name
            directory.mkdir()
            environment[name] = str(directory)
        environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        report = root / "desktop.json"
        process = subprocess.Popen([str(executable.resolve()), "--demo", "--smoke-test", str(report)], cwd=root, env=environment)
        try:
            code = process.wait(timeout=150)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
        result = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {"error": "No desktop report was produced"}
        if code or result.get("error") or result.get("version") != version or result.get("renderer") != "edgechromium":
            raise RuntimeError("Native desktop smoke failed: " + str(result))
        image_path = report.with_suffix(".png")
        with Image.open(image_path) as image:
            extrema = image.convert("RGB").getextrema()
            if image.width < 600 or image.height < 400 or max(high - low for low, high in extrema) < 50:
                raise RuntimeError("Native desktop screenshot is blank or incorrectly sized")
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(image_path, screenshot)
    print("Native desktop smoke passed: GUI subsystem, WebView2, authenticated UI, fonts/icons, screenshot and clean exit.")


def smoke(command: list[str], version: str) -> None:
    with tempfile.TemporaryDirectory(prefix="chat-sync-bundle-") as temporary:
        root = Path(temporary)
        environment = dict(os.environ)
        for name in ("PYTHONPATH", "PYTHONHOME"):
            environment.pop(name, None)
        for name in ("LOCALAPPDATA", "APPDATA", "XDG_CONFIG_HOME", "OneDrive", "OneDriveConsumer", "OneDriveCommercial", "TMP", "TEMP", "TMPDIR"):
            directory = root / name
            directory.mkdir()
            environment[name] = str(directory)
        if os.name == "nt":
            environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
        result = subprocess.run([*command, "--version"], cwd=root, env=environment,
                                capture_output=True, text=True, timeout=60, check=True)
        if result.stdout.strip() != version:
            raise RuntimeError("Executable version does not match the package")
        process = subprocess.Popen([*command, "--config", str(root / "config.json"), "panel", "--demo", "--no-browser", "--port", "0"],
                                   cwd=root, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
        messages: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            for line in process.stdout:
                messages.put(line)
            messages.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + 60
            while True:
                try:
                    line = messages.get(timeout=max(0.01, deadline - time.monotonic()))
                except queue.Empty as error:
                    raise RuntimeError("Panel did not print a startup URL within 60 seconds") from error
                if line is None:
                    raise RuntimeError("Executable exited before starting the panel")
                if line.startswith("Read-only demo: "):
                    url = urlsplit(line.removeprefix("Read-only demo: ").strip())
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("Panel startup timed out")
            if url.scheme != "http" or url.hostname != "127.0.0.1":
                raise RuntimeError("Panel is not using loopback HTTP")
            token = parse_qs(url.fragment)["token"][0]
            origin = f"{url.scheme}://{url.netloc}"
            opener = build_opener(ProxyHandler({}))

            def request(path: str, data: dict | None = None, authenticated: bool = True, request_origin: str | None = None):
                headers = {"Origin": request_origin or origin}
                if authenticated:
                    headers["Authorization"] = "Bearer " + token
                if data is not None:
                    headers["Content-Type"] = "application/json"
                body = json.dumps(data).encode() if data is not None else None
                try:
                    with opener.open(Request(origin + path, data=body, headers=headers), timeout=10) as response:
                        return response.status, response.read()
                except HTTPError as error:
                    with error:
                        return error.code, error.read()

            status, payload = request("/api/state")
            if status != 200:
                raise RuntimeError(f"Panel state returned HTTP {status}")
            state = json.loads(payload)
            if not state["demo"] or not state["process_check_ok"] or state["version"] != version:
                raise RuntimeError("Demo, process detection or version check failed in the executable")
            if not Path(state["config_path"]).is_relative_to(root):
                raise RuntimeError("Demo configuration escaped the isolated data directory")
            assets = Path(__file__).resolve().parents[1] / "src/copilot_chat_sync/web"
            for route, relative in (("/", "index.html"), ("/app.js", "app.js"), ("/style.css", "style.css"),
                                    ("/vendor/lucide.js", "vendor/lucide.js"), ("/vendor/plex-sans.woff2", "vendor/plex-sans.woff2")):
                status, payload = request(route)
                if status != 200 or payload != (assets / relative).read_bytes():
                    raise RuntimeError(f"Bundled resource missing or different: {relative}")
            if request("/api/state", authenticated=False)[0] != 401:
                raise RuntimeError("Unauthenticated API access was allowed")
            selected = [workspace["id"] for workspace in state["workspaces"] if workspace["bound"]]
            status, payload = request("/api/preview", {"action": "push", "workspaces": selected})
            plan = json.loads(payload)
            if status != 200 or not plan.get("read_only"):
                raise RuntimeError("Demo preview failed")
            if request("/api/apply", {"plan": plan["plan"]})[0] != 403:
                raise RuntimeError("Demo allowed synchronization")
            if request("/api/preview", {}, request_origin="https://example.invalid")[0] != 403:
                raise RuntimeError("Cross-origin API access was allowed")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
            reader.join(timeout=5)
            process.stdout.close()
    print("Executable smoke passed: version, isolated demo, assets, process check and API protections.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--version", required=True)
    arguments = parser.parse_args()
    try:
        smoke([str(arguments.executable.resolve())], arguments.version)
    except Exception as error:
        message = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error::" + message)
        raise