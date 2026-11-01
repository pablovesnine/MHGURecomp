"""Real Git fixtures: no network, credentials, game data or GitHub writes."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

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
        self.commit("README.md", "original\n")
        self.commit("runtime/platform/android.c", "old Android\n")
        self.commit("tools/fork-policy.json", json.dumps({
            "version": 1,
            "keep": {"files": ["README.md", "tools/fork-policy.json"], "prefixes": [".github/"]},
            "remove": {"files": ["runtime/platform/android.c"], "prefixes": ["android/"]},
            "shared": {"files": ["common", "fork", "upstream", "human"], "prefixes": ["runtime/"]},
        }))
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
        (self.writer / file).parent.mkdir(parents=True, exist_ok=True)
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

    def test_keep_modify_delete_and_new_workflow(self):
        self.commit("README.md", "fork documentation\n")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.git(self.writer, "rm", "README.md")
        self.git(self.writer, "commit", "-m", "delete upstream readme")
        self.commit(".github/workflows/new.yml", "untrusted workflow")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":README.md"),
                         "fork documentation")
        self.assertEqual(self.git(self.repo, "ls-tree", "-r", "--name-only",
                                  result["sha"], ".github"), "")

    def test_removed_prefix_cannot_resurrect_new_files(self):
        self.commit("android/new/evil.c", "never resurrect\n")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.git(self.repo, "ls-tree", "-r", "--name-only",
                                  result["sha"], "android"), "")

    def test_trusted_policy_not_upstream_policy(self):
        self.commit("tools/fork-policy.json", '{"version":999,"keep":{}}')
        self.commit(".github/new.yml", "untrusted")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.worker.policy_digest(result["base"]), result["policy"])
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":tools/fork-policy.json"),
                         self.git(self.repo, "show", result["base"] + ":tools/fork-policy.json"))

    def test_unknown_new_path_blocks(self):
        self.commit("new-unclassified/code.c", "review first")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "Unclassified"):
            self.worker.prepare()
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())

    def test_promote_exact_validated_candidate(self):
        self.upstream_change()
        result = self.candidate()
        self.worker.promote(result["sha"], result["base"], result["upstream"], result["policy"])
        self.assertEqual(self.worker.remote_tip("master"), result["sha"])
        self.assertIsNone(self.worker.remote_tip(sync.BRANCH))

    def test_promote_refuses_master_advancement(self):
        self.upstream_change()
        result = self.candidate()
        self.git(self.writer, "reset", "--hard", result["base"])
        master = self.commit("fork", "new master")
        self.git(self.writer, "push", "origin", "master")
        with self.assertRaisesRegex(sync.Intervention, "master"):
            self.worker.promote(result["sha"], result["base"], result["upstream"], result["policy"])
        self.assertEqual(self.worker.remote_tip("master"), master)

    def test_promote_refuses_branch_race(self):
        self.upstream_change()
        result = self.candidate()
        self.git(self.writer, "fetch", "origin", sync.BRANCH)
        self.git(self.writer, "checkout", "--detach", "FETCH_HEAD")
        human = self.commit("human", "do not promote")
        self.git(self.writer, "push", "origin", f"{human}:refs/heads/{sync.BRANCH}")
        with self.assertRaisesRegex(sync.Intervention, "branch"):
            self.worker.promote(result["sha"], result["base"], result["upstream"], result["policy"])
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), human)

    def test_malformed_policy_cannot_escape_repository(self):
        for path in ("../outside", "/absolute", ".git/config", "a/../b", "a\\b", "a//b"):
            with self.subTest(path=path), self.assertRaises(sync.Intervention):
                sync.validate_policy({"version": 1, "keep": {"files": [path], "prefixes": []},
                                      "remove": {"files": [], "prefixes": []},
                                      "shared": {"files": [], "prefixes": []}})

    def test_modify_delete_removed_path_resolves_without_resurrection(self):
        self.git(self.writer, "rm", "runtime/platform/android.c")
        self.git(self.writer, "commit", "-m", "fork retires Android")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit("runtime/platform/android.c", "upstream modified Android")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        candidate = self.candidate()
        self.assertEqual(self.git(self.repo, "ls-tree", candidate["sha"],
                                  "--", "runtime/platform/android.c"), "")

    def test_protected_both_modified_preserves_fork(self):
        self.commit("README.md", "fork")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit("README.md", "upstream")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        candidate = self.candidate()
        self.assertEqual(self.git(self.repo, "show", candidate["sha"] + ":README.md"), "fork")

    def test_promote_rejects_policy_hash_mismatch(self):
        self.upstream_change()
        candidate = self.candidate()
        with self.assertRaisesRegex(sync.Intervention, "policy"):
            self.worker.promote(candidate["sha"], candidate["base"],
                                candidate["upstream"], "0" * 64)
        self.assertEqual(self.worker.remote_tip("master"), candidate["base"])

    def test_prepush_advertisement_closes_ancestor_race(self):
        self.upstream_change()
        candidate = self.candidate()
        original = self.worker.git
        raced = []

        def race(*args):
            if "push" in args and args[-1].endswith(":refs/heads/master"):
                self.git(self.writer, "push", "origin", "HEAD:refs/heads/master")
                raced.append(True)
            return original(*args)

        with patch.object(self.worker, "git", side_effect=race):
            with self.assertRaises(sync.GitFailure):
                self.worker.promote(candidate["sha"], candidate["base"],
                                    candidate["upstream"], candidate["policy"])
        self.assertEqual(raced, [True])
        self.assertEqual(self.worker.remote_tip("master"), candidate["upstream"])
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), candidate["sha"])

    def test_pathspec_metacharacter_does_not_remove_other_protected_files(self):
        self.commit(".github/workflows/keep.yml", "fork")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit(".github/workflows/*.yml", "malicious pathspec")
        self.git(self.writer, "push", "upstream", "master")
        self.worker.refresh()
        candidate = self.candidate()
        self.assertEqual(self.git(self.repo, "show",
                                  candidate["sha"] + ":.github/workflows/keep.yml"), "fork")


if __name__ == "__main__":
    unittest.main()
