"""Stable-release selection and explicit-base integration, entirely offline."""
import copy
import subprocess
import unittest
from unittest.mock import patch

import test_upstream_sync as fixtures

sync = fixtures.sync


class ReleaseTests(unittest.TestCase):
    setUp = fixtures.SyncTests.setUp
    git = staticmethod(fixtures.SyncTests.git)
    commit = fixtures.SyncTests.commit
    publish = fixtures.SyncTests.publish
    release_api = fixtures.SyncTests.release_api
    upstream_change = fixtures.SyncTests.upstream_change
    candidate = fixtures.SyncTests.candidate

    def test_state_strict_canonical_roundtrip(self):
        raw = "".join(k + "\t" + v + "\n" for k, v in self.initial_state.items()).encode()
        self.assertEqual(sync.parse_release_state(raw), self.initial_state)
        self.assertEqual(sync.release_state_bytes(self.initial_state), raw)
        bad = [raw.replace(b"\n", b"\r\n"), raw[:-1], raw + b"schema\t1\n",
               raw + b"unknown\t1\n", raw.replace(b"schema\t1", b"schema\t2"),
               raw.replace(b"release-base-v1", b"ordinary-merge"),
               raw.replace(b"release_id\t1", b"release_id\t0"),
               raw.replace(b"tag\t1.0.0", b"tag\tv1.0.0"),
               raw.replace(b"2026-01-01", b"2026-02-30"),
               raw.replace(b"fork_base\t", b"fork_base\t\t"),
               b"\n".join(reversed(raw.rstrip(b"\n").split(b"\n"))) + b"\n"]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(sync.Intervention):
                sync.parse_release_state(data)

    def test_prerelease_draft_bare_tag_and_master_do_not_build(self):
        self.commit("upstream", "not stable\n")
        self.publish()
        self.releases[-1]["prerelease"] = True
        self.publish(version="2.0")
        self.releases[-1]["draft"] = True
        self.git(self.writer, "tag", "99.0")
        self.git(self.writer, "push", "upstream", "refs/tags/99.0")
        self.assertEqual(self.worker.prepare()["outcome"], "noop")
        self.releases[-2]["prerelease"] = False
        self.assertEqual(self.worker.prepare()["outcome"], "candidate")

    def test_same_release_ignores_notes_and_fork_edits(self):
        self.releases[0]["body"] = "edited notes"
        self.commit("README.md", "fork notes\n")
        self.git(self.writer, "push", "origin", "master")
        self.worker.refresh()
        self.assertEqual(self.worker.prepare()["outcome"], "noop")

    def test_unpublished_record_is_not_a_stable_release(self):
        self.publish(version="99.0")
        self.releases[-1]["published_at"] = None
        self.assertEqual(self.worker.prepare()["outcome"], "noop")

    def test_protected_modes_are_retained(self):
        self.git(self.writer, "update-index", "--chmod=+x", "README.md")
        self.git(self.writer, "commit", "-m", "Fork executable protected mode")
        self.git(self.writer, "push", "origin", "master")
        self.upstream_change()
        candidate = self.candidate()
        self.assertTrue(self.git(self.repo, "ls-tree", candidate["sha"],
                                 "--", "README.md").startswith("100755 blob "))

    def test_grafted_history_is_refused(self):
        (self.repo / ".git/info/grafts").write_text(self.initial + "\n")
        with self.assertRaisesRegex(sync.Intervention, "Grafted"):
            self.worker.refresh()

    def test_numeric_upgrade_at_same_commit_is_two_parent_candidate(self):
        self.git(self.writer, "checkout", "--detach", self.initial)
        self.publish(version="1.1")
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(result["upstream"], self.initial)
        self.assertEqual(self.git(self.repo, "show", "-s", "--format=%P", result["sha"]),
                         result["base"] + " " + self.initial)
        state = sync.parse_release_state(self.worker.run(
            "show", result["sha"] + ":tools/upstream-release.tsv", binary=True).stdout)
        self.assertEqual(state["version"], "1.1")
        self.assertEqual(state["fork_base"], result["base"])
        self.assertEqual(state["migration_merge"], self.initial)
        self.worker.promote(result["sha"], result["base"], result["upstream"], result["policy"])

    def history_with_reverted_prerelease(self):
        stable = self.initial
        self.commit("runtime/future.c", "future stable code\n")
        prerelease = self.git(self.writer, "rev-parse", "HEAD")
        self.git(self.writer, "push", "upstream", "master")
        # Historical upstream code was integrated then reverted on the fork.
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "revert", "--no-edit", prerelease)
        self.git(self.writer, "push", "origin", "master")
        self.worker.refresh()
        return stable, prerelease

    def test_explicit_base_recovers_reverted_ancestor_release(self):
        _, prerelease = self.history_with_reverted_prerelease()
        self.git(self.writer, "checkout", "--detach", prerelease)
        self.publish(version="1.1")
        result = self.candidate()
        self.assertTrue(self.worker.ancestor(prerelease, result["base"]))
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":runtime/future.c"),
                         "future stable code")

    def test_release_branch_without_reverted_change_does_not_resurrect_it(self):
        stable, _ = self.history_with_reverted_prerelease()
        self.git(self.writer, "checkout", "--detach", stable)
        self.commit("runtime/other.c", "other stable branch\n")
        # Publish a release tag without moving master backwards.
        self.publish(version="1.1")
        result = self.candidate()
        self.assertEqual(self.git(self.repo, "ls-tree", result["sha"], "--", "runtime/future.c"), "")
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":runtime/other.c"),
                         "other stable branch")

    def test_selection_by_publication_then_id_not_version(self):
        self.publish(version="9.0")
        self.publish(version="2.0")
        self.releases[-2]["published_at"] = self.releases[-1]["published_at"]
        self.assertEqual(self.worker.context()["release"]["version"], "2.0")
        self.releases[-1]["tag_name"] = "v2.0"
        with self.assertRaisesRegex(sync.Intervention, "numeric|version|tag"):
            self.worker.prepare()

    def test_tracked_release_withdrawal_and_reclassification_block(self):
        initial = copy.deepcopy(self.releases)
        for mode in ("withdrawn", "prerelease", "draft", "tag", "date"):
            self.releases[:] = copy.deepcopy(initial)
            if mode == "withdrawn":
                self.releases.clear()
            elif mode in ("prerelease", "draft"):
                self.releases[0][mode] = True
            elif mode == "tag":
                self.releases[0]["tag_name"] = "1.0.1"
            else:
                self.releases[0]["published_at"] = "2026-01-02T00:00:00Z"
            with self.subTest(mode=mode), self.assertRaises(sync.Intervention):
                self.worker.prepare()

    def test_invalid_downgrade_equivalent_and_divergent_releases_block(self):
        for version in ("0.9", "1.0.0.0", "v2.0"):
            with self.subTest(version=version):
                self.publish(version=version)
                with self.assertRaises(sync.Intervention):
                    self.worker.prepare()
                self.releases.pop()
        self.git(self.writer, "checkout", "--orphan", "divergent")
        self.git(self.writer, "rm", "-rf", ".")
        self.commit("common", "unrelated\n")
        self.publish(version="3.0")
        with self.assertRaisesRegex(sync.Intervention, "divergen|ancestr"):
            self.worker.prepare()

    def test_annotated_tag_and_isolated_namespace_no_tag_pollution(self):
        self.commit("upstream", "new\n")
        self.publish(annotated=True)
        before = self.git(self.repo, "tag", "--list")
        result = self.worker.prepare()
        self.assertEqual(result["outcome"], "candidate")
        self.assertNotEqual(self.worker.context()["release"]["tag_oid"], result["upstream"])
        self.assertEqual(self.git(self.repo, "tag", "--list"), before)

    def test_tracked_and_newly_observed_tag_retarget_block(self):
        self.worker.context()
        self.upstream_change()
        self.git(self.writer, "tag", "-f", "1.0.0")
        self.git(self.writer, "push", "--force", "upstream", "refs/tags/1.0.0")
        with self.assertRaisesRegex(sync.Intervention, "tag|moved"):
            self.worker.prepare()

    def test_observed_candidate_tag_retarget_blocks(self):
        self.upstream_change()
        self.worker.prepare()
        self.commit("upstream", "retarget\n")
        self.git(self.writer, "tag", "-f", "1.0.1")
        self.git(self.writer, "push", "--force", "upstream", "refs/tags/1.0.1")
        with self.assertRaisesRegex(sync.Intervention, "tag|moved"):
            self.worker.prepare()

    def test_api_failure_never_falls_back(self):
        self.upstream_change()
        with patch.object(sync, "api", side_effect=sync.GitFailure("API unavailable")):
            with self.assertRaises(sync.GitFailure):
                self.worker.prepare()
        self.assertIsNone(self.worker.remote_tip(sync.BRANCH))

    def test_shared_conflict_and_unknown_path_cannot_be_hidden_by_keep(self):
        self.commit("runtime/arm64.c", "fork ARM64\n")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit("runtime/arm64.c", "upstream ARM64\n")
        self.commit("README.md", "upstream protected conflict\n")
        self.publish()
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "arm64"):
            self.worker.prepare()

    def test_worktree_and_index_remain_untouched(self):
        self.upstream_change()
        before = self.git(self.repo, "rev-parse", "HEAD")
        (self.repo / "local").write_text("untracked local\n")
        index = (self.repo / ".git/index").read_bytes()
        self.worker.prepare()
        self.assertEqual(self.git(self.repo, "rev-parse", "HEAD"), before)
        self.assertEqual((self.repo / ".git/index").read_bytes(), index)
        self.assertEqual((self.repo / "local").read_text(), "untracked local\n")

    def test_candidate_tree_tampering_with_bot_identity_rejected(self):
        self.upstream_change()
        result = self.candidate()
        self.git(self.repo, "checkout", "--detach", result["sha"])
        self.git(self.repo, "config", "user.name", sync.BOT_NAME)
        self.git(self.repo, "config", "user.email", sync.BOT_EMAIL)
        for path, contents in (("upstream", "injected\n"),
                               ("tools/upstream-release.tsv", "schema\t1\n"),
                               ("README.md", "tampered protected\n")):
            self.git(self.repo, "reset", "--hard", result["sha"])
            (self.repo / path).write_text(contents)
            self.git(self.repo, "add", path)
            self.git(self.repo, "commit", "--amend", "--no-edit")
            tampered = self.git(self.repo, "rev-parse", "HEAD")
            self.git(self.repo, "push", "--force", "origin", f"HEAD:refs/heads/{sync.BRANCH}")
            with self.subTest(path=path), self.assertRaises(sync.Intervention):
                self.worker.promote(tampered, result["base"], result["upstream"], result["policy"])

    def test_promotion_rechecks_release_and_tag(self):
        self.upstream_change()
        result = self.candidate()
        self.releases[-1]["prerelease"] = True
        with self.assertRaises(sync.Intervention):
            self.worker.promote(result["sha"], result["base"], result["upstream"], result["policy"])
        self.assertEqual(self.worker.remote_tip("master"), result["base"])

    def test_candidate_timestamp_does_not_affect_exact_reuse(self):
        self.upstream_change()
        result = self.candidate()
        with patch.dict("os.environ", {"GIT_COMMITTER_DATE": "2030-01-01T00:00:00Z",
                                       "GIT_AUTHOR_DATE": "2030-01-01T00:00:00Z"}):
            self.assertEqual(self.worker.prepare()["sha"], result["sha"])

    def test_recorded_release_must_be_in_fork_history_even_for_noop(self):
        self.git(self.writer, "checkout", "--orphan", "disconnected")
        self.git(self.writer, "commit", "-m", "Disconnected tree with copied state")
        self.git(self.writer, "push", "--force", "origin", "HEAD:refs/heads/master")
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "ancestor|history"):
            self.worker.prepare()

    def test_candidate_push_rechecks_release_before_external_write(self):
        self.upstream_change()
        result = self.worker.prepare()
        self.releases[-1]["prerelease"] = True
        with self.assertRaises(sync.Intervention):
            self.worker.push_candidate(result["sha"], None)
        self.assertIsNone(self.worker.remote_tip(sync.BRANCH))

    def test_promotion_rechecks_identity_after_tree_calculation(self):
        self.upstream_change()
        result = self.candidate()
        original = self.worker.merge_tree

        def calculate(*args):
            tree = original(*args)
            self.releases[-1]["prerelease"] = True
            return tree

        with patch.object(self.worker, "merge_tree", side_effect=calculate):
            with self.assertRaises(sync.Intervention):
                self.worker.promote(result["sha"], result["base"],
                                    result["upstream"], result["policy"])
        self.assertEqual(self.worker.remote_tip("master"), result["base"])

    def test_candidate_push_advertisement_preserves_ancestor_race(self):
        self.upstream_change()
        result = self.worker.prepare()
        original = self.worker.git

        def race(*args):
            if "push" in args and args[-1].endswith(f":refs/heads/{sync.BRANCH}"):
                self.git(self.writer, "push", "origin",
                         result["base"] + f":refs/heads/{sync.BRANCH}")
            return original(*args)

        with patch.object(self.worker, "git", side_effect=race):
            with self.assertRaises(sync.GitFailure):
                self.worker.push_candidate(result["sha"], None)
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), result["base"])

    def test_merged_human_bot_branch_is_not_cleaned(self):
        base = self.worker.git("rev-parse", "origin/master")
        self.git(self.writer, "push", "origin", base + f":refs/heads/{sync.BRANCH}")
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "human|unrecognized"):
            self.worker.prepare()
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), base)


class ApiTests(unittest.TestCase):
    def test_upstream_pagination_uses_fixed_endpoint_and_flattens(self):
        response = subprocess.CompletedProcess([], 0, '[[{"id":1}],[{"id":2}]]', "")
        with patch.object(sync.subprocess, "run", return_value=response) as run:
            result = sync.api("releases?per_page=100", paginate=True,
                              repository="morerokk/MHGURecomp")
        self.assertEqual(result, [{"id": 1}, {"id": 2}])
        self.assertIn("repos/morerokk/MHGURecomp/releases?per_page=100", run.call_args.args[0])
        self.assertIn("--paginate", run.call_args.args[0])

    def test_failed_or_malformed_pages_block(self):
        for code, body in ((1, ""), (0, "{}"), (0, "[{}]"), (0, "not-json")):
            response = subprocess.CompletedProcess([], code, body, "private transport details")
            with patch.object(sync.subprocess, "run", return_value=response):
                with self.subTest(body=body), self.assertRaises(sync.GitFailure):
                    sync.api("releases?per_page=100", paginate=True,
                             repository="morerokk/MHGURecomp")


if __name__ == "__main__":
    unittest.main()
