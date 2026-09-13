import json
import tempfile
import unittest
from pathlib import Path

from copilot_chat_sync.sessions import SyncError, normalize
from copilot_chat_sync.store import Store
from test_sessions import SID, sample

WRITER = "22222222-2222-4222-8222-222222222222"


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "shared"
        self.store = Store(self.root)
        self.store.initialize()
        self.store.load()

    def publish(self, text, parents=()):
        return self.store.publish(normalize(sample(text), SID), list(parents), WRITER)

    def test_sequential_updates_have_one_head(self):
        first = self.publish("first")
        second = self.publish("second", [first.revision])
        self.assertEqual(Store(self.root).load().chosen(SID).revision, second.revision)
        self.assertEqual(len(self.store.graphs[SID]), 2)

    def test_offline_branches_are_preserved_and_block_pull(self):
        first = self.publish("first")
        left = self.publish("PC A", [first.revision])
        right = self.publish("PC B", [first.revision])
        reloaded = Store(self.root).load()
        self.assertEqual({item.revision for item in reloaded.heads(SID)}, {left.revision, right.revision})
        with self.assertRaisesRegex(SyncError, "Divergent history"):
            reloaded.chosen(SID)
        self.assertEqual(len(reloaded.graphs[SID]), 3)

    def test_resolution_preserves_both_previous_branches(self):
        first = self.publish("first")
        left = self.publish("PC A", [first.revision])
        right = self.publish("PC B", [first.revision])
        resolved = self.publish("PC B", [left.revision, right.revision])
        self.assertEqual(self.store.chosen(SID).revision, resolved.revision)
        self.assertEqual(len(self.store.graphs[SID]), 4)

    def test_missing_parent_blocks_incomplete_download(self):
        first = self.publish("first")
        self.publish("second", [first.revision])
        (self.root / "revisions" / SID / (first.revision + ".json")).unlink()
        with self.assertRaisesRegex(SyncError, "Incomplete OneDrive"):
            Store(self.root).load()

    def test_checksum_and_onedrive_conflict_names_fail_closed(self):
        revision = self.publish("first")
        path = self.root / "revisions" / SID / (revision.revision + ".json")
        envelope = json.loads(path.read_text())
        envelope["session"]["creationDate"] = 42
        path.write_text(json.dumps(envelope))
        with self.assertRaisesRegex(SyncError, "checksum"):
            Store(self.root).load()
        path.rename(path.with_name(revision.revision + "-PC2.json"))
        with self.assertRaisesRegex(SyncError, "conflict copy"):
            Store(self.root).load()

    def test_repeated_publish_is_idempotent(self):
        first = self.publish("same")
        second = self.publish("same")
        self.assertEqual(first.revision, second.revision)
        self.assertEqual(len(list((self.root / "revisions" / SID).iterdir())), 1)

    def test_old_payloads_are_lazy_and_rechecked_on_use(self):
        revision = self.publish("large historical payload")
        loaded = Store(self.root).load().chosen(SID)
        self.assertIsNone(loaded.data)
        path = self.root / "revisions" / SID / (revision.revision + ".json")
        path.write_text("{}")
        with self.assertRaisesRegex(SyncError, "changed after scanning"):
            _ = loaded.session

    def test_legacy_folder_is_not_mistaken_for_versioned_store(self):
        legacy = Path(self.temporary.name) / "legacy"
        legacy.mkdir()
        (legacy / (SID + ".jsonl")).write_text("not a revision")
        with self.assertRaisesRegex(SyncError, "empty shared folder"):
            Store(legacy).initialize()


if __name__ == "__main__":
    unittest.main()