"""Real-size handoff check; synthetic data only, with no permanent chat storage."""

import argparse
import os
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from copilot_chat_sync.index import read_keys
from copilot_chat_sync.sessions import canonical_bytes, file_digest, load_session, native_bytes, normalize
from copilot_chat_sync.store import Store
from copilot_chat_sync.sync import migrate, pull, push, restore
from copilot_chat_sync.workspace import Config
from test_sessions import SID, sample
from test_workspace import URI, WID, make_workspace


@contextmanager
def peak_rss():
    process = psutil.Process()
    peak = [process.memory_info().rss]
    stop = threading.Event()

    def sample_memory():
        while not stop.wait(0.02):
            peak[0] = max(peak[0], process.memory_info().rss)

    monitor = threading.Thread(target=sample_memory, daemon=True)
    monitor.start()
    try:
        yield peak
    finally:
        stop.set()
        monitor.join()


def check(mib: int) -> None:
    if not 128 < mib < 8192:
        raise ValueError("Use a log size greater than 128 MiB and less than 8 GiB")
    started = time.monotonic()
    with peak_rss() as memory, tempfile.TemporaryDirectory(prefix="chat-sync-large-log-") as temporary:
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
        mutation = canonical_bytes({"kind": 1, "k": ["requests", 0, "message", "text"], "v": "x" * (1024 * 1024)}) + b"\n"
        with source.open("wb") as stream:
            stream.write(native_bytes(normalize(sample(), SID)))
            while stream.tell() <= mib * 1024 * 1024:
                stream.write(mutation)
            stream.write(canonical_bytes({"kind": 1, "k": ["requests", 0, "message", "text"], "v": "Final A"}) + b"\n")
        del mutation
        size = source.stat().st_size
        original_hash = file_digest(source)
        original_index = read_keys(workspaces[0].database)
        with patch("copilot_chat_sync.sync.require_closed"), patch.dict(os.environ, {"LOCALAPPDATA": str(root / "locks")}):
            assert push(configs[0])["would_publish"] == 1
            assert push(configs[0], apply=True)["published"] == 1
            revision = Store(shared).load().chosen(SID)
            assert revision.session["requests"][0]["message"]["text"] == "Final A"
            assert revision.path.stat().st_size < 1024 * 1024
            assert file_digest(source) == original_hash, "Send must not rewrite the source log"
            assert pull(configs[1], apply=True)["files"] == 1
            target = workspaces[1].chats / (SID + ".jsonl")
            target.write_bytes(native_bytes(normalize(sample("Continued B"), SID)))
            assert push(configs[1], apply=True)["published"] == 1
            result = pull(configs[0], apply=True)
            backup = configs[0].backups / result["backup"] / "files" / WID / "chatSessions" / source.name
            assert backup.stat().st_size == size
            assert file_digest(backup) == original_hash, "Full raw log must survive the backup"
            assert load_session(source)["requests"][0]["message"]["text"] == "Continued B"
            restore(configs[0], result["backup"], apply=True)
            assert file_digest(source) == original_hash
            assert read_keys(workspaces[0].database) == original_index
            assert load_session(source)["requests"][0]["message"]["text"] == "Final A"
            if os.name != "nt":
                legacy = root / "legacy"
                workspaces[0].chats.rename(legacy)
                workspaces[0].chats.symlink_to(legacy, target_is_directory=True)
                migration = migrate(configs[0], apply=True)
                assert not workspaces[0].chats.is_symlink()
                assert file_digest(source) == original_hash
                assert file_digest(legacy / source.name) == original_hash
                restore(configs[0], migration["backup"], apply=True)
                assert file_digest(source) == original_hash
        peak_mib = memory[0] / (1024 * 1024)
        assert peak_mib < 256, f"Whole-log buffering regression: sampled peak RSS {peak_mib:.1f} MiB"
        print(f"Large-log check passed: {size} bytes (> {mib} MiB), send/receive, raw backup/restore, migration, sampled peak RSS {peak_mib:.1f} MiB, {time.monotonic() - started:.1f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mib", type=int, default=513)
    check(parser.parse_args().mib)
