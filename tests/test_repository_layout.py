"""Fork-only maintenance layout and public build interface contracts."""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
MAINTENANCE = ROOT / ".github/maintenance"


class RepositoryLayoutTests(unittest.TestCase):
    def test_maintenance_files_have_one_canonical_location(self):
        for name in ("sync-upstream.py", "fork-policy.json",
                     "upstream-release.tsv"):
            with self.subTest(name=name):
                self.assertTrue((MAINTENANCE / name).is_file())
                self.assertFalse((ROOT / "tools" / name).exists())

    def test_canonical_paths_and_retirement_policy(self):
        spec = importlib.util.spec_from_file_location(
            "layout_sync", MAINTENANCE / "sync-upstream.py")
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        self.assertEqual(sync.POLICY, ".github/maintenance/fork-policy.json")
        self.assertEqual(sync.RELEASE_STATE,
                         ".github/maintenance/upstream-release.tsv")
        policy = sync.validate_policy(json.loads(
            (MAINTENANCE / "fork-policy.json").read_text()))
        for name in ("sync-upstream.py", "fork-policy.json",
                     "upstream-release.tsv"):
            self.assertEqual(sync.classify(policy, "tools/" + name), "remove")
            self.assertEqual(sync.classify(
                policy, ".github/maintenance/" + name), "keep")
        self.assertEqual(sync.classify(policy, "tools/vkreplay.c"), "remove")
        self.assertFalse((ROOT / "tools/vkreplay.c").exists())
        self.assertEqual(sync.classify(policy, "tools/vkprobe.c"), "shared")
        self.assertEqual(sync.classify(
            policy, "tests/test_repository_layout.py"), "keep")

    def test_public_interfaces_and_active_auxiliaries_remain(self):
        for path in ("tools/build-linux-release.sh", "tools/upstream-version.sh",
                     "tools/vkprobe.c", "tools/test_lift.py",
                     "tools/test_harness.c", "updater/sha256.c",
                     "updater/updater.h"):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())
        helper = (ROOT / "tools/upstream-version.sh").read_text()
        self.assertIn(
            "state_file=.github/maintenance/upstream-release.tsv", helper)
        self.assertNotIn("state_file=tools/upstream-release.tsv", helper)


if __name__ == "__main__":
    unittest.main()
