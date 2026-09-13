import contextlib
import io
import json
import os
import sqlite3
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
        with sqlite3.connect(self.storage / WID / "state.vscdb") as connection:
            connection.execute("INSERT INTO ItemTable VALUES (?,?)", ("chat.ChatSessionStore.index", '{"version":2,"entries":{}}'))
        with patch("copilot_chat_sync.cli.code_processes", return_value=[]):
            code, output, errors = self.run_cli("doctor")
        self.assertEqual(code, 2, errors)
        self.assertTrue(any("schema" in issue for issue in json.loads(output)["issues"]))


if __name__ == "__main__":
    unittest.main()