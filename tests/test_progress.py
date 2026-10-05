import tempfile
import unittest
from pathlib import Path

from copilot_chat_sync.progress import Progress, current, file_checked
from copilot_chat_sync.sessions import canonical_bytes, file_chunks, load_session
from test_sessions import SID, sample


class ProgressTests(unittest.TestCase):
    def test_actual_byte_counts_and_context_cleanup(self):
        progress = Progress()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / (SID + ".jsonl")
            path.write_bytes(canonical_bytes({"kind": 0, "v": sample()}) + b"\n")
            with progress.track("1"):
                self.assertEqual(load_session(path)["sessionId"], SID)
                self.assertEqual(list(file_chunks(path)), [path.read_bytes()])
                file_checked()
                data = progress.snapshot("1")
                self.assertEqual(data["done"], path.stat().st_size)
                self.assertEqual(data["total"], data["done"])
                self.assertEqual(data["files"], 1)
            self.assertIsNone(current.get())
            self.assertFalse(progress.snapshot("1")["active"])
            with progress.track("2"):
                self.assertEqual(progress.snapshot("1"), {})
                self.assertEqual(progress.snapshot("2")["files"], 0)
