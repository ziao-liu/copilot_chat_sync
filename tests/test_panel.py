import http.client
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot_chat_sync.panel import ASSETS, Panel, PanelError, PanelServer, demo_config
from copilot_chat_sync.sessions import SyncError, native_bytes, normalize
from copilot_chat_sync.store import Store
from copilot_chat_sync.workspace import Config
from test_sessions import SID, sample
from test_workspace import URI, WID, make_workspace


class PanelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = make_workspace(self.root / "native")
        self.workspace.chats.mkdir()
        (self.workspace.chats / (SID + ".jsonl")).write_bytes(native_bytes(normalize(sample(), SID)))
        self.config = Config(self.root / "local/config.json", self.root / "shared", self.root / "native",
                             bindings=[{"id": WID, "uri": URI}])
        self.config.save()
        Store(self.config.store).initialize()
        self.panel = Panel(self.config.path)
        self.server = PanelServer(0, self.panel)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "appdata")})
        environment.start()
        self.addCleanup(environment.stop)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None, headers=None, authenticated=True):
        client = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        defaults = {"Origin": self.server.origin, "Content-Type": "application/json"}
        if authenticated:
            defaults["Authorization"] = "Bearer " + self.panel.token
        defaults.update(headers or {})
        client.request("POST" if body is not None else "GET", path, json.dumps(body) if body is not None else None, defaults)
        response = client.getresponse()
        payload = response.read()
        status = response.status
        client.close()
        return status, json.loads(payload)

    def preview(self):
        status, result = self.request("/api/preview", {"action": "push", "workspaces": [WID]})
        self.assertEqual(status, 200, result)
        return result

    def test_unauthenticated_and_cross_origin_access_is_rejected(self):
        self.assertEqual(self.request("/api/state", authenticated=False)[0], 401)
        self.assertEqual(self.request("/api/state", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("/api/preview", {}, headers={"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Sec-Fetch-Site": "cross-site"})[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Authorization": "Bearer \u00e9"})[0], 401)

    def test_preview_is_read_only_and_apply_requires_a_ticket(self):
        result = self.preview()
        self.assertEqual(result["result"]["would_publish"], 1)
        self.assertFalse((self.config.store / "revisions").exists())
        self.assertEqual(self.request("/api/apply", {"plan": "forged"})[0], 409)

    def test_apply_uses_existing_process_guard(self):
        result = self.preview()
        with patch("copilot_chat_sync.sync.require_closed", side_effect=SyncError("VS Code is running")):
            status, payload = self.request("/api/apply", {"plan": result["plan"]})
        self.assertEqual(status, 400, payload)
        self.assertFalse((self.config.store / "revisions").exists())

    def test_apply_is_single_use_and_goes_through_cli(self):
        result = self.preview()
        with patch("copilot_chat_sync.sync.require_closed"):
            status, payload = self.request("/api/apply", {"plan": result["plan"]})
        self.assertEqual(status, 200, payload)
        self.assertEqual(payload["published"], 1)
        self.assertEqual(self.request("/api/apply", {"plan": result["plan"]})[0], 409)

    def test_changed_files_and_expired_plans_are_rejected(self):
        result = self.preview()
        path = self.workspace.chats / (SID + ".jsonl")
        path.write_bytes(native_bytes(normalize(sample("changed since preview"), SID)))
        self.assertEqual(self.request("/api/apply", {"plan": result["plan"]})[0], 409)
        result = self.preview()
        self.panel.plan["expires"] = 0
        self.assertEqual(self.request("/api/apply", {"plan": result["plan"]})[0], 409)

    def test_unknown_actions_and_empty_workspace_selection_fail(self):
        for options in ({"action": "shell", "command": "anything"}, {"action": "push", "workspaces": []},
                        {"action": "pull", "workspaces": [WID], "apply": True}, {"action": "restore", "backup": "--help"}):
            self.assertEqual(self.request("/api/preview", options)[0], 400)

    def test_binding_selection_can_remove_without_deleting_chats(self):
        status, result = self.request("/api/preview", {"action": "bindings", "workspaces": []})
        self.assertEqual(status, 200, result)
        with patch("copilot_chat_sync.sync.require_closed"):
            self.assertEqual(self.request("/api/apply", {"plan": result["plan"]})[0], 200)
        self.assertEqual(Config.load(self.config.path).bindings, [])
        self.assertTrue((self.workspace.chats / (SID + ".jsonl")).exists())

    def test_demo_refuses_all_writes(self):
        self.panel.demo = True
        result = self.preview()
        self.assertTrue(result["read_only"])
        self.assertEqual(self.request("/api/apply", {"plan": result["plan"]})[0], 403)

    def test_busy_panel_refuses_overlapping_operations(self):
        with self.panel.exclusive():
            with self.assertRaises(PanelError):
                with self.panel.exclusive():
                    self.fail("Concurrent operation was allowed")

    def test_setup_and_unbound_snapshot_work_without_native_chats(self):
        self.panel.config_path = self.root / "new-control/config.json"
        with patch("copilot_chat_sync.panel.code_processes", return_value=[]):
            status, snapshot = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertFalse(snapshot["configured"])
        status, plan = self.request("/api/preview", {"action": "init", "store": str(self.root / "new-store"), "storage": str(self.config.storage)})
        self.assertEqual(status, 200, plan)
        self.assertFalse(self.panel.config_path.exists())
        with patch("copilot_chat_sync.sync.require_closed"):
            self.assertEqual(self.request("/api/apply", {"plan": plan["plan"]})[0], 200)
        with patch("copilot_chat_sync.panel.code_processes", return_value=[]):
            status, snapshot = self.request("/api/state")
        self.assertEqual(status, 200, snapshot)
        self.assertFalse(snapshot["workspaces"][0]["bound"])

    def test_setup_selects_workspaces_with_one_apply(self):
        self.panel.config_path = self.root / "new-control/config.json"
        before = (self.workspace.chats / (SID + ".jsonl")).read_bytes()
        status, scanned = self.request("/api/scan", {"storage": str(self.config.storage)})
        self.assertEqual(status, 200, scanned)
        self.assertEqual(scanned["workspaces"][0]["id"], WID)
        options = {"action": "init", "store": str(self.root / "new-store"),
                   "storage": str(self.config.storage), "workspaces": [WID]}
        self.assertEqual(self.request("/api/preview", {**options, "workspaces": []})[0], 400)
        status, plan = self.request("/api/preview", options)
        self.assertEqual(status, 200, plan)
        self.assertEqual(plan["result"]["bound"], 1)
        self.assertFalse(self.panel.config_path.exists())
        self.assertFalse((self.root / "new-store").exists())
        with patch("copilot_chat_sync.sync.require_closed"):
            status, result = self.request("/api/apply", {"plan": plan["plan"]})
        self.assertEqual(status, 200, result)
        self.assertEqual(Config.load(self.panel.config_path).bindings, [{"id": WID, "uri": URI}])
        self.assertEqual((self.workspace.chats / (SID + ".jsonl")).read_bytes(), before)
        self.assertEqual(self.request("/api/apply", {"plan": plan["plan"]})[0], 409)

    def test_setup_preview_rejects_changed_workspace_identity(self):
        self.panel.config_path = self.root / "new-control/config.json"
        status, plan = self.request("/api/preview", {"action": "init", "store": str(self.root / "new-store"),
                                                  "storage": str(self.config.storage), "workspaces": [WID]})
        self.assertEqual(status, 200, plan)
        (self.workspace.directory / "workspace.json").write_text(json.dumps({"folder": URI + "-other"}), encoding="utf-8")
        self.assertEqual(self.request("/api/apply", {"plan": plan["plan"]})[0], 409)
        self.assertFalse(self.panel.config_path.exists())
        self.assertFalse((self.root / "new-store").exists())

    def test_quarantine_requires_explicit_acknowledgement(self):
        editing = self.workspace.directory / "chatEditingSessions" / SID
        editing.mkdir(parents=True)
        status, plan = self.request("/api/preview", {"action": "repair", "workspaces": [WID], "detach": True})
        self.assertEqual(status, 200, plan)
        self.assertTrue(plan["needs_acknowledgement"])
        self.assertEqual(self.request("/api/apply", {"plan": plan["plan"]})[0], 400)
        self.assertTrue(editing.exists())
        with patch("copilot_chat_sync.sync.require_closed"):
            self.assertEqual(self.request("/api/apply", {"plan": plan["plan"], "acknowledge": True})[0], 200)
        self.assertFalse(editing.exists())

    def test_static_assets_are_offline_and_protected_by_csp(self):
        for path, relative in (("/", "index.html"), ("/app.js", "app.js"), ("/style.css", "style.css"),
                               ("/vendor/lucide.js", "vendor/lucide.js"), ("/vendor/plex-sans.woff2", "vendor/plex-sans.woff2")):
            client = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
            client.request("GET", path)
            response = client.getresponse()
            self.assertEqual(response.status, 200, path)
            self.assertEqual(response.read(), (ASSETS / relative).read_bytes())
            self.assertIn("frame-ancestors 'none'", response.getheader("Content-Security-Policy"))
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            client.close()
        self.assertEqual(self.request("/../config.json")[0], 404)

    def test_demo_fixtures_are_isolated_and_include_conflict_and_backups(self):
        demo_path = demo_config(self.root / "demo")
        self.assertTrue(demo_path.is_relative_to(self.root / "demo"))
        with patch("copilot_chat_sync.panel.code_processes", return_value=[]), patch("copilot_chat_sync.cli.code_processes", return_value=[]):
            snapshot = Panel(demo_path, demo=True).snapshot()
        self.assertTrue(snapshot["demo"])
        self.assertEqual(len(snapshot["workspaces"]), 4)
        self.assertEqual(len(snapshot["conflicts"]), 1)
        self.assertEqual(len(snapshot["backups"]), 4)


if __name__ == "__main__":
    unittest.main()