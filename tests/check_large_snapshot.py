"""Verify giant FIRST records and giant retained snapshots, using synthetic chats."""

import argparse
import gc
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from check_large_log import peak_rss
from copilot_chat_sync.cli import dispatch, parser
from copilot_chat_sync.index import read_keys
from copilot_chat_sync.sessions import canonical_bytes, file_digest, load_session, native_bytes, normalize
from copilot_chat_sync.store import Store
from copilot_chat_sync.sync import pull, push, restore
from copilot_chat_sync.workspace import Config
from test_sessions import SID, sample
from test_workspace import URI, WID, make_workspace


def write_initial(path: Path, mib: int) -> int:
    before, marker, after = canonical_bytes({"kind": 0, "v": sample("GIANT_FIXTURE_MARKER")}).partition(b'"GIANT_FIXTURE_MARKER"')
    assert marker
    with path.open("wb") as stream:
        stream.write(before + b'"')
        chunk = b"x" * (1024 * 1024)
        for _ in range(mib):
            stream.write(chunk)
        stream.write(b'"' + after + b"\n")
        return stream.tell()


def assert_chat(path: Path, expected_size: int | None) -> None:
    data = load_session(path)
    text = data["requests"][0]["message"]["text"]
    if expected_size is None:
        assert text == "Final A"
    else:
        assert len(text) == expected_size and text.count("x") == expected_size, "Giant message was altered"
    assert data["sessionId"] == SID and len(data["requests"]) == 1


def check(mib: int, shrink: bool) -> None:
    if not 128 < mib < 1024:
        raise ValueError("Use a first-record size greater than 128 MiB and less than 1 GiB")
    started = time.monotonic()
    with peak_rss() as memory, tempfile.TemporaryDirectory(prefix="chat-sync-giant-first-") as temporary:
        root = Path(temporary)
        shared = root / "shared"
        Store(shared).initialize()
        workspaces = [make_workspace(root / name / "native") for name in ("a", "b")]
        configs = [Config(root / name / "control/config.json", shared, workspace.directory.parent,
                          bindings=[{"id": WID, "uri": URI}]) for name, workspace in zip(("a", "b"), workspaces)]
        for config in configs:
            config.save()
        workspaces[0].chats.mkdir()
        source = workspaces[0].chats / (SID + ".jsonl")
        first_size = write_initial(source, mib)
        expected_size = None if shrink else mib * 1024 * 1024
        if shrink:
            with source.open("ab") as stream:
                stream.write(canonical_bytes({"kind": 1, "k": ["requests", 0, "message", "text"], "v": "Final A"}) + b"\n")
        original_hash = file_digest(source)
        original_index = read_keys(workspaces[0].database)
        assert_chat(source, expected_size)
        with patch("copilot_chat_sync.sync.require_closed"), patch.dict(os.environ, {"LOCALAPPDATA": str(root / "locks")}):
            assert push(configs[0])["would_publish"] == 1
            assert push(configs[0], apply=True)["published"] == 1
            assert file_digest(source) == original_hash, "Send modified the original file"
            revision = Store(shared).load().chosen(SID)
            assert revision.path.stat().st_size > 128 * 1024 * 1024 if not shrink else revision.path.stat().st_size < 1024 * 1024
            assert push(configs[0], apply=True)["published"] == 0
            assert pull(configs[1], apply=True)["files"] == 1
            target = workspaces[1].chats / source.name
            assert_chat(target, expected_size)
            if not shrink:
                assert target.stat().st_size > 128 * 1024 * 1024
            output = root / (SID + ".json")
            arguments = parser().parse_args(["--config", str(configs[1].path), "export-revision", SID,
                                              "--output", str(output), "--apply"])
            assert dispatch(arguments)["applied"]
            assert_chat(output, expected_size)
            target.write_bytes(native_bytes(normalize(sample("Continued B"), SID)))
            assert push(configs[1], apply=True)["published"] == 1
            result = pull(configs[0], apply=True)
            backup = configs[0].backups / result["backup"] / "files" / WID / "chatSessions" / source.name
            assert file_digest(backup) == original_hash, "Backup lost original bytes"
            assert load_session(source)["requests"][0]["message"]["text"] == "Continued B"
            restore(configs[0], result["backup"], apply=True)
            assert file_digest(source) == original_hash
            assert read_keys(workspaces[0].database) == original_index
            assert_chat(source, expected_size)
        gc.collect()
        peak_mib = memory[0] / (1024 * 1024)
        ceiling = max(768, mib * 3 + 128)
        assert peak_mib < ceiling, f"Avoidable giant snapshot copies: sampled peak RSS {peak_mib:.1f} MiB >= {ceiling}"
        print(f"Giant-FIRST check passed: first record {first_size} bytes (> {mib} MiB), shrink={shrink}, "
              f"send/receive/re-send/export/checksum/raw backup/restore, peak RSS {peak_mib:.1f} MiB, "
              f"{time.monotonic() - started:.1f}s", flush=True)


if __name__ == "__main__":
    options = argparse.ArgumentParser()
    options.add_argument("--mib", type=int, default=129)
    options.add_argument("--shrink", action="store_true")
    args = options.parse_args()
    check(args.mib, args.shrink)
