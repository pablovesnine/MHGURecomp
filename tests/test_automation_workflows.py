"""Workflow trust boundaries and issue/status state; offline stdlib tests."""
from argparse import Namespace
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("sync_maintenance", ROOT / "tools/sync-upstream.py")
sync = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sync)


def job(text, name):
    match = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z_]+:\n|\Z)", text, re.M | re.S)
    if match is None:
        raise AssertionError("Missing job " + name)
    return match.group(1)


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.builder = (ROOT / ".github/workflows/linux-builder.yml").read_text()
        cls.ci = (ROOT / ".github/workflows/linux-ci.yml").read_text()
        cls.sync = (ROOT / ".github/workflows/upstream-sync.yml").read_text()
        cls.publisher = (ROOT / ".github/workflows/linux-publisher.yml").read_text()

    def test_external_actions_immutable(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            for action in re.findall(r"^\s*(?:-\s*)?uses:\s+([^\s#]+)", path.read_text(), re.M):
                if not action.startswith("./"):
                    self.assertRegex(action, r"^[\w/-]+@[0-9a-f]{40}$")

    def test_validator_readonly_and_same_image_for_candidate(self):
        self.assertIn("workflow_call:", self.builder)
        self.assertNotIn("write", re.sub(r"#.*", "", self.builder))
        self.assertNotIn("secrets:", self.builder)
        self.assertIn("persist-credentials: false", self.builder)
        self.assertIn("ref: ${{ inputs.candidate_ref || github.sha }}", self.builder)
        self.assertIn('[[ "$sha" == "$expected" ]]', self.builder)
        self.assertIn("retention-days: 1", self.builder)
        self.assertNotIn("if: steps.source.outputs.publish", self.builder)
        self.assertNotIn("pull_request_target", self.builder + self.ci + self.sync)
        self.assertNotIn("update-build-arm64.sh", self.builder)

    def test_mandatory_lint_runtime_qemu(self):
        for text in ("runs-on: ubuntu-24.04", "timeout-minutes: 60",
                     "--check --version 0 --jobs 2", "shellcheck tools/build-linux-release.sh",
                     "actionlint", "unittest discover", "platforms: linux/amd64",
                     "SOURCE_REVISION=${{ steps.source.outputs.sha }}"):
            self.assertIn(text, self.builder)
        self.assertNotIn("|| true", self.builder)
        self.assertNotIn("matrix:", self.builder)

    def test_no_pr_and_explicit_validation_publication(self):
        self.assertIn("'23 */6 * * *'", self.sync)
        self.assertIn("cancel-in-progress: false", self.sync)
        self.assertIn("retry_validation:", self.sync)
        self.assertIn("uses: ./.github/workflows/linux-builder.yml", job(self.sync, "validate"))
        self.assertIn("uses: ./.github/workflows/linux-publisher.yml", job(self.sync, "publish"))
        self.assertNotIn("pull-requests: write", self.sync)
        self.assertNotIn("workflow_run:", self.sync)
        self.assertIn("branches: [master]", self.ci)
        self.assertNotIn("fork-arm64-maintenance", self.ci)
        self.assertIn("pull_request:", self.ci)
        self.assertIn("uses: ./.github/workflows/linux-publisher.yml", job(self.ci, "publish"))

    def test_trusted_prepare_promote_and_report(self):
        for name in ("prepare", "promote", "report"):
            text = job(self.sync, name)
            self.assertIn("ref: ${{ github.sha }}", text)
            self.assertNotIn("ref: ${{ needs.prepare.outputs.candidate_sha }}", text)
        prepare = job(self.sync, "prepare")
        self.assertIn('cp tools/sync-upstream.py "$RUNNER_TEMP/sync-upstream.py"', prepare)
        self.assertIn("contents: write", prepare)
        self.assertNotIn("issues: write", prepare)
        validate = job(self.sync, "validate")
        self.assertNotIn("write", re.sub(r"#.*", "", validate))
        self.assertNotIn("secrets:", validate)
        promote = job(self.sync, "promote")
        self.assertIn("needs.validate.result == 'success'", promote)
        self.assertIn("needs.validate.outputs.source_sha == needs.prepare.outputs.candidate_sha", promote)
        self.assertIn("--base", promote)
        self.assertIn("--policy", promote)
        self.assertIn("--upstream", promote)
        report = job(self.sync, "report")
        self.assertIn("issues: write", report)
        self.assertIn("statuses: write", report)
        self.assertNotIn("contents: write", report)

    def test_publisher_isolated_no_checkout_execution_or_rebuild(self):
        text = self.publisher
        self.assertIn("workflow_call:", text)
        self.assertIn("workflow_dispatch:", text)
        self.assertIn("artifact_run_id:", text)
        self.assertIn("packages: write", text)
        self.assertNotIn("actions/checkout@", text)
        self.assertNotIn("build-push-action@", text)
        self.assertNotRegex(text, r"\bdocker\s+(run|build)\b")
        for contract in ("docker image load", "docker image push",
                         '[[ "$current" == "$SOURCE_SHA" ]]',
                         '[[ "$remote" == "$digest" ]]',
                         '== "$TESTED_IMAGE_ID" ]]', "linux/amd64",
                         'org.opencontainers.image.source',
                         'org.opencontainers.image.revision'):
            self.assertIn(contract, text)
        self.assertIn("needs.promote.result == 'success'", job(self.sync, "publish"))
        self.assertIn('checks[0]["conclusion"] == "success"', text)
        self.assertIn('run["head_sha"] == sys.argv[4]', text)

    def test_policy_explicit_ownership_and_retirement(self):
        policy = sync.validate_policy(json.loads((ROOT / "tools/fork-policy.json").read_text()))
        for path in ("README.md", ".github/workflows/brand-new.yml", "docs/new.md",
                     "tools/sync-upstream.py", "tools/fork-policy.json",
                     "tools/docker/new.sh", "updater/updater.h"):
            self.assertEqual(sync.classify(policy, path), "keep", path)
        for path in ("android/new.c", "server/new.c", "extras/cheats/new.txt",
                     "runtime/platform/android.c", "runtime/platform/windows.c",
                     "tools/bundle_dlls.py", "updater/new.c", "tests/test_update_arch.c",
                     "update-build-arm64.sh", "tests/test_update_build.py"):
            self.assertEqual(sync.classify(policy, path), "remove", path)
        for path in ("updater/sha256.c", "runtime/new.c", "third_party/new.c"):
            self.assertEqual(sync.classify(policy, path), "shared", path)
        self.assertIsNone(sync.classify(policy, "unexpected-root.c"))
        self.assertIsNone(sync.classify(policy, ".github-evil/foo"))

    def test_dependabot_remains_monthly(self):
        text = (ROOT / ".github/dependabot.yml").read_text()
        self.assertEqual(text.count("interval: monthly"), 2)
        self.assertNotIn("auto-merge", text)

    def test_policy_covers_actual_tracked_tree_and_no_retired_files(self):
        import subprocess
        policy = sync.validate_policy(json.loads((ROOT / "tools/fork-policy.json").read_text()))
        paths = subprocess.check_output(
            ["git", "-C", str(ROOT), "ls-files", "-z"], text=True
        ).rstrip("\0").split("\0")
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(sync.classify(policy, path), ("keep", "shared"))

    def test_publisher_checks_actual_run_green_job_and_source_binding(self):
        match = re.search(r"<<'PY'\n(.*?)\n          PY", self.publisher, re.S)
        self.assertIsNotNone(match)
        guard = compile(textwrap.dedent(match.group(1)), "publisher-guard", "exec")
        sha = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = {"head_repository": {"full_name": sync.REPOSITORY},
                   "head_branch": "master", "event": "push", "status": "in_progress",
                   "path": ".github/workflows/linux-ci.yml", "head_sha": sha}
            jobs = [{"jobs": [{"name": "validate / AArch64 without game data (amd64 host)",
                               "conclusion": "success"}]}]

            def execute():
                (root / "validation-run.json").write_text(json.dumps(run))
                (root / "validation-jobs.json").write_text(json.dumps(jobs))
                with patch("sys.argv", ["-", str(root), "123", "123", sha]):
                    exec(guard, {})

            execute()
            jobs[0]["jobs"][0]["conclusion"] = "failure"
            with self.assertRaises(AssertionError):
                execute()
            jobs[0]["jobs"][0]["conclusion"] = "success"
            run["head_sha"] = "b" * 40
            with self.assertRaises(AssertionError):
                execute()
            run["path"] = ".github/workflows/upstream-sync.yml"
            status = {"context": sync.CONTEXT, "state": "success",
                      "target_url": f"https://github.com/{sync.REPOSITORY}/actions/runs/123"}
            (root / "validation-statuses.json").write_text(json.dumps([[status]]))
            execute()
            status["target_url"] += "4"
            (root / "validation-statuses.json").write_text(json.dumps([[status]]))
            with self.assertRaises(AssertionError):
                execute()


class ApiTests(unittest.TestCase):
    def test_latest_status_terminal_no_failed_rebuild(self):
        for state in ("success", "failure", "error"):
            with self.subTest(state=state), patch.object(sync, "api", return_value=[
                {"context": "other", "state": "pending"},
                {"context": sync.CONTEXT, "state": state},
            ]):
                self.assertTrue(sync.already_tested("a" * 40))
        with patch.object(sync, "api", return_value=[
            {"context": sync.CONTEXT, "state": "pending"},
            {"context": sync.CONTEXT, "state": "success"},
        ]):
            self.assertFalse(sync.already_tested("a" * 40))

    def test_issue_two_reopens_and_deduplicates_unchanged_block(self):
        state = {"key": "k", "state": "blocked", "sha": "a" * 40}
        with patch.object(sync, "api", side_effect=[{"state": "closed", "body": "old"}, None]) as api:
            sync.update_issue(state, "conflict", "run")
            self.assertEqual(api.call_args.args[:2], ("issues/2", "PATCH"))
            self.assertEqual(api.call_args.args[2]["state"], "open")
        issue = {"state": "open", "body": sync.state_marker(state) + "\nold"}
        with patch.object(sync, "api", return_value=issue) as api:
            sync.update_issue(state, "conflict", "different-run")
            self.assertEqual(api.call_count, 1)

    def test_clean_closes_existing_tracking_issue(self):
        with patch.object(sync, "api", side_effect=[
            {"state": "open", "body": sync.state_marker({"key": "k", "state": "blocked"})}, None,
        ]) as api:
            sync.update_issue({"key": "k", "state": "clean"}, "merged", "run")
            self.assertEqual(api.call_args.args[2]["state"], "closed")

    def test_noop_does_not_hide_unresolved_publication_failure(self):
        previous = {"key": "prior", "state": "publication-failed", "sha": "a" * 40}
        issue = {"state": "open", "body": sync.state_marker(previous) + "\nRetry publication"}
        with patch.object(sync, "api", return_value=issue) as api:
            sync.update_issue({"key": "new", "state": "clean"},
                              "No new upstream", "new-run")
            self.assertEqual(api.call_count, 1)

    def test_unchanged_failed_candidate_dedup_keeps_original_failure_detail(self):
        issue = {"state": "open", "body": sync.state_marker({
            "key": "k", "state": "blocked", "sha": "a" * 40}) + "\nOriginal build failure"}
        with patch.object(sync, "api", return_value=issue) as api:
            sync.update_issue({"key": "k", "state": "blocked"}, "known blocker", "new-run")
            self.assertEqual(api.call_count, 1)

    def test_publisher_failure_after_promotion_is_recoverable_not_rolled_back(self):
        args = Namespace(sha="a" * 40, key="k", phase="final", outcome="candidate",
                         promotion="success", publication="failure")
        with patch.object(sync, "update_issue") as issue, patch.object(sync, "summary"):
            sync.report(args, "run")
            self.assertEqual(issue.call_args.args[0]["state"], "publication-failed")
            self.assertIn("No rollback", issue.call_args.args[1])

    def test_only_exact_sha_receives_green_validation_status(self):
        args = Namespace(sha="a" * 40, key="k", phase="validation", result="success")
        with patch.object(sync, "api") as api, patch.object(sync, "update_issue") as issue:
            sync.report(args, "run")
            self.assertEqual(api.call_args.args[:2], ("statuses/" + args.sha, "POST"))
            self.assertEqual(api.call_args.args[2]["state"], "success")
            self.assertEqual(api.call_args.args[2]["target_url"], "run")
            issue.assert_not_called()

    def test_infrastructure_git_failure_is_not_an_expected_policy_blocker(self):
        self.assertFalse(issubclass(sync.GitFailure, sync.Intervention))

    def test_unchanged_block_skips_git_prepare_and_build(self):
        args = Namespace(repo=".", cleanup_legacy=False, retry=False)
        with patch.object(sync, "SyncGit") as factory, \
                patch.object(sync, "issue_state", return_value={"key": "k", "state": "blocked"}), \
                patch.object(sync, "write_outputs") as outputs:
            git = factory.return_value
            git.context.return_value = {"base": "a" * 40, "upstream": "b" * 40,
                                        "policy": "c" * 64, "key": "k", "previous": None}
            sync.prepare(args, "run")
            git.prepare.assert_not_called()
            self.assertEqual(outputs.call_args.kwargs["outcome"], "blocked")
            self.assertEqual(outputs.call_args.kwargs["should_validate"], "false")

    def test_tested_candidate_prepare_never_pushes_or_opens_pr(self):
        sha = "a" * 40
        args = Namespace(repo=".", cleanup_legacy=False, retry=False)
        context = {"base": "b" * 40, "upstream": "c" * 40,
                   "policy": "d" * 64, "key": "k", "previous": sha}
        with patch.object(sync, "SyncGit") as factory, \
                patch.object(sync, "issue_state", return_value={}), \
                patch.object(sync, "already_tested", return_value=True), \
                patch.object(sync, "write_outputs") as outputs, \
                patch.object(sync, "summary"), patch.object(sync, "api") as api:
            git = factory.return_value
            git.context.return_value = context
            git.prepare.return_value = dict(context, outcome="candidate", sha=sha,
                                            previous=sha, changed=False, omitted=[])
            git.remote_tip.return_value = sha
            sync.prepare(args, "run")
            git.push_candidate.assert_not_called()
            api.assert_not_called()
            self.assertEqual(outputs.call_args.kwargs["should_validate"], "false")

    def test_promotion_requires_green_current_run_status_before_git(self):
        args = Namespace(repo=".", sha="a" * 40, base="b" * 40,
                         upstream="c" * 40, policy="d" * 64, result="success")
        for state, url in (("pending", "run"), ("success", "old-run")):
            with patch.object(sync, "api", return_value=[
                {"context": sync.CONTEXT, "state": state, "target_url": url},
            ]), patch.object(sync, "SyncGit") as factory:
                with self.assertRaises(sync.Intervention):
                    sync.promote(args, "run")
                factory.assert_not_called()

    def test_non_sha_rejected_before_api(self):
        args = Namespace(repo=".", sha="master", base="b" * 40,
                         upstream="c" * 40, policy="d" * 64, result="success")
        with patch.object(sync, "api") as api, self.assertRaises(sync.Intervention):
            sync.promote(args, "run")
        api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
