import json
import tempfile
import unittest
from pathlib import Path

from copilot_chat_sync.sessions import SyncError, digest, load_session, metadata, native_bytes, normalize, parse_log

SID = "11111111-1111-4111-8111-111111111111"


def sample(message="Initial question"):
    return {
        "version": 3,
        "sessionId": SID,
        "creationDate": 1000,
        "initialLocation": "panel",
        "requests": [{"message": {"text": message}, "timestamp": 2000}],
    }


class SessionTests(unittest.TestCase):
    def test_replays_sets_pushes_truncation_and_deletes(self):
        entries = [
            {"kind": 0, "v": sample()},
            {"kind": 1, "k": ["requests", 0, "message", "text"], "v": "Revised"},
            {"kind": 2, "k": ["requests"], "v": [{"message": "Second"}]},
            {"kind": 2, "k": ["requests"], "i": 1},
            {"kind": 1, "k": ["customTitle"], "v": "Title"},
            {"kind": 3, "k": ["customTitle"]},
            {"kind": 1, "k": ["requests", 0, "timestamp"]},
        ]
        result = parse_log("\n".join(json.dumps(entry) for entry in entries))
        self.assertEqual(len(result["requests"]), 1)
        self.assertEqual(result["requests"][0]["message"]["text"], "Revised")
        self.assertNotIn("customTitle", result)
        self.assertNotIn("timestamp", result["requests"][0])

    def test_corrupt_or_unknown_logs_fail_closed(self):
        initial = json.dumps({"kind": 0, "v": sample()})
        invalid = ["", '{"kind":0', '{"kind":1,"k":["x"],"v":1}',
                   initial + '\n{"kind":99,"k":["x"]}',
                   initial + '\n{"kind":2,"k":["requests"],"i":-1}',
                   initial + '\n{"kind":2,"k":["requests"],"n":1}',
                   initial + '\n{"kind":1,"k":["missing",0],"v":1}',
                   initial + '\n{"kind":1,"k":[],"v":{}}',
                   initial + "\n" + initial]
        for text in invalid:
            with self.subTest(text=text), self.assertRaises(SyncError):
                parse_log(text)

    def test_normalization_excludes_editing_and_execution_state(self):
        data = sample()
        data.update(hasPendingEdits=True, inputState={"permissionLevel": "autopilot"},
                    workingDirectory="/old/project", repoData={"diffs": ["old patch"]},
                    pendingRequests=[{"command": "never replay"}])
        normalized = normalize(data, SID)
        self.assertNotIn("hasPendingEdits", normalized)
        self.assertNotIn("inputState", normalized)
        self.assertNotIn("repoData", normalized)
        self.assertNotIn("pendingRequests", normalized)
        self.assertEqual(normalized["requests"], data["requests"])

    def test_native_json_and_jsonl_roundtrip(self):
        data = normalize(sample("\u4e2d\u6587 question"), SID)
        with tempfile.TemporaryDirectory() as directory:
            for suffix in (".json", ".jsonl"):
                path = Path(directory) / (SID + suffix)
                path.write_bytes(native_bytes(data, suffix))
                self.assertEqual(load_session(path), data)
        self.assertEqual(metadata(data)["title"], "\u4e2d\u6587 question")

    def test_rejects_session_mismatch_and_future_versions(self):
        for change in ({"version": 4}, {"sessionId": "../../escape"}, {"creationDate": float("nan")}):
            with self.subTest(change=change), self.assertRaises(SyncError):
                normalize({**sample(), **change}, SID)

    def test_semantic_hash_ignores_json_formatting(self):
        data = normalize(sample(), SID)
        self.assertEqual(digest(data), digest(json.loads(json.dumps(data, indent=4))))


if __name__ == "__main__":
    unittest.main()