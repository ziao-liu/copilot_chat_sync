import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot_chat_sync.index import INDEX, read_keys
from copilot_chat_sync.sessions import SyncError, load_session, native_bytes, normalize
from copilot_chat_sync.store import Store
from copilot_chat_sync.sync import migrate, pull, push, repair, resolve, restore
from copilot_chat_sync.workspace import Config
from test_sessions import SID, sample
from test_workspace import URI, WID, make_workspace


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local-appdata")})
        environment.start()
        self.addCleanup(environment.stop)
        self.shared = self.root / "onedrive"
        Store(self.shared).initialize()
        self.configs = []
        self.workspaces = []
        for name in ("pc-a", "pc-b"):
            workspace = make_workspace(self.root / name / "storage")
            config = Config(self.root / name / "control/config.json", self.shared, workspace.directory.parent,
                            bindings=[{"id": WID, "uri": URI}])
            config.save()
            self.configs.append(config)
            self.workspaces.append(workspace)
        self.guard = patch("copilot_chat_sync.sync.require_closed")
        self.closed = self.guard.start()
        self.addCleanup(self.guard.stop)
        self.write(0, "original")
        self.code = self.root / "project/train.py"
        self.code.parent.mkdir()
        self.code.write_text("original project code\n")

    def write(self, computer, text):
        workspace = self.workspaces[computer]
        workspace.chats.mkdir(exist_ok=True)
        (workspace.chats / (SID + ".jsonl")).write_bytes(native_bytes(normalize(sample(text), SID)))

    def text(self, computer):
        return load_session(self.workspaces[computer].chats / (SID + ".jsonl"))["requests"][0]["message"]["text"]

    def seed_both(self):
        push(self.configs[0], apply=True)
        pull(self.configs[1], apply=True)

    def test_first_sync_continuation_and_index(self):
        self.seed_both()
        self.write(1, "continued on B")
        push(self.configs[1], apply=True)
        result = pull(self.configs[0], apply=True)
        self.assertEqual(result["files"], 1)
        self.assertEqual(self.text(0), "continued on B")
        self.assertIn(SID, json.loads(read_keys(self.workspaces[0].database)[INDEX])["entries"])
        self.assertEqual(self.code.read_text(), "original project code\n")

    def test_dry_run_does_not_touch_native_or_shared_data(self):
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        result = push(self.configs[0])
        self.assertEqual(result["would_publish"], 1)
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")))
        self.closed.assert_not_called()

    def test_dirty_destination_blocks_every_write(self):
        self.seed_both()
        self.write(1, "unpublished B")
        self.write(0, "published A")
        push(self.configs[0], apply=True)
        before = read_keys(self.workspaces[1].database)
        with self.assertRaisesRegex(SyncError, "Unpublished local changes"):
            pull(self.configs[1], apply=True)
        self.assertEqual(self.text(1), "unpublished B")
        self.assertEqual(read_keys(self.workspaces[1].database), before)

    def test_divergence_is_preserved_then_explicitly_resolved(self):
        self.seed_both()
        self.write(0, "branch A")
        self.write(1, "branch B")
        push(self.configs[0], apply=True)
        preview = push(self.configs[1])
        self.assertIn(SID, preview["conflicts"])
        result = push(self.configs[1], apply=True)
        self.assertIn(SID, result["conflicts"])
        with self.assertRaisesRegex(SyncError, "Divergent"):
            pull(self.configs[0], apply=True)
        store = Store(self.shared).load()
        choice = next(head for head in store.heads(SID) if head.session["requests"][0]["message"]["text"] == "branch B")
        resolve(self.configs[0], SID, choice.revision, apply=True)
        pull(self.configs[0], apply=True)
        self.assertEqual(self.text(0), "branch B")
        self.assertEqual(len(Store(self.shared).load().graphs[SID]), 4)

    def test_edit_snapshots_block_pull_unless_quarantined(self):
        push(self.configs[0], apply=True)
        editing = self.workspaces[1].directory / "chatEditingSessions" / SID
        editing.mkdir(parents=True)
        (editing / "state.json").write_text('{"entries":[{"state":0,"current":"stale code"}]}')
        with self.assertRaisesRegex(SyncError, "Editing snapshots"):
            pull(self.configs[1], apply=True)
        self.assertTrue(editing.exists())
        result = pull(self.configs[1], apply=True, detach=True)
        self.assertFalse(editing.exists())
        self.assertTrue((self.workspaces[1].directory / ".chat-sync-quarantine" / result["backup"] / SID / "state.json").exists())
        self.assertEqual(self.code.read_text(), "original project code\n")
        restore(self.configs[1], result["backup"], apply=True)
        self.assertFalse(editing.exists())

    def test_restore_import_and_preserve_unrelated_database_changes(self):
        push(self.configs[0], apply=True)
        before = read_keys(self.workspaces[1].database)
        result = pull(self.configs[1], apply=True)
        with sqlite3.connect(self.workspaces[1].database) as connection:
            connection.execute("UPDATE ItemTable SET value='new unrelated value' WHERE key='unrelated.extension'")
        restore(self.configs[1], result["backup"], apply=True)
        self.assertEqual(read_keys(self.workspaces[1].database), before)
        self.assertFalse((self.workspaces[1].chats / (SID + ".jsonl")).exists())
        with sqlite3.connect(self.workspaces[1].database) as connection:
            self.assertEqual(connection.execute("SELECT value FROM ItemTable WHERE key='unrelated.extension'").fetchone()[0], "new unrelated value")

    def test_restore_refuses_newer_edits(self):
        push(self.configs[0], apply=True)
        result = pull(self.configs[1], apply=True)
        self.write(1, "newer edits")
        with self.assertRaisesRegex(SyncError, "Newer local changes"):
            restore(self.configs[1], result["backup"], apply=True)
        self.assertEqual(self.text(1), "newer edits")

    def test_failure_rolls_back_native_files_and_index(self):
        push(self.configs[0], apply=True)
        before = read_keys(self.workspaces[1].database)
        from copilot_chat_sync.index import write_keys
        calls = []

        def fail_once(*args):
            calls.append(True)
            if len(calls) == 1:
                raise OSError("simulated disk failure")
            return write_keys(*args)

        with patch("copilot_chat_sync.transaction.write_keys", side_effect=fail_once), self.assertRaisesRegex(SyncError, "rolled back"):
            pull(self.configs[1], apply=True)
        self.assertEqual(read_keys(self.workspaces[1].database), before)
        self.assertFalse((self.workspaces[1].chats / (SID + ".jsonl")).exists())

    def test_running_vscode_blocks_apply(self):
        self.closed.side_effect = SyncError("Close all VS Code windows")
        with self.assertRaisesRegex(SyncError, "Close all"):
            push(self.configs[0], apply=True)
        self.assertFalse((self.shared / "revisions").exists())

    @unittest.skipIf(os.name == "nt", "Windows junction integration is covered separately")
    def test_migration_detaches_old_link_without_deleting_shared_history(self):
        linked = self.root / "old-onedrive"
        self.workspaces[0].chats.rename(linked)
        self.workspaces[0].chats.symlink_to(linked, target_is_directory=True)
        with self.assertRaisesRegex(SyncError, "redirected storage"):
            push(self.configs[0], apply=True)
        result = migrate(self.configs[0], apply=True)
        self.assertFalse(self.workspaces[0].chats.is_symlink())
        self.assertEqual(self.text(0), "original")
        self.assertTrue((linked / (SID + ".jsonl")).exists())
        self.assertTrue(Path(result["workspaces"][0]["retained_link"]).is_symlink())

    def test_repair_preview_and_apply(self):
        before = read_keys(self.workspaces[0].database)
        self.assertEqual(repair(self.configs[0])["indexes"], 1)
        self.assertEqual(read_keys(self.workspaces[0].database), before)
        repair(self.configs[0], apply=True)
        self.assertIn(SID, json.loads(read_keys(self.workspaces[0].database)[INDEX])["entries"])

    @unittest.skipIf(os.name == "nt", "Symlink fixture; Windows junction covered separately")
    def test_interrupted_migration_has_explicit_recovery(self):
        from copilot_chat_sync.transaction import list_backups
        original = self.root / "old-shared"
        self.workspaces[0].chats.rename(original)
        self.workspaces[0].chats.symlink_to(original, target_is_directory=True)
        original_rename = Path.rename

        def fail_staging(path, target):
            if "chatSessions.staging-" in path.name:
                raise OSError("simulated interruption")
            return original_rename(path, target)

        with patch.object(Path, "rename", fail_staging), self.assertRaisesRegex(SyncError, "Migration interrupted"):
            migrate(self.configs[0], apply=True)
        backup = list_backups(self.configs[0])[0]
        self.assertEqual(backup["status"], "prepared")
        with self.assertRaisesRegex(SyncError, "interrupted operation"):
            push(self.configs[0], apply=True)
        restore(self.configs[0], backup["id"], apply=True)
        self.assertFalse(self.workspaces[0].chats.is_symlink())
        self.assertEqual(self.text(0), "original")
        self.assertTrue((original / (SID + ".jsonl")).exists())


if __name__ == "__main__":
    unittest.main()