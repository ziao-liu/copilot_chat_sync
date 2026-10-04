import http.client
import contextlib
import json
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from copilot_chat_sync import __version__
from copilot_chat_sync.desktop import desktop_check, main, require_webview_runtime, run
from copilot_chat_sync.sessions import SyncError


class Event:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, handler):
        self.handlers.append(handler)
        return self


class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.config = Path(self.temporary.name) / "local/config.json"
        self.window = types.SimpleNamespace(events=types.SimpleNamespace(closing=Event(), initialized=Event()), destroy=Mock())
        self.webview = types.SimpleNamespace(settings={}, create_window=Mock(return_value=self.window), start=Mock())

    def test_window_owns_authenticated_service_and_shuts_it_down(self):
        addresses = []

        def show_window(callback, **options):
            url = urlsplit(self.webview.create_window.call_args.kwargs["url"])
            addresses.append((url.hostname, url.port))
            client = http.client.HTTPConnection(url.hostname, url.port, timeout=5)
            client.request("GET", "/api/state")
            response = client.getresponse()
            self.assertEqual(response.status, 401)
            response.read()
            token = parse_qs(url.fragment)["token"][0]
            client.request("GET", "/api/state", headers={"Authorization": "Bearer " + token})
            response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertFalse(json.loads(response.read())["configured"])
            client.close()
            self.assertTrue(options["private_mode"])
            self.assertFalse(options["debug"])
            self.assertTrue(Path(options["storage_path"]).is_dir())
            self.assertIsNone(callback)

        self.webview.start.side_effect = show_window
        with patch.dict("sys.modules", {"webview": self.webview}), patch("copilot_chat_sync.desktop.require_webview_runtime"), patch("webbrowser.open") as browser:
            run(self.config)
        browser.assert_not_called()
        self.assertFalse(self.config.exists())
        self.assertFalse(self.webview.settings["ALLOW_FILE_URLS"])
        self.assertFalse(self.webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"])
        self.assertNotIn("js_api", self.webview.create_window.call_args.kwargs)
        self.assertFalse(any(thread.name == "chat-sync-local-service" for thread in threading.enumerate()))
        with self.assertRaises(OSError):
            client = http.client.HTTPConnection(*addresses[0], timeout=1)
            try:
                client.request("GET", "/")
            finally:
                client.close()

    def test_gui_failure_still_stops_local_service(self):
        self.webview.start.side_effect = RuntimeError("GUI unavailable")
        with patch.dict("sys.modules", {"webview": self.webview}), patch("copilot_chat_sync.desktop.require_webview_runtime"):
            with self.assertRaisesRegex(RuntimeError, "GUI unavailable"):
                run(self.config)
        self.assertFalse(any(thread.name == "chat-sync-local-service" for thread in threading.enumerate()))

    def test_close_is_refused_during_an_operation(self):
        from copilot_chat_sync.panel import Panel
        panels = []

        def create_panel(*args, **kwargs):
            panel = Panel(*args, **kwargs)
            panels.append(panel)
            return panel

        def show_window(*args, **kwargs):
            closing = self.window.events.closing.handlers[0]
            self.assertTrue(closing())
            with panels[0].exclusive():
                self.assertFalse(closing())
            self.assertTrue(closing())

        self.webview.start.side_effect = show_window
        with patch.dict("sys.modules", {"webview": self.webview}), patch("copilot_chat_sync.desktop.require_webview_runtime"), patch("copilot_chat_sync.desktop.Panel", side_effect=create_panel):
            run(self.config)

    def test_demo_flag_is_required_for_smoke_mode(self):
        with self.assertRaises(SystemExit) as result:
            main(["--smoke-test", str(Path(self.temporary.name) / "report.json")])
        self.assertEqual(result.exception.code, 2)

    def test_rendering_check_targets_simplified_handoff(self):
        report = Path(self.temporary.name) / "rendering.json"
        result = {"version": __version__, "demo": True, "error": False, "handoff": True,
                  "actions": 2, "actionsVisible": True, "projectChoices": 4,
                  "selectedProjects": 1, "projectFolders": 8, "overflow": False, "fonts": "loaded"}

        def evaluate(script, callback):
            self.assertIn("getElementById('version')", script)
            self.assertIn("getElementById('demo-banner')", script)
            self.assertIn(".transfer-actions button", script)
            self.assertIn("rect.bottom <= innerHeight", script)
            self.assertIn("getElementById('project-tree')", script)
            callback(result.copy())

        window = types.SimpleNamespace(events=types.SimpleNamespace(loaded=Mock()),
                                       evaluate_js=evaluate, gui=types.SimpleNamespace(renderer="test"))
        with patch("copilot_chat_sync.desktop.sys.platform", "linux"):
            desktop_check(window, report)
            self.assertEqual(json.loads(report.read_text())["actions"], 2)
            result["actions"] = 1
            with self.assertRaisesRegex(RuntimeError, "rendering check failed"):
                desktop_check(window, Path(self.temporary.name) / "invalid.json")
            result["actions"] = 2
            result["actionsVisible"] = False
            with self.assertRaisesRegex(RuntimeError, "rendering check failed"):
                desktop_check(window, Path(self.temporary.name) / "offscreen.json")
            result["actionsVisible"] = True
            result["selectedProjects"] = 2
            with self.assertRaisesRegex(RuntimeError, "rendering check failed"):
                desktop_check(window, Path(self.temporary.name) / "multiple-projects.json")

    def test_main_selects_native_window_and_reports_failure(self):
        with patch("copilot_chat_sync.desktop.run") as application:
            self.assertEqual(main(["--config", str(self.config), "--demo"]), 0)
        application.assert_called_once_with(self.config, True, None)

    def test_webview_runtime_is_required_without_legacy_fallback(self):
        registry = types.SimpleNamespace(HKEY_CURRENT_USER=1, HKEY_LOCAL_MACHINE=2,
                                         KEY_WOW64_32KEY=1, KEY_WOW64_64KEY=2, KEY_READ=4,
                                         OpenKey=Mock(side_effect=FileNotFoundError), QueryValueEx=Mock())
        with patch("copilot_chat_sync.desktop.sys.platform", "win32"), patch.dict("sys.modules", {"winreg": registry}):
            with self.assertRaisesRegex(SyncError, "Evergreen Runtime"):
                require_webview_runtime()
            registry.OpenKey.side_effect = None
            registry.OpenKey.return_value = contextlib.nullcontext()
            registry.QueryValueEx.return_value = ("130.0.1.0", 1)
            require_webview_runtime()


if __name__ == "__main__":
    unittest.main()