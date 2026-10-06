import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot_chat_sync.cache import cache_scope, current
from copilot_chat_sync.sessions import SyncError, normalize
from copilot_chat_sync.store import Store
from test_sessions import SID, sample
from test_store import WRITER


class CacheTests(unittest.TestCase):
    def test_cached_store_checks_all_bytes_even_if_size_and_mtime_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "shared")
            store.initialize()
            revision = store.publish(normalize(sample("original"), SID), [], WRITER)
            path = store.root / "revisions" / SID / (revision.revision + ".json")
            with cache_scope(root / "cache.sqlite"):
                loaded = Store(store.root).load()
                with patch("copilot_chat_sync.store.load_json", side_effect=AssertionError("Reparsed unchanged history")):
                    self.assertEqual(Store(store.root).load().chosen(SID).revision, revision.revision)
                stat = path.stat()
                path.write_bytes(path.read_bytes().replace(b"original", b"modified"))
                os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                with self.assertRaisesRegex(SyncError, "checksum"):
                    Store(store.root).load()
                with self.assertRaisesRegex(SyncError, "changed after scanning"):
                    _ = loaded.chosen(SID).session

    def test_validation_never_caches_unsupported_session_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root / "shared")
            store.initialize()
            with cache_scope(root / "cache.sqlite"):
                store.publish(normalize(sample(), SID), [], WRITER)
                cache = current.get()
                cache.connection.execute("UPDATE verified_v2 SET data='{}'")
                cache.connection.commit()
                with self.assertRaisesRegex(SyncError, "cache checksum mismatch"):
                    Store(store.root).load()

    def test_read_only_preview_cache_does_not_create_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cache.sqlite"
            with cache_scope(path, persist=False):
                self.assertFalse(path.exists())
            self.assertFalse(path.exists())

    def test_normalization_keeps_default_copy_semantics(self):
        original = sample()
        result = normalize(original, SID)
        result["requests"][0]["message"]["text"] = "changed"
        self.assertNotEqual(original["requests"], result["requests"])
