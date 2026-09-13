import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from copilot_chat_sync.safety import code_processes, is_redirect, local_lock, plain_path
from copilot_chat_sync.sessions import SyncError, native_bytes, normalize
from copilot_chat_sync.store import Store
from copilot_chat_sync.sync import migrate
from copilot_chat_sync.workspace import Config
from test_sessions import SID, sample
from test_workspace import URI, WID, make_workspace


class SafetyTests(unittest.TestCase):
    def test_parent_traversal_is_rejected(self):
        root = Path(tempfile.gettempdir()) / "native"
        with self.assertRaisesRegex(SyncError, "Parent traversal"):
            plain_path(root / ".." / "project/code.py", root)

    def test_local_lock_prevents_another_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "local.lock"
            with local_lock(path):
                with self.assertRaisesRegex(SyncError, "Another local sync"):
                    with local_lock(path):
                        self.fail("Second writer acquired the lock")
            with local_lock(path):
                pass

    def test_process_detection_does_not_terminate_processes(self):
        processes = []
        for identifier, name, user, command in (
            (1, "Code.exe", "me", []), (2, "Code Helper (Renderer)", "me", []),
            (3, "node", "me", ["/home/me/.vscode-server/server/node"]),
            (4, "python", "me", []), (5, "Code.exe", "other", []),
        ):
            processes.append(types.SimpleNamespace(pid=identifier, info={"name": name, "username": user, "exe": "", "cmdline": command}))
        fake = types.SimpleNamespace(Process=lambda: types.SimpleNamespace(username=lambda: "me"),
                                     process_iter=lambda attributes: processes, NoSuchProcess=ProcessLookupError, AccessDenied=PermissionError)
        with patch.dict(sys.modules, {"psutil": fake}):
            result = code_processes()
        self.assertEqual(len(result), 3)
        self.assertTrue(any(item.startswith("1:") for item in result))

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture")
    def test_linked_parent_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "code").mkdir()
            (root / "native").mkdir()
            (root / "native/chatSessions").symlink_to(root / "code", target_is_directory=True)
            with self.assertRaisesRegex(SyncError, "redirected storage"):
                plain_path(root / "native/chatSessions/file.jsonl", root / "native")


@unittest.skipUnless(os.name == "nt", "Requires Windows NTFS and PowerShell")
class WindowsTests(unittest.TestCase):
    def test_actual_ntfs_junction_migration_preserves_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = make_workspace(root / "native")
            target = root / "old OneDrive"
            target.mkdir()
            (target / (SID + ".jsonl")).write_bytes(native_bytes(normalize(sample(), SID)))
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(workspace.chats), str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(is_redirect(workspace.chats))
            config = Config(root / "control/config.json", root / "new-shared", root / "native",
                            bindings=[{"id": WID, "uri": URI}])
            Store(config.store).initialize()
            with patch("copilot_chat_sync.sync.require_closed"), patch.dict(os.environ, {"LOCALAPPDATA": str(root / "locks")}):
                migrate(config, apply=True)
            self.assertFalse(is_redirect(workspace.chats))
            self.assertTrue((target / (SID + ".jsonl")).exists())

    def test_powershell_resolves_real_python_and_propagates_failure(self):
        script = Path(__file__).resolve().parents[1] / "scripts/chat-sync.ps1"
        prefix = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), "-PythonExecutable", sys.executable]
        success = subprocess.run([*prefix, "--version"], capture_output=True, text=True)
        self.assertEqual(success.returncode, 0, success.stdout + success.stderr)
        self.assertIn("0.1.0", success.stdout)
        failure = subprocess.run([*prefix, "not-a-command"], capture_output=True, text=True)
        self.assertNotEqual(failure.returncode, 0)

    def test_silent_stub_is_not_reported_as_success(self):
        script = Path(__file__).resolve().parents[1] / "scripts/chat-sync.ps1"
        with tempfile.TemporaryDirectory() as directory:
            stub = Path(directory) / "stub.cmd"
            stub.write_text("@echo off\nexit /b 0\n")
            result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                                     "-PythonExecutable", str(stub), "--version"], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()