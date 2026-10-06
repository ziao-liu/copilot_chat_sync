import tempfile
import unittest
from pathlib import Path

from copilot_chat_sync.progress import Progress, current, file_checked, report, steps
from copilot_chat_sync.sessions import canonical_bytes, file_chunks, load_session
from test_sessions import SID, sample


class ProgressTests(unittest.TestCase):
    def test_nested_work_units_do_not_reset_between_files_or_reach_100_early(self):
        progress = Progress()
        values = []
        with progress.track("overall"):
            with steps(3) as phase_done:
                phase_done()
                values.append(progress.snapshot("overall")["overall"])
                with steps(2) as file_done:
                    report("读取第一个文件", "one", 100, 100)
                    self.assertEqual(progress.snapshot("overall")["overall"], values[-1])
                    file_done()
                    values.append(progress.snapshot("overall")["overall"])
                    report("读取第二个文件", "two", 0, 100)
                    self.assertEqual(progress.snapshot("overall")["overall"], values[-1])
                    file_done()
                    values.append(progress.snapshot("overall")["overall"])
                phase_done()
                phase_done()
            self.assertLess(progress.snapshot("overall")["overall"], 1)
        self.assertEqual(values, sorted(values))
        self.assertAlmostEqual(values[0], 1 / 3)
        self.assertAlmostEqual(values[1], 1 / 2)
        self.assertAlmostEqual(values[2], 2 / 3)
        self.assertEqual(progress.snapshot("overall")["overall"], 1)
        self.assertTrue(progress.snapshot("overall")["finished"])
        self.assertEqual(progress.steps, [])

    def test_failure_retains_partial_overall_and_cleans_nested_context(self):
        progress = Progress()
        with self.assertRaisesRegex(RuntimeError, "check failed"):
            with progress.track("failed"):
                with steps(2) as phase_done:
                    phase_done()
                    with steps(2) as file_done:
                        file_done()
                        raise RuntimeError("check failed")
        data = progress.snapshot("failed")
        self.assertFalse(data["active"])
        self.assertFalse(data["finished"])
        self.assertEqual(data["overall"], .75)
        self.assertEqual(progress.steps, [])
        self.assertIsNone(current.get())

    def test_empty_steps_and_disabled_cli_reporting(self):
        with steps(0) as advance:
            advance()
        progress = Progress()
        with progress.track("empty"):
            with steps(0):
                pass
            self.assertLess(progress.snapshot("empty")["overall"], 1)
        self.assertEqual(progress.snapshot("empty")["overall"], 1)
        with self.assertRaisesRegex(ValueError, "non-negative"):
            with steps(-1):
                pass

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
