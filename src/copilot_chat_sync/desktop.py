"""Native desktop window over the authenticated local synchronization service."""

from __future__ import annotations

import argparse
import ctypes
import json
import queue
import shutil
import sys
import tempfile
import threading
from contextlib import ExitStack
from pathlib import Path
from typing import Callable

from . import __version__
from .panel import Panel, PanelServer, demo_config
from .sessions import SyncError
from .workspace import default_config, expand_path

RUNTIME_URL = "https://developer.microsoft.com/microsoft-edge/webview2/consumer/"


def require_webview_runtime() -> None:
    if sys.platform != "win32":
        return
    import winreg
    key = r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
            try:
                with winreg.OpenKey(hive, key, access=winreg.KEY_READ | view) as entry:
                    version = winreg.QueryValueEx(entry, "pv")[0]
                    if isinstance(version, str) and version.split(".")[0].isdigit() and int(version.split(".")[0]) >= 86:
                        return
            except FileNotFoundError:
                continue
    raise SyncError("Microsoft Edge WebView2 Runtime is required. Install the Evergreen Runtime from Microsoft, then reopen this app. " + RUNTIME_URL)


def desktop_check(window, destination: Path) -> None:
    results: queue.Queue[dict] = queue.Queue()
    if not window.events.loaded.wait(60):
        raise RuntimeError("Desktop window did not load")
    script = """new Promise((resolve, reject) => {
        const timeout = setTimeout(() => reject(new Error('Desktop view did not become ready')), 45000);
        const observer = new MutationObserver(check);
        function check() {
            const content = document.getElementById('content');
            if (!content || content.hidden || document.getElementById('refresh').disabled) return;
            clearTimeout(timeout);
            observer.disconnect();
            document.fonts.ready.then(() => resolve({
                title: document.title,
                version: document.getElementById('footer-version').textContent,
                demo: !document.getElementById('demo-badge').hidden,
                error: !document.getElementById('error-banner').hidden,
                rows: document.querySelectorAll('[data-select]').length,
                icons: document.querySelectorAll('svg.lucide').length,
                fonts: document.fonts.status,
                overflow: document.documentElement.scrollWidth > innerWidth,
                width: innerWidth, height: innerHeight
            }));
        }
        observer.observe(document.documentElement, {subtree:true, attributes:true, childList:true});
        check();
    })"""
    window.evaluate_js(script, callback=results.put)
    result = results.get(timeout=60)
    if not isinstance(result, dict) or result.get("version") != __version__ or not result.get("demo") or result.get("error") or not result.get("rows") or not result.get("icons") or result.get("overflow") or result.get("fonts") != "loaded":
        raise RuntimeError("Desktop rendering check failed: " + str(result))
    result["renderer"] = window.gui.renderer
    if sys.platform == "win32" and result["renderer"] != "edgechromium":
        raise RuntimeError("Desktop did not use WebView2")
    if sys.platform == "win32":
        from System import Action, Func, Object
        from System.IO import MemoryStream
        from System.Threading.Tasks import Task
        from Microsoft.Web.WebView2.Core import CoreWebView2CapturePreviewImageFormat
        captured: queue.Queue[bytes | Exception] = queue.Queue()

        def capture() -> None:
            stream = MemoryStream()

            def finished(task) -> None:
                try:
                    if task.IsFaulted:
                        raise RuntimeError(str(task.Exception))
                    captured.put(bytes(stream.ToArray()))
                except Exception as error:
                    captured.put(error)
                finally:
                    stream.Dispose()

            task = window.native.webview.CoreWebView2.CapturePreviewAsync(CoreWebView2CapturePreviewImageFormat.Png, stream)
            task.ContinueWith(Action[Task](finished))

        window.native.Invoke(Func[Object](capture))
        image = captured.get(timeout=30)
        if isinstance(image, Exception):
            raise image
        with destination.with_suffix(".png").open("xb") as stream:
            stream.write(image)
    with destination.open("x", encoding="utf-8") as stream:
        json.dump(result, stream)


def run(config_path: Path, demo: bool = False, check: Callable | None = None) -> None:
    require_webview_runtime()
    try:
        import webview
    except ImportError as error:
        raise SyncError("Desktop dependencies are missing. Reinstall the Windows app or install copilot-chat-sync[desktop].") from error
    with ExitStack() as resources:
        if demo:
            temporary = resources.enter_context(tempfile.TemporaryDirectory(prefix="chat-sync-desktop-demo-"))
            config_path = demo_config(Path(temporary))
        profile = tempfile.mkdtemp(prefix="chat-sync-webview-")
        resources.callback(shutil.rmtree, profile, ignore_errors=True)
        panel = Panel(config_path, demo=demo)
        server = PanelServer(0, panel)
        worker = threading.Thread(target=server.serve_forever, name="chat-sync-local-service")
        worker.start()
        failures = []
        try:
            webview.settings["ALLOW_FILE_URLS"] = False
            webview.settings["ALLOW_DOWNLOADS"] = True
            webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = False
            window = webview.create_window("Copilot Chat Sync", url=server.origin + "/#token=" + panel.token,
                                           width=1180, height=820, min_size=(680, 520), text_select=True)

            def closing() -> bool:
                return not panel.lock.locked()

            def initialized(renderer) -> bool:
                if sys.platform == "win32" and renderer != "edgechromium":
                    failures.append(SyncError("WebView2 initialization failed. Install the current Microsoft runtime: " + RUNTIME_URL))
                    return False
                return True

            def check_window() -> None:
                try:
                    check(window)
                except Exception as error:
                    failures.append(error)
                finally:
                    window.destroy()

            window.events.closing += closing
            window.events.initialized += initialized
            webview.start(check_window if check else None, gui="edgechromium" if sys.platform == "win32" else None,
                          private_mode=True, storage_path=profile, debug=False)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        if failures:
            raise failures[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="CopilotChatSync", description=__doc__)
    parser.add_argument("--config", type=expand_path, default=default_config())
    parser.add_argument("--demo", action="store_true", help="Use isolated read-only demonstration data")
    parser.add_argument("--smoke-test", type=expand_path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.smoke_test and (not args.demo or args.smoke_test.exists() or not args.smoke_test.parent.is_dir()):
        parser.error("Desktop smoke testing requires --demo and a new report path in an existing directory")
    try:
        run(args.config, args.demo, (lambda window: desktop_check(window, args.smoke_test)) if args.smoke_test else None)
        return 0
    except Exception as error:
        if args.smoke_test:
            if not args.smoke_test.exists():
                with args.smoke_test.open("x", encoding="utf-8") as stream:
                    json.dump({"error": str(error)}, stream)
        elif sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, str(error), "Copilot Chat Sync - Startup problem", 0x10)
        elif sys.stderr:
            print(str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())