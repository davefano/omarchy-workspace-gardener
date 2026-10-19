"""Opt-in Quickshell integration: GARDENER_LIVE_TESTS=1 python3 -m unittest test_service."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import time
import unittest


@unittest.skipUnless(os.environ.get("GARDENER_LIVE_TESTS") == "1", "requires a live Hyprland session and Quickshell")
class LockStatusTests(unittest.TestCase):
    def test_public_lock_status_controls_cleanup_without_direct_service_access(self):
        source = Path(__file__).resolve().parent
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("Service.qml", "Model.js", "gardener.py"):
                (root / name).symlink_to(source / name)
            (root / "shell.qml").write_text('import Quickshell\nShellRoot { Service {} }\n')
            control = root / "lock-state"
            control.write_text("false\n")
            binary = root / "bin"
            binary.mkdir()
            for name in ("python3", "hyprctl", "cat"):
                (binary / name).symlink_to(shutil.which(name))
            command = binary / "omarchy-shell"
            command.write_text(
                '#!/bin/sh\n[ "$1 $2" = "lock isLocked" ] || exit 2\n'
                f'value=$(cat {shlex.quote(str(control))})\n'
                'case "$value" in true|false) echo "$value";; *) exit 1;; esac\n'
            )
            command.chmod(0o755)
            env = dict(os.environ, PATH=str(binary), XDG_STATE_HOME=str(root / "state"))
            qs = shutil.which("qs")
            self.assertIsNotNone(qs)
            config = str(root / "shell.qml")
            with (root / "shell.log").open("w+") as log:
                process = subprocess.Popen([qs, "-p", config], env=env, stdout=log, stderr=log)
                try:
                    def ipc(method, *args):
                        result = subprocess.run([qs, "ipc", "-n", "-p", config, "call", "--", "gardener", method, *args], env=env, capture_output=True, text=True, timeout=3)
                        return result.stdout.strip()

                    def await_lock(known, locked):
                        deadline = time.monotonic() + 8
                        observed = None
                        while time.monotonic() < deadline:
                            self.assertIsNone(process.poll(), "Quickshell exited; inspect harness log")
                            try:
                                observed = json.loads(ipc("status"))
                                if observed.get("ready") and observed.get("lockStatusKnown") is known and observed.get("locked") is locked:
                                    return observed
                            except ValueError:
                                pass
                            time.sleep(0.1)
                        self.fail(f"Expected known={known}, locked={locked}; observed {observed}")

                    await_lock(True, False)
                    self.assertIn("state", json.loads(ipc("freeze", "test")))
                    self.assertEqual(ipc("cancel", "test"), "ok")
                    command.chmod(0o644)
                    await_lock(False, True)
                    self.assertIn("Could not read", json.loads(ipc("freeze", "test"))["error"])
                    command.chmod(0o755)
                    await_lock(True, False)
                    control.write_text("true\n")
                    self.assertFalse(await_lock(True, True)["counting"])
                    self.assertIn("locked", json.loads(ipc("freeze", "test"))["error"])
                    control.write_text("error\n")
                    unavailable = await_lock(False, True)
                    self.assertFalse(unavailable["counting"])
                    self.assertIn("Could not read", unavailable["error"])
                    self.assertIn("Could not read", json.loads(ipc("freeze", "test"))["error"])
                    control.write_text("false\n")
                    self.assertEqual(await_lock(True, False)["error"], "")
                    self.assertIn("state", json.loads(ipc("freeze", "test")))
                    self.assertEqual(ipc("cancel", "test"), "ok")
                finally:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
