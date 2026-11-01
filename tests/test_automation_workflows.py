"""Security/transport contracts, plus mocked API tests. All tests are stdlib."""
import importlib.util
import re
from pathlib import Path
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

    def test_every_external_action_is_immutable(self):
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            for action in re.findall(r"^\s*(?:-\s*)?uses:\s+([^\s#]+)", path.read_text(), re.M):
                if not action.startswith("./"):
                    self.assertRegex(action, r"^[\w/-]+@[0-9a-f]{40}$")

    def test_validator_is_reusable_and_strictly_read_only(self):
        self.assertIn("workflow_call:", self.builder)
        self.assertNotIn("write", re.sub(r"#.*", "", self.builder))
        self.assertNotIn("secrets:", self.builder)
        self.assertIn("persist-credentials: false", self.builder)
        self.assertIn("ref: ${{ inputs.candidate_ref || github.sha }}", self.builder)
        self.assertIn('[[ "$sha" == "$expected" ]]', self.builder)
        self.assertNotIn("pull_request_target", self.builder + self.sync + self.ci)

    def test_only_arm64_target_with_mandatory_tests(self):
        self.assertIn("runs-on: ubuntu-24.04", self.builder)
        self.assertIn("timeout-minutes: 60", self.builder)
        self.assertIn("--check --version 0 --jobs 2", self.builder)
        self.assertNotIn("--check aarch64", self.builder)
        self.assertNotIn("--check x86_64", self.builder)
        self.assertNotIn("matrix:", self.builder)
        self.assertNotIn("|| true", self.builder)
        self.assertIn("shellcheck tools/build-linux-release.sh", self.builder)
        self.assertIn("actionlint", self.builder)
        self.assertIn("unittest discover", self.builder)
        self.assertIn("platforms: linux/amd64", self.builder)

    def test_docker_revision_argument_matches_checked_out_source(self):
        self.assertIn("build-args:", self.builder)
        self.assertIn(
            "SOURCE_REVISION=${{ steps.source.outputs.sha }}", self.builder)

    def test_human_push_on_bot_branch_is_still_validated(self):
        self.assertIn(
            "github.event.sender.login != 'github-actions[bot]'", self.builder)
        self.assertIn(
            "github.event.pull_request.head.repo.full_name != github.repository",
            self.builder)

    def test_sync_marks_candidate_pending_before_readonly_build(self):
        queue = job(self.sync, "queue")
        self.assertIn("statuses: write", queue)
        self.assertNotIn("actions/checkout@", queue)
        self.assertIn("state=pending", queue)
        self.assertIn("needs: [prepare, queue]", job(self.sync, "validate"))

    def test_sync_trusted_prepare_readonly_validate_and_status_report(self):
        prepare = job(self.sync, "prepare")
        validate = job(self.sync, "validate")
        report = job(self.sync, "report")
        self.assertIn("contents: write", prepare)
        self.assertIn('cp tools/sync-upstream.py "$RUNNER_TEMP/sync-upstream.py"', prepare)
        self.assertIn('python3 "$RUNNER_TEMP/sync-upstream.py"', prepare)
        self.assertIn("ref: ${{ github.sha }}", prepare)
        self.assertNotIn("write", re.sub(r"#.*", "", validate))
        self.assertNotIn("secrets:", validate)
        self.assertIn("uses: ./.github/workflows/linux-builder.yml", validate)
        self.assertIn("candidate_ref: ${{ needs.prepare.outputs.candidate_sha }}", validate)
        self.assertIn("statuses: write", report)
        self.assertNotIn("contents: write", report)
        self.assertIn("ref: ${{ github.sha }}", report)
        self.assertNotIn("ref: ${{ needs.prepare.outputs.candidate_sha }}", report)

    def test_shifted_schedule_no_bot_event_dependency(self):
        self.assertIn("'23 */6 * * *'", self.sync)
        self.assertIn("cancel-in-progress: false", self.sync)
        self.assertIn("retry_validation:", self.sync)
        self.assertIn("cleanup_legacy:", self.sync)
        self.assertIn("should_validate == 'true'", self.sync)
        self.assertNotIn("workflow_run:", self.sync)
        self.assertIn("head.ref != 'bot/upstream-sync'", self.builder)

    def test_publisher_does_not_execute_checkout_or_rebuild(self):
        publish = job(self.ci, "publish")
        self.assertIn("packages: write", publish)
        self.assertNotIn("actions/checkout@", publish)
        self.assertNotIn("build-push-action@", publish)
        self.assertNotRegex(publish, r"\bdocker\s+(run|build)\b")
        self.assertNotIn("bash tools/", publish)
        self.assertIn("docker image load", publish)
        self.assertIn("docker image push", publish)
        self.assertIn('[[ "$current" == "$SOURCE_SHA" ]]', publish)
        self.assertIn('[[ "$remote" == "$digest" ]]', publish)
        self.assertIn('== "$TESTED_IMAGE_ID" ]]', publish)
        self.assertIn("candidate_ref: ''", job(self.ci, "validate"))
        self.assertIn("github.event_name == 'push'", publish)
        self.assertIn("github.event_name == 'workflow_dispatch'", publish)
        self.assertIn("github.ref == 'refs/heads/master'", publish)
        self.assertIn("retention-days: 1", self.builder)
        self.assertIn('[[ -z "$CANDIDATE"', self.builder)

    def test_bootstrap_branch_runs_checks_but_cannot_publish(self):
        self.assertIn("branches: [master, fork-arm64-maintenance]", self.ci)
        publish = job(self.ci, "publish")
        self.assertIn("github.ref == 'refs/heads/master'", publish)

    def test_dependabot_monthly_grouped_no_automerge(self):
        text = (ROOT / ".github/dependabot.yml").read_text()
        self.assertEqual(text.count("interval: monthly"), 2)
        self.assertEqual(text.count("groups:"), 2)
        self.assertIn("directory: /tools/docker", text)
        self.assertNotIn("auto-merge", text)


class ApiTests(unittest.TestCase):
    def test_tested_sha_skips_build_even_after_failure(self):
        for state in ("success", "failure", "error"):
            with self.subTest(state=state), patch.object(sync, "api", return_value=[
                {"context": "another", "state": "pending"},
                {"context": sync.CONTEXT, "state": state},
            ]):
                self.assertTrue(sync.already_tested("a" * 40))

    def test_latest_context_wins_and_unfinished_can_retry(self):
        with patch.object(sync, "api", return_value=[
            {"context": sync.CONTEXT, "state": "pending"},
            {"context": sync.CONTEXT, "state": "success"},
        ]):
            self.assertFalse(sync.already_tested("a" * 40))
        with patch.object(sync, "api", return_value=[]):
            self.assertFalse(sync.already_tested("b" * 40))

    def test_existing_bot_comment_is_updated_not_spammed(self):
        comment = {"id": 42, "user": {"login": sync.BOT_NAME},
                   "body": sync.COMMENT + "\nold"}
        with patch.object(sync, "api", side_effect=[[comment], None]) as api:
            sync.comment(1, "new")
            self.assertEqual(api.call_args.args[:2], ("issues/comments/42", "PATCH"))

    def test_unchanged_comment_has_no_write(self):
        comment = {"id": 42, "user": {"login": sync.BOT_NAME},
                   "body": sync.COMMENT + "\nsame"}
        with patch.object(sync, "api", return_value=[comment]) as api:
            sync.comment(1, "same")
            self.assertEqual(api.call_count, 1)

    def test_human_marker_comment_is_never_edited(self):
        comment = {"id": 42, "user": {"login": "human"},
                   "body": sync.COMMENT + "\nold"}
        with patch.object(sync, "api", side_effect=[[comment], None]) as api:
            sync.comment(1, "new")
            self.assertEqual(api.call_args.args[:2], ("issues/1/comments", "POST"))

    def test_issue_disabled_conflict_remains_visible(self):
        with patch.object(sync, "pull_request", return_value=None), \
             patch.object(sync, "api", return_value={"has_issues": False}) as api, \
             patch("builtins.print") as output:
            sync.notify_failure("conflict", "https://example.test/run")
            self.assertEqual(api.call_count, 1)
            self.assertIn("::error::", output.call_args.args[0])

    def test_conflict_reuses_single_tracking_issue_even_when_closed(self):
        issue = {"number": 14, "title": sync.ISSUE_TITLE, "state": "closed",
                 "user": {"login": sync.BOT_NAME}}
        with patch.object(sync, "pull_request", return_value=None), \
             patch.object(sync, "api", side_effect=[
                 {"has_issues": True}, [issue], None,
             ]) as api:
            sync.notify_failure("conflict", "https://example.test/run")
            self.assertEqual(api.call_args.args[:2], ("issues/14", "PATCH"))
            self.assertIn("state=all", api.call_args_list[1].args[0])

    def test_tested_candidate_prepare_makes_no_api_writes_or_pr(self):
        from argparse import Namespace
        sha = "a" * 40
        with patch.object(sync, "SyncGit") as factory, \
             patch.object(sync, "write_outputs") as outputs, \
             patch.object(sync, "already_tested", return_value=True), \
             patch.object(sync, "pull_request") as pr, \
             patch.object(sync, "api") as api:
            git = factory.return_value
            git.prepare.return_value = {
                "outcome": "candidate", "sha": sha, "changed": False, "previous": sha}
            git.remote_tip.return_value = sha
            git.run.return_value.returncode = 0
            sync.prepare(Namespace(repo=".", cleanup_legacy=False, retry=False), "run")
            git.push_candidate.assert_not_called()
            pr.assert_not_called()
            api.assert_not_called()
            outputs.assert_called_once_with(should_validate="false")

    def test_report_binds_status_to_exact_sha_and_warns_stale_head(self):
        from argparse import Namespace
        args = Namespace(sha="a" * 40, pr="7", result="success")
        pr = {"head": {"ref": sync.BRANCH, "sha": "b" * 40,
                       "repo": {"full_name": sync.REPOSITORY}},
              "base": {"ref": "master", "sha": "c" * 40}}
        with patch.object(sync, "api", side_effect=[
            pr, {"status": "ahead"}, None,
        ]) as api, \
             patch.object(sync, "comment") as comment:
            sync.report(args, "https://example.test/run")
            self.assertEqual(api.call_args.args[:2], (f"statuses/{args.sha}", "POST"))
            self.assertEqual(api.call_args.args[2]["state"], "success")
            self.assertIn("does NOT validate", comment.call_args.args[1])

    def test_report_rejects_success_when_master_has_advanced(self):
        from argparse import Namespace
        args = Namespace(sha="a" * 40, pr="7", result="success")
        pr = {"head": {"ref": sync.BRANCH, "sha": args.sha,
                       "repo": {"full_name": sync.REPOSITORY}},
              "base": {"ref": "master", "sha": "c" * 40}}
        with patch.object(sync, "api", side_effect=[
            pr, {"status": "diverged"}, None,
        ]) as api, patch.object(sync, "comment") as comment:
            sync.report(args, "https://example.test/run")
            self.assertEqual(api.call_args.args[2]["state"], "failure")
            self.assertIn("master advanced", comment.call_args.args[1])

    def test_report_rejects_non_sha_before_api(self):
        from argparse import Namespace
        with patch.object(sync, "api") as api:
            with self.assertRaises(sync.Intervention):
                sync.report(Namespace(sha="master", pr="7", result="success"), "run")
            api.assert_not_called()


if __name__ == "__main__":
    unittest.main()
