"""Real Git fixtures: no network, credentials, game data or GitHub writes."""
import importlib.util
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / ".github/maintenance/sync-upstream.py"
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
        self.commit(".github/maintenance/fork-policy.json", json.dumps({
            "version": 1,
            "keep": {"files": ["README.md"], "prefixes": [".github/"]},
            "remove": {"files": ["runtime/platform/android.c"], "prefixes": ["android/"]},
            "shared": {"files": ["common", "fork", "upstream", "human"], "prefixes": ["runtime/"]},
        }))
        self.git(self.writer, "remote", "add", "origin", str(self.origin))
        self.git(self.writer, "remote", "add", "upstream", str(self.upstream))
        self.releases = []
        tracked = self.publish()
        self.initial = tracked
        self.initial_state = {
            "schema": "1", "algorithm": "release-base-v1", "repository": "morerokk/MHGURecomp",
            "release_id": "1", "version": "1.0.0", "tag": "1.0.0",
            "tag_oid": tracked, "commit": tracked, "published_at": "2026-01-01T00:00:00Z",
            "fork_base": tracked, "migration_merge": tracked, "migration_source": tracked,
        }
        self.commit(".github/maintenance/upstream-release.tsv", "".join(
            key + "\t" + value + "\n" for key, value in self.initial_state.items()))
        self.git(self.writer, "push", "origin", "master")
        self.git(self.root, "clone", str(self.origin), str(self.repo))
        self.git(self.repo, "remote", "add", "upstream", str(self.upstream))
        api_mock = patch.object(sync, "api", side_effect=self.release_api)
        api_mock.start()
        self.addCleanup(api_mock.stop)
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

    def release_api(self, path, **kwargs):
        if path == "releases?per_page=100":
            self.assertEqual(kwargs.get("repository"), "morerokk/MHGURecomp")
            self.assertTrue(kwargs.get("paginate"))
            return copy.deepcopy(self.releases)
        self.fail("Unexpected network/API request: " + path)

    def publish(self, version=None, annotated=False):
        number = len(self.releases) + 1
        version = version or f"1.0.{number - 1}"
        sha = self.git(self.writer, "rev-parse", "HEAD")
        if annotated:
            self.git(self.writer, "tag", "-a", version, "-m", "Stable release")
        else:
            self.git(self.writer, "tag", version)
        self.git(self.writer, "push", "upstream", "master", f"refs/tags/{version}")
        self.releases.append({"id": number, "tag_name": version, "draft": False,
                              "prerelease": False, "published_at": f"2026-01-{number:02d}T00:00:00Z",
                              "body": "Release notes", "target_commitish": "untrusted-moving-branch"})
        return sha

    def upstream_change(self):
        sha = self.commit("upstream", "new\n")
        self.publish()
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

    def test_master_advance_preserves_and_blocks_stale_candidate(self):
        self.upstream_change()
        first = self.candidate()
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit("fork", "later fork\n")
        self.git(self.writer, "push", "origin", "master")
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "stale|context"):
            self.worker.prepare()
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), first["sha"])

    def test_upstream_advance_preserves_and_blocks_stale_candidate(self):
        self.upstream_change()
        first = self.candidate()
        self.commit("upstream", "next\n")
        self.publish()
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "stale|context"):
            self.worker.prepare()
        self.assertEqual(self.worker.remote_tip(sync.BRANCH), first["sha"])

    def test_conflict_does_not_publish_or_resolve(self):
        self.commit("common", "fork\n")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit("common", "upstream\n")
        self.publish()
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
        self.worker.context()
        self.git(self.repo, "checkout", "--detach", "origin/master")
        self.git(self.repo, "-c", "user.name=Human", "-c", "user.email=human@example.test",
                 "merge", "--no-ff", "-m", sync.MARKER + " Stable release 1.0.1",
                 self.git(self.writer, "rev-parse", "HEAD"))
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
        self.publish()
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":README.md"),
                         "fork documentation")
        self.assertEqual(self.git(self.repo, "ls-tree", "-r", "--name-only",
                                  result["sha"], ".github/workflows"), "")
        self.assertEqual(
            self.git(self.repo, "show",
                     result["sha"] + ":.github/maintenance/fork-policy.json"),
            self.git(self.repo, "show",
                     result["base"] + ":.github/maintenance/fork-policy.json"))

    def test_removed_prefix_cannot_resurrect_new_files(self):
        self.commit("android/new/evil.c", "never resurrect\n")
        self.publish()
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.git(self.repo, "ls-tree", "-r", "--name-only",
                                  result["sha"], "android"), "")

    def test_real_fork_policy_never_reintroduces_personal_build_files(self):
        policy = json.loads((SCRIPT.parent / "fork-policy.json").read_text())
        if ".github/maintenance/upstream-release.tsv" not in policy["keep"]["files"]:
            policy["keep"]["files"].append(".github/maintenance/upstream-release.tsv")
        policy["shared"]["files"] += ["common", "fork", "upstream", "human"]
        self.commit(".github/maintenance/fork-policy.json", json.dumps(policy))
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        retired = ("update-build-arm64.sh", "tests/test_update_build.py",
                   "run-debug.bat", "run-game.bat", "tools/sync-upstream.py",
                   "tools/fork-policy.json", "tools/upstream-release.tsv",
                   "tools/vkreplay.c")
        for path in retired:
            self.commit(path, "upstream attempts to add a retired personal entry\n")
        self.publish()
        self.worker.refresh()
        candidate = self.candidate()
        for path in retired:
            with self.subTest(path=path):
                self.assertEqual(sync.classify(policy, path), "remove")
                self.assertEqual(self.git(self.repo, "ls-tree", candidate["sha"],
                                          "--", path), "")
                self.assertIn(path, candidate["omitted"])

    def test_trusted_policy_not_upstream_policy(self):
        self.commit(".github/maintenance/fork-policy.json", '{"version":999,"keep":{}}')
        self.commit(".github/new.yml", "untrusted")
        self.publish()
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.worker.policy_digest(result["base"]), result["policy"])
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":.github/maintenance/fork-policy.json"),
                         self.git(self.repo, "show", result["base"] + ":.github/maintenance/fork-policy.json"))

    def test_unknown_new_path_blocks(self):
        self.commit("new-unclassified/code.c", "review first")
        self.publish()
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "Unclassified"):
            self.worker.prepare()
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())

    def test_real_policy_imports_reviewed_example_but_blocks_sibling(self):
        policy = json.loads((SCRIPT.parent / "fork-policy.json").read_text())
        policy["shared"]["files"] += ["common", "fork", "upstream", "human"]
        self.commit(sync.POLICY, json.dumps(policy))
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        path = "extras/example-engine-module/example_engine_module.c"
        self.commit(path, "/* public loader test fixture */\n")
        self.publish()
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":" + path),
                         "/* public loader test fixture */")
        self.worker.promote(result["sha"], result["base"], result["upstream"],
                            result["policy"])
        self.commit("extras/example-engine-module/unreviewed.c", "review first")
        self.publish()
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "Unclassified"):
            self.worker.prepare()

    def test_unknown_new_bat_still_requires_policy_review(self):
        self.commit("new-launcher.bat", "unreviewed platform entry point\n")
        self.publish()
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "Unclassified"):
            self.worker.prepare()
        self.assertFalse((self.repo / ".git/MERGE_HEAD").exists())

    def test_root_readme_translations_removed_without_changing_fork_readme(self):
        self.commit("README.md", "fork-owned documentation\n")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        translations = ("README.es.md", "README.pt-BR.md", "README.zh_Hant.md",
                        "README.fil.md")
        for path in translations:
            self.commit(path, "upstream translation\n")
        self.commit("README.md", "upstream documentation\n")
        self.publish()
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":README.md"),
                         "fork-owned documentation")
        for path in translations:
            with self.subTest(path=path):
                self.assertEqual(self.git(self.repo, "ls-tree", result["sha"], "--", path), "")
                self.assertIn(path, result["omitted"])
        self.worker.promote(result["sha"], result["base"], result["upstream"], result["policy"])

    def test_explicit_fork_translation_protection_precedes_locale_rule(self):
        policy = json.loads((self.writer / sync.POLICY).read_text())
        policy["keep"]["files"].append("README.es.md")
        self.commit(sync.POLICY, json.dumps(policy))
        self.commit("README.es.md", "fork-owned Spanish documentation\n")
        self.git(self.writer, "update-index", "--chmod=+x", "README.es.md")
        self.git(self.writer, "commit", "-m", "Retain fork-owned executable mode")
        base = self.git(self.writer, "rev-parse", "HEAD")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", self.initial)
        self.commit("README.es.md", "upstream Spanish documentation\n")
        self.publish()
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(sync.classify(policy, "README.es.md"), "keep")
        self.assertEqual(self.git(self.repo, "ls-tree", result["sha"], "--", "README.es.md"),
                         self.git(self.writer, "ls-tree", base, "--", "README.es.md"))

    def test_nested_readme_translation_is_not_automatically_classified(self):
        self.commit("translations/README.es.md", "not a trusted root translation\n")
        self.publish()
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "Unclassified"):
            self.worker.prepare()

    def test_readme_translation_shaped_directory_cannot_hide_code(self):
        self.commit("README.es.md/injected.c", "unreviewed code\n")
        self.publish()
        self.worker.refresh()
        with self.assertRaisesRegex(sync.Intervention, "Unclassified"):
            self.worker.prepare()

    def test_real_fork_policy_retains_only_shared_linux_icon(self):
        policy = json.loads((SCRIPT.parent / "fork-policy.json").read_text())
        policy["shared"]["files"] += ["common", "fork", "upstream", "human"]
        self.commit(sync.POLICY, json.dumps(policy))
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        shared = "extras/icon/mhgurecomp-128.png"
        retired = ("extras/icon/mhgurecomp.ico", "extras/icon/mhgurecomp.rc",
                   "extras/icon/mhgurecomp-updater-128.png",
                   "extras/icon/mhgurecomp-updater.ico", "extras/icon/mhgurecomp-updater.rc")
        for path in (shared, *retired):
            self.commit(path, "upstream icon fixture\n")
        self.publish()
        self.worker.refresh()
        result = self.candidate()
        self.assertEqual(self.git(self.repo, "show", result["sha"] + ":" + shared),
                         "upstream icon fixture")
        for path in retired:
            with self.subTest(path=path):
                self.assertEqual(self.git(self.repo, "ls-tree", result["sha"], "--", path), "")
                self.assertIn(path, result["omitted"])

    def test_real_fork_policy_preserves_public_source_tools_and_protected_tests(self):
        policy = json.loads((SCRIPT.parent / "fork-policy.json").read_text())
        policy["shared"]["files"] += ["common", "fork", "upstream", "human"]
        self.commit(sync.POLICY, json.dumps(policy))
        protected = ("tools/build-linux-release.sh", "tools/upstream-version.sh",
                     "tools/publish-linux-release.py", "tests/test_release_publish.py",
                     "tests/test_arm64_runtime.py", "tests/test_arm64_abi.c")
        for path in protected:
            self.commit(path, "fork-owned source fixture\n")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", self.initial)
        for path in protected:
            self.commit(path, "upstream must not replace trusted fork source\n")
        self.publish()
        self.worker.refresh()
        result = self.candidate()
        for path in protected:
            with self.subTest(path=path):
                self.assertEqual(self.git(self.repo, "show", result["sha"] + ":" + path),
                                 "fork-owned source fixture")
        self.worker.promote(result["sha"], result["base"], result["upstream"], result["policy"])

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
        self.publish()
        self.worker.refresh()
        candidate = self.candidate()
        self.assertEqual(self.git(self.repo, "ls-tree", candidate["sha"],
                                  "--", "runtime/platform/android.c"), "")

    def test_protected_both_modified_preserves_fork(self):
        self.commit("README.md", "fork")
        self.git(self.writer, "push", "origin", "master")
        self.git(self.writer, "reset", "--hard", "HEAD~1")
        self.commit("README.md", "upstream")
        self.publish()
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
        self.publish()
        self.worker.refresh()
        candidate = self.candidate()
        self.assertEqual(self.git(self.repo, "show",
                                  candidate["sha"] + ":.github/workflows/keep.yml"), "fork")


if __name__ == "__main__":
    unittest.main()
