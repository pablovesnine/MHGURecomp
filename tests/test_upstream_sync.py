"""Real Git fixtures: no network, credentials, game data or GitHub writes."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/sync-upstream.py"
SPEC = importlib.util.spec_from_file_location("upstream_sync", SCRIPT)
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.origin = self.root / "fork.git"
        self.upstream = self.root / "upstream.git"
        self.writer = self.root / "writer"
        self.repo = self.root / "runner"
        for remote in (self.origin, self.upstream):
            self.git(self.root, "init", "--bare", "--initial-branch=master", str(remote))
        self.git(self.root, "init", "--initial-branch=master", str(self.writer))
        self.git(self.writer, "config", "user.name", "Human")
        self.git(self.writer, "config", "user.email", "human@example.test")
        self.commit("common", "base\n")
        self.git(self.writer, "remote", "add", "origin", str(self.origin))
        self.git(self.writer, "remote", "add", "upstream", str(self.upstream))
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "push", "upstream", "master")
        self.git(self.root, "clone", str(self.origin), str(self.repo))
        self.git(self.repo, "remote", "add", "upstream", str(self.upstream))
        self.worker = sync.SyncGit(self.repo)
        self.worker.refresh()

    @staticmethod
    def git(repo, *args):
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.strip()

    def commit(self, file, contents):
        (self.writer / file).write_text(contents)
        self.git(self.writer, "add", file)
        self.git(self.writer, "commit", "-m", "Human change " + file)
        return self.git(self.writer, "rev-parse", "HEAD")

    def upstream_change(self):
        sha = self.commit("upstream", "new\n")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        return sha

    def candidate(self):
        result = self.worker.prepare()
        self.worker.push_candidate(result["sha"], result["previous"])
        self.worker.refresh()
        return result

    def test_noop_has_no_bot_branch(self):
        self.assertEqual(self.worker.prepare()["outcome"], "noop")
        self.assertEqual(self.git(self.origin, "branch", "--list", sync.BRANCH), "")

    def test_clean_merge_preserves_both_ancestries(self):
        self.commit("fork", "fork only\n")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        upstream = self.upstream_change()
        result = self.candidate()
        self.assertTrue(self.worker.ancestor(upstream, result["sha"]))
        self.assertTrue(self.worker.ancestor("origin/master", result["sha"]))
        self.assertEqual(len(self.git(self.repo, "rev-list", "--parents", "-n", "1", result["sha"]).split()), 3)

    def test_repeat_reuses_exact_candidate(self):
        self.upstream_change()
        first = self.candidate()
        second = self.worker.prepare()
        self.assertEqual(first["sha"], second["sha"])
        self.assertFalse(second["changed"])

    def test_master_advance_extends_candidate_without_reset(self):
        self.upstream_change()
        first = self.candidate()
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit("fork", "later fork\n")
        self.git(self.writer, "push", "origin", "master")
        self.worker.refresh()
        second = self.candidate()
        self.assertNotEqual(first["sha"], second["sha"])
        self.assertTrue(self.worker.ancestor(first["sha"], second["sha"]))
        self.assertTrue(self.worker.ancestor("origin/master", second["sha"]))

    def test_upstream_advance_extends_candidate(self):
        self.upstream_change()
        first = self.candidate()
        self.commit("upstream", "next\n")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        second = self.candidate()
        self.assertTrue(self.worker.ancestor(first["sha"], second["sha"]))
        self.assertTrue(self.worker.ancestor("upstream/master", second["sha"]))

    def test_conflict_does_not_publish_or_resolve(self):
        self.commit("common", "fork\n")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit("common", "upstream\n")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "common"):
            self.worker.prepare()
        self.assertEqual(self.git(self.origin, "branch", "--list", sync.BRANCH), "")
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())

    def test_human_branch_commits_are_preserved_and_rejected(self):
        self.upstream_change()
        first = self.candidate()
        self.git(self.writer, "fetch", "origin", sync.BRANCH)
        self.git(self.writer, "checkout", "--detach", "FETCH_HEAD")
        human = self.commit("human", "do not discard\n")
        self.git(self.writer, "push", "origin", f"HEAD:refs/heads/{sync.BRANCH}")
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "human|unrecognized"):
            self.worker.prepare()
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), human)
        self.assertNotEqual(first["sha"], human)

    def test_marker_without_bot_identity_is_rejected(self):
        self.upstream_change()
        self.git(self.repo, "checkout", "--detach", "origin/master")
        self.git(self.repo, "-c", "user.name=Human", "-c", "user.email=human@example.test",
                 "merge", "--no-ff", "-m", sync.MARKER + " Merge upstream master", "upstream/master")
        self.git(self.repo, "push", "origin", f"HEAD:refs/heads/{sync.BRANCH}")
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "unrecognized"):
            self.worker.prepare()

    def test_delete_requires_tip_ancestor_of_master(self):
        self.upstream_change()
        result = self.candidate()
        with self.assertRaises(sync.Intervention):
            self.worker.delete_merged(sync.BRANCH, result["sha"])
        self.git(self.repo, "push", "origin", f'{result["sha"]}:refs/heads/master')
        self.worker.refresh()
        self.worker.delete_merged(sync.BRANCH, result["sha"])
        self.assertIsNone(self.worker.remote_tip(sync.BRANCH))

    def test_delete_lease_rejects_remote_race(self):
        base = self.git(self.repo, "rev-parse", "origin/master")
        self.git(self.repo, "push", "origin", f"{base}:refs/heads/{sync.BRANCH}")
        newer = self.commit("human", "raced\n")
        self.git(self.writer, "push", "origin", f"{newer}:refs/heads/{sync.BRANCH}")
        with self.assertRaises(sync.Intervention):
            self.worker.delete_merged(sync.BRANCH, base)
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), newer)

    def test_push_does_not_overwrite_human_race(self):
        self.upstream_change()
        candidate = self.worker.prepare()
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        human = self.commit("human", "raced\n")
        self.git(self.writer, "push", "origin", f"{human}:refs/heads/{sync.BRANCH}")
        with self.assertRaises(sync.Intervention):
            self.worker.push_candidate(candidate["sha"], candidate["previous"])
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), human)

    def test_cleanup_after_merge_is_no_build(self):
        self.upstream_change()
        candidate = self.candidate()
        self.git(self.repo, "push", "origin", f'{candidate["sha"]}:refs/heads/master')
        self.worker.refresh()
        self.assertEqual(self.worker.prepare()["outcome"], "cleaned")
        self.assertIsNone(self.worker.remote_tip(sync.BRANCH))


if __name__ == "__main__":
    unittest.main()
