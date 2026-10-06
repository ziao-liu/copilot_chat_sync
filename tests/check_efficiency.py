"""Compare identical multi-chat handoffs; all data is synthetic and temporary."""

import argparse
import gc
import json
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from check_large_log import peak_rss
from copilot_chat_sync import __version__
from copilot_chat_sync import sessions
from copilot_chat_sync.store import Store
from copilot_chat_sync.sync import pull, push
from copilot_chat_sync.workspace import Config
from test_workspace import URI, WID, make_workspace


def check(count=4, mib=65):
    results = {"version": __version__, "chats": count, "mib_per_chat": mib, "operations": {}}
    with tempfile.TemporaryDirectory(prefix="chat-sync-efficiency-") as temporary:
        root = Path(temporary)
        Store(root / "shared").initialize()
        workspaces = [make_workspace(root / name / "native") for name in ("a", "b")]
        configs = [Config(root / name / "control/config.json", root / "shared", workspace.directory.parent,
                          bindings=[{"id": WID, "uri": URI}]) for name, workspace in zip(("a", "b"), workspaces)]
        for config in configs:
            config.save()
        workspaces[0].chats.mkdir()
        identifiers = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"efficiency-fixture-{index}")) for index in range(count)]
        chunk = b"x" * (1024 * 1024)
        for identifier in identifiers:
            with (workspaces[0].chats / (identifier + ".jsonl")).open("wb") as stream:
                stream.write(('{"kind":0,"v":{"version":3,"sessionId":"' + identifier +
                              '","creationDate":1000,"initialLocation":"panel","requests":[{"message":"').encode())
                for _ in range(mib):
                    stream.write(chunk)
                stream.write(b'"}]}}\n')

        original = sessions._read_json

        def measure(name, operation):
            gc.collect()
            started = time.monotonic()
            parsed_bytes = 0
            parses = 0

            def read(reader, *args, **kwargs):
                nonlocal parses, parsed_bytes
                value = original(reader, *args, **kwargs)
                parses += 1
                parsed_bytes += reader.count
                return value

            with peak_rss() as memory, patch.object(sessions, "_read_json", side_effect=read):
                result = operation()
            results["operations"][name] = {"seconds": round(time.monotonic() - started, 3),
                                           "peak_rss_mib": round(memory[0] / 2**20, 1),
                                           "json_parses": parses, "parsed_mib": round(parsed_bytes / 2**20, 1),
                                           "result": result}
            print(name, results["operations"][name], flush=True)

        with patch("copilot_chat_sync.sync.require_closed"), patch.dict(os.environ, {"LOCALAPPDATA": str(root / "locks")}):
            measure("send_preview", lambda: push(configs[0]))
            measure("send_apply", lambda: push(configs[0], apply=True))
            measure("receive_preview", lambda: pull(configs[1]))
            measure("receive_apply", lambda: pull(configs[1], apply=True))
            measure("unchanged_receive", lambda: pull(configs[1], apply=True))
            path = workspaces[0].chats / (identifiers[0] + ".jsonl")
            with path.open("ab") as stream:
                stream.write(b'{"kind":1,"k":["customTitle"],"v":"Changed title"}\n')
            measure("one_changed_send", lambda: push(configs[0], apply=True))
            measure("one_changed_receive", lambda: pull(configs[1], apply=True))
            assert results["operations"]["receive_apply"]["result"]["files"] == count
            assert results["operations"]["unchanged_receive"]["result"]["files"] == 0
            assert results["operations"]["one_changed_receive"]["result"]["files"] == 1
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--mib", type=int, default=65)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--assert-optimized", action="store_true")
    options = parser.parse_args()
    result = check(options.count, options.mib)
    if options.assert_optimized:
        operations = result["operations"]
        assert operations["unchanged_receive"]["json_parses"] == 0
        assert operations["one_changed_receive"]["json_parses"] <= 2
        assert operations["one_changed_send"]["json_parses"] <= 2
        assert max(value["peak_rss_mib"] for value in operations.values()) < options.mib * 3 + 160
    if options.report:
        options.report.write_text(json.dumps(result, indent=2) + "\n")
