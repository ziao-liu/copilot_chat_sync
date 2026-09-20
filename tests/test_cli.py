import contextlib
import io
import json
import os
import runpy
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot_chat_sync.cli import main
from copilot_chat_sync.store import Store
from copilot_chat_sync.workspace import Config
from test_workspace import URI, WID, make_workspace


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local-appdata")})
        environment.start()
        self.addCleanup(environment.stop)
        self.storage = self.root / "native"
        make_workspace(self.storage)
        self.config = self.root / "local/config.json"

    def run_cli(self, *args):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = main(["--config", str(self.config), *args])
        return code, output.getvalue(), errors.getvalue()

    def test_scan_reports_actual_uri(self):
        code, output, errors = self.run_cli("scan", "--storage-root", str(self.storage))
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["workspaces"][0]["uri"], URI)

    def test_desktop_launcher_defaults_to_panel_and_forwards_arguments(self):
        launcher = Path(__file__).resolve().parents[1] / "scripts/desktop.py"
        for arguments in ([], ["--version"], ["panel", "--demo", "--no-browser"]):
            with self.subTest(arguments=arguments):
                with patch.object(sys, "argv", ["CopilotChatSync.exe", *arguments]):
                    with patch("copilot_chat_sync.cli.main", return_value=3) as dispatch:
                        with self.assertRaises(SystemExit) as stopped:
                            runpy.run_path(str(launcher), run_name="__main__")
                dispatch.assert_called_once_with(arguments or ["panel"])
                self.assertEqual(stopped.exception.code, 3)

    def test_bundle_smoke_checks_source_process_in_isolation(self):
        root = Path(__file__).resolve().parents[1]
        smoke = runpy.run_path(str(root / "scripts/smoke_bundle.py"))["smoke"]
        source = f"import sys; sys.path.insert(0, {str(root / 'src')!r}); from copilot_chat_sync.cli import main; raise SystemExit(main())"
        smoke([sys.executable, "-c", source], "0.1.0")

    def test_init_preview_and_explicit_apply(self):
        arguments = ("init", "--store", str(self.root / "cloud"), "--storage-root", str(self.storage))
        code, output, errors = self.run_cli(*arguments)
        self.assertEqual(code, 0, errors)
        self.assertFalse(json.loads(output)["applied"])
        self.assertFalse(self.config.exists())
        with patch("copilot_chat_sync.sync.require_closed"):
            code, _, errors = self.run_cli(*arguments, "--apply")
        self.assertEqual(code, 0, errors)
        self.assertTrue(self.config.exists())
        self.assertEqual(self.run_cli(*arguments, "--apply")[0], 2)

    def test_init_can_include_workspaces_without_a_separate_bind(self):
        store = self.root / "cloud"
        arguments = ("init", "--store", str(store), "--storage-root", str(self.storage), "--workspace", WID)
        code, output, errors = self.run_cli(*arguments)
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["bindings"], [{"id": WID, "uri": URI}])
        self.assertFalse(store.exists())
        self.assertFalse(self.config.exists())
        with patch("copilot_chat_sync.sync.require_closed", side_effect=RuntimeError("guard reached")):
            with self.assertRaisesRegex(RuntimeError, "guard reached"):
                self.run_cli(*arguments, "--apply")
        self.assertFalse(store.exists())
        with patch("copilot_chat_sync.sync.require_closed"):
            code, output, errors = self.run_cli(*arguments, "--apply")
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["bound"], 1)
        self.assertEqual(Config.load(self.config).bindings, [{"id": WID, "uri": URI}])

    def test_init_preview_rejects_old_shared_folder(self):
        store = self.root / "old-cloud"
        store.mkdir()
        old_chat = store / "old-chat.json"
        old_chat.write_text("preserved history", encoding="utf-8")
        code, _, errors = self.run_cli("init", "--store", str(store), "--storage-root", str(self.storage))
        self.assertEqual(code, 2)
        self.assertIn("empty shared folder", errors)
        self.assertFalse(self.config.exists())
        self.assertEqual(old_chat.read_text(encoding="utf-8"), "preserved history")

    def test_bind_decodes_plus_but_keeps_path_case(self):
        config = Config(self.config, self.root / "cloud", self.storage)
        config.save()
        code, output, errors = self.run_cli("bind", "--uri", URI.replace("%2B", "+"))
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["bindings"][0]["id"], WID)
        self.assertEqual(self.run_cli("bind", "--server", "server-proxy", "--path", "/home/alice/PROJECT")[0], 2)

    def test_ambiguous_uri_requires_actual_id(self):
        make_workspace(self.storage, WID + "-1")
        Config(self.config, self.root / "cloud", self.storage).save()
        code, _, errors = self.run_cli("bind", "--uri", URI)
        self.assertEqual(code, 2)
        self.assertIn("found 2", errors)

    def test_missing_config_is_not_silent_success(self):
        code, _, errors = self.run_cli("pull", "--apply")
        self.assertEqual(code, 2)
        self.assertIn("init first", errors)

    def test_doctor_rejects_future_index_schema(self):
        config = Config(self.config, self.root / "cloud", self.storage, bindings=[{"id": WID, "uri": URI}])
        config.save()
        Store(config.store).initialize()
        with contextlib.closing(sqlite3.connect(self.storage / WID / "state.vscdb")) as connection, connection:
            connection.execute("INSERT INTO ItemTable VALUES (?,?)", ("chat.ChatSessionStore.index", '{"version":2,"entries":{}}'))
        with patch("copilot_chat_sync.cli.code_processes", return_value=[]):
            code, output, errors = self.run_cli("doctor")
        self.assertEqual(code, 2, errors)
        self.assertTrue(any("schema" in issue for issue in json.loads(output)["issues"]))


if __name__ == "__main__":
    unittest.main()