"""Public harness regressions; subprocess fixtures contain no game data."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_runner():
    spec = importlib.util.spec_from_file_location(
        "crossplay_runner", ROOT / "tools/test-crossplay.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CrossplayRunnerTests(unittest.TestCase):
    def test_network_isolation_is_required_without_an_escape_hatch(self):
        module = load_runner()
        with patch.object(module.socket, "if_nameindex",
                          return_value=[(1, "lo"), (2, "eth0")]):
            with self.assertRaisesRegex(RuntimeError, "isolated"):
                module.require_isolated_network()
        with patch.object(module.socket, "if_nameindex",
                          return_value=[(1, "lo")]):
            module.require_isolated_network()

    def test_a_failed_child_is_not_hidden_by_printing_its_log(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            with module.Harness(Path(tmp), []) as harness:
                child = harness.start(
                    "failure", [sys.executable, "-c", "raise SystemExit(7)"],
                    target=False)
                with self.assertRaisesRegex(RuntimeError, "exit 7"):
                    harness.finish(child)

    def test_zero_exit_with_a_failure_marker_is_still_a_failure(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            with module.Harness(Path(tmp), []) as harness:
                child = harness.start(
                    "false-success",
                    [sys.executable, "-c", "print('[test] FAIL: fixture')"],
                    target=False)
                with self.assertRaisesRegex(RuntimeError, "FAIL"):
                    harness.finish(child)

    def test_positive_client_requires_its_final_assertion(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            with module.Harness(Path(tmp), []) as harness:
                child = harness.start(
                    "incomplete", [sys.executable, "-c", "print('started')"],
                    target=False)
                with self.assertRaisesRegex(RuntimeError, "missing"):
                    harness.finish(child, "finished every assertion")

    def test_ready_server_that_dies_is_rejected(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            with module.Harness(Path(tmp), []) as harness:
                child = harness.start(
                    "early-exit",
                    [sys.executable, "-c", "print('ready', flush=True)"],
                    target=False)
                child.process.wait(timeout=5)
                with self.assertRaisesRegex(RuntimeError, "exited"):
                    harness.wait_for(child, "ready")

    def test_watchdog_reaps_a_hung_child(self):
        module = load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            with module.Harness(Path(tmp), []) as harness:
                child = harness.start(
                    "hung", [sys.executable, "-c",
                             "import time; time.sleep(60)"], target=False)
                with self.assertRaises((RuntimeError, subprocess.TimeoutExpired)):
                    harness.finish(child, timeout=0.1)
            self.assertIsNotNone(child.process.poll())
            self.assertTrue(child.output.closed)

    def test_runner_prefix_is_argv_not_shell_code(self):
        module = load_runner()
        self.assertEqual(
            module.target_command(
                ["qemu-aarch64", "-L", "/a root"], "/binary", ["host", "127.0.0.1:1"]),
            ["qemu-aarch64", "-L", "/a root", "/binary", "host", "127.0.0.1:1"])

    def test_network_fixture_builds_keep_arm64_and_elf_checks(self):
        text = (ROOT / "Makefile").read_text()
        for token in ("test-crossplay:", "tests/test_room.c",
                      "tests/test_ryuldn.c", "tests/test_xbridge.c",
                      "tests/emu_room.c", "tests/ryusrv_main.cpp",
                      'tools/test-crossplay.py', '"$(TEST_RUNNER)"'):
            self.assertIn(token, text)
        script = (ROOT / "tools/docker/build.sh").read_text()
        for name in ("test-room", "test-ryuldn", "test-xbridge",
                     "emu-room", "ryusrv-main"):
            self.assertIn("/work/obj-aarch64/crossplay-test/" + name, script)


if __name__ == "__main__":
    unittest.main()
