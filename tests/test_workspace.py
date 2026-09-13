import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot_chat_sync.index import INDEX, KEYS, MODEL_CACHE, STATE_CACHE, merge_keys, read_keys, write_keys
from copilot_chat_sync.sessions import SyncError, native_bytes, normalize
from copilot_chat_sync.workspace import Config, Workspace, default_storage, discover
from test_sessions import SID, sample

WID = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
URI = "vscode-remote://ssh-remote%2Bserver-proxy/home/alice/project"


def make_workspace(storage, identifier=WID, uri=URI):
    directory = storage / identifier
    directory.mkdir(parents=True)
    (directory / "workspace.json").write_text(json.dumps({"folder": uri}))
    with sqlite3.connect(directory / "state.vscdb") as connection:
        connection.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value BLOB)")
        connection.execute("INSERT INTO ItemTable VALUES ('unrelated.extension', 'preserve me')")
    return Workspace.open(storage, identifier)


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.storage = self.root / "storage"
        self.workspace = make_workspace(self.storage)

    def test_discovery_uses_real_metadata_and_suffix_ids(self):
        make_workspace(self.storage, WID + "-1", "vscode-remote://ssh-remote+npu-server/home/alice/PROJECT")
        workspaces, errors = discover(self.storage)
        self.assertEqual(len(workspaces), 2)
        self.assertFalse(errors)
        self.assertIn(URI, [workspace.uri for workspace in workspaces])

    def test_configuration_guards_uri_identity(self):
        config = Config(self.root / "local/config.json", self.root / "shared", self.storage,
                        bindings=[{"id": WID, "uri": URI}])
        config.save()
        self.assertEqual(Config.load(config.path).workspaces()[0], self.workspace)
        (self.workspace.directory / "workspace.json").write_text(json.dumps({"folder": "file:///other"}))
        with self.assertRaisesRegex(SyncError, "URI changed"):
            config.workspaces()

    def test_config_state_cannot_live_in_shared_store(self):
        config = Config(self.root / "shared/config.json", self.root / "shared", self.storage)
        with self.assertRaisesRegex(SyncError, "non-nested"):
            config.save()

    def test_windows_storage_uses_actual_appdata(self):
        with patch("copilot_chat_sync.workspace.sys.platform", "win32"), patch.dict("os.environ", {"APPDATA": str(self.root / "custom")}):
            self.assertEqual(default_storage(), self.root / "custom/Code/User/workspaceStorage")

    def test_local_state_cannot_be_synced_through_another_onedrive_folder(self):
        config = Config(self.root / "onedrive/configs/config.json", self.root / "onedrive/shared", self.storage)
        with patch.dict("os.environ", {"OneDrive": str(self.root / "onedrive")}):
            with self.assertRaisesRegex(SyncError, "must not be stored in OneDrive"):
                config.validate()

    def test_jsonl_preferred_when_both_native_formats_exist(self):
        self.workspace.chats.mkdir()
        for suffix, text in ((".json", "old"), (".jsonl", "new")):
            (self.workspace.chats / (SID + suffix)).write_bytes(native_bytes(normalize(sample(text), SID), suffix))
        self.assertEqual(self.workspace.sessions()[SID]["requests"][0]["message"]["text"], "new")

    def test_index_updates_only_chat_keys_and_preserves_archiving(self):
        before = read_keys(self.workspace.database)
        after = merge_keys(before, {SID: normalize(sample(), SID)})
        write_keys(self.workspace.database, before, after)
        with sqlite3.connect(self.workspace.database) as connection:
            self.assertEqual(connection.execute("SELECT value FROM ItemTable WHERE key='unrelated.extension'").fetchone()[0], "preserve me")
        state = json.loads(after[STATE_CACHE])
        state[0]["archived"] = True
        after[STATE_CACHE] = json.dumps(state)
        changed = merge_keys(after, {SID: normalize(sample("Updated"), SID)})
        self.assertTrue(json.loads(changed[STATE_CACHE])[0]["archived"])
        self.assertEqual(json.loads(changed[MODEL_CACHE])[0]["label"], "Updated")
        self.assertEqual(json.loads(changed[INDEX])["entries"][SID]["lastResponseState"], 1)

    def test_future_index_schemas_and_concurrent_writers_are_rejected(self):
        before = read_keys(self.workspace.database)
        with self.assertRaisesRegex(SyncError, "schema"):
            merge_keys({**before, INDEX: '{"version":2,"entries":{}}'}, {})
        after = merge_keys(before, {SID: normalize(sample(), SID)})
        write_keys(self.workspace.database, before, after)
        with self.assertRaisesRegex(SyncError, "changed after preflight"):
            write_keys(self.workspace.database, before, after)

    def test_nonlocal_cache_entries_and_empty_chats(self):
        before = {key: None for key in KEYS}
        before[MODEL_CACHE] = '[{"resource":"copilotcli:/keep","label":"CLI"}]'
        data = normalize({**sample(), "requests": []}, SID)
        after = merge_keys(before, {SID: data})
        self.assertEqual(json.loads(after[MODEL_CACHE]), [{"resource": "copilotcli:/keep", "label": "CLI"}])
        self.assertTrue(json.loads(after[INDEX])["entries"][SID]["isEmpty"])


if __name__ == "__main__":
    unittest.main()