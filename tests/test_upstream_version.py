"""Real offline Git fixtures; the fixed upstream URL is rewritten locally."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/upstream-version.sh"
UPSTREAM = "https://github.com/morerokk/MHGURecomp.git"


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.writer = self.root / "upstream writer"
        self.remote = self.root / "upstream.git"
        self.repo = self.root / "fork checkout"
        self.env = os.environ.copy()
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_TERMINAL_PROMPT="0")
        self.git(self.root, "init", "-q", "--initial-branch=main", str(self.writer))
        self.git(self.writer, "config", "user.name", "Version Fixture")
        self.git(self.writer, "config", "user.email", "fixture@example.invalid")
        self.base = self.commit("base")
        self.git(self.root, "clone", "--bare", str(self.writer), str(self.remote))
        self.git(self.root, "clone", "--no-local", str(self.remote), str(self.repo))
        self.git(self.repo, "config", f"url.{self.remote}.insteadOf", UPSTREAM)

    def git(self, repo, *args):
        return subprocess.run(["git", "-C", str(repo), *args], env=self.env,
                              check=True, text=True, capture_output=True).stdout.strip()

    def commit(self, text):
        (self.writer / "fixture").write_text(text)
        self.git(self.writer, "add", ".")
        self.git(self.writer, "commit", "-qm", text)
        return self.git(self.writer, "rev-parse", "HEAD")

    def tag(self, name, target=None, annotated=False):
        args = ["tag"]
        if annotated:
            args.extend(["-a", "-m", "Fixture release"])
        args.extend([name, target or self.base])
        self.git(self.writer, *args)
        self.git(self.writer, "push", str(self.remote), "refs/tags/" + name)

    def resolve(self, *args, repo=None):
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=repo or self.repo,
                              env=self.env, capture_output=True, text=True)

    def success(self, version):
        result = self.resolve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, version + "\n")

    def failure(self, message):
        result = self.resolve()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)

    def test_natural_order_annotated_and_nonrelease_names(self):
        for name in ("0.9", "0.13", "0.13.1", "v999", "999-rc1",
                     "release-999", "999.0-beta"):
            self.tag(name, annotated=name == "0.13.1")
        self.success("0.13.1")

    def test_local_and_fork_numeric_tags_are_not_authority(self):
        self.tag("0.12.0")
        self.git(self.repo, "tag", "999")
        original = self.git(self.repo, "rev-parse", "refs/tags/999")
        # Even a same-name local tag must never be overwritten by upstream.
        blob = self.git(self.repo, "hash-object", "-w", "fixture")
        self.git(self.repo, "tag", "0.12.0", blob)
        self.success("0.12.0")
        self.assertEqual(self.git(self.repo, "rev-parse", "refs/tags/999"), original)
        self.assertEqual(self.git(self.repo, "rev-parse", "refs/tags/0.12.0"), blob)
        self.assertEqual(self.git(self.repo, "tag", "--list"), "0.12.0\n999")

    def test_only_integrated_ancestors_are_eligible(self):
        self.tag("0.12.0")
        future = self.commit("not integrated")
        self.tag("99", future)
        self.git(self.writer, "checkout", "--orphan", "unrelated")
        unrelated = self.commit("unrelated")
        self.tag("999", unrelated, annotated=True)
        self.success("0.12.0")
        self.git(self.repo, "fetch", "--no-tags", str(self.remote), future)
        self.git(self.repo, "merge", "--ff-only", "FETCH_HEAD")
        self.success("99")

    def test_deleted_cached_tag_is_not_eligible(self):
        self.tag("0.9")
        self.tag("0.13.1", annotated=True)
        self.success("0.13.1")
        self.git(self.remote, "update-ref", "-d", "refs/tags/0.13.1")
        self.success("0.9")
        self.git(self.remote, "update-ref", "-d", "refs/tags/0.9")
        self.failure("no numeric upstream tags")

    def test_previously_observed_tag_move_is_refused(self):
        self.tag("0.12.0")
        self.success("0.12.0")
        changed = self.commit("new target")
        self.git(self.writer, "push", str(self.remote), "HEAD:refs/heads/main")
        self.git(self.remote, "update-ref", "refs/tags/0.12.0", changed)
        self.failure("upstream tag 0.12.0 changed")

    def test_annotated_tag_object_change_with_same_commit_is_refused(self):
        self.tag("0.12.0", annotated=True)
        self.success("0.12.0")
        self.git(self.writer, "tag", "-fa", "-m", "Changed annotation", "0.12.0", self.base)
        self.git(self.writer, "push", "--force", str(self.remote), "refs/tags/0.12.0")
        self.failure("upstream tag 0.12.0 changed")

    def test_deleted_then_recreated_tag_move_is_refused(self):
        self.tag("0.12.0", annotated=True)
        self.success("0.12.0")
        self.git(self.remote, "update-ref", "-d", "refs/tags/0.12.0")
        self.failure("no numeric upstream tags")
        self.git(self.remote, "update-ref", "refs/tags/0.12.0", self.base)
        self.failure("upstream tag 0.12.0 changed")

    def test_remote_failure_never_uses_cache(self):
        self.tag("0.12.0")
        self.success("0.12.0")
        shutil.rmtree(self.remote)
        self.failure("cannot query upstream")

    def test_fetch_failure_never_uses_cache(self):
        self.tag("0.12.0")
        self.success("0.12.0")
        # Keep real Git for every operation except this injected transport error.
        shimdir = self.root / "bin"
        shimdir.mkdir()
        git = shutil.which("git")
        (shimdir / "git").write_text(
            '#!/bin/bash\nfor arg in "$@"; do\n'
            '  [[ $arg != fetch ]] || exit 23\n'
            f'done\nexec "{git}" "$@"\n')
        (shimdir / "git").chmod(0o755)
        self.env["PATH"] = str(shimdir) + os.pathsep + self.env["PATH"]
        self.failure("cannot fetch upstream tags")

    def test_no_numeric_tags(self):
        self.tag("v1")
        self.git(self.repo, "tag", "999")
        self.failure("no numeric upstream tags")

    def test_no_ancestor_and_noncommit_tags(self):
        future = self.commit("future only")
        self.tag("1", future)
        blob = self.git(self.writer, "hash-object", "-w", "fixture")
        self.tag("999", blob)
        self.failure("no numeric upstream tag is an ancestor of HEAD")

    def test_shallow_history_refuses_even_matching_tag(self):
        self.tag("0.12.0")
        shallow = self.root / "shallow"
        self.git(self.root, "clone", "--depth=1", self.remote.as_uri(), str(shallow))
        self.git(shallow, "config", f"url.{self.remote}.insteadOf", UPSTREAM)
        result = self.resolve(repo=shallow)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("shallow", result.stderr)
        self.assertIn("git fetch --unshallow origin", result.stderr)

    def test_replace_refs_cannot_forge_ancestry(self):
        self.tag("0.12.0")
        future = self.commit("future")
        self.tag("99", future)
        self.git(self.repo, "fetch", "--no-tags", str(self.remote), future)
        self.git(self.repo, "replace", self.base, future)
        self.success("0.12.0")

    def test_concurrent_metadata_lock_refuses_without_network(self):
        common = self.git(self.repo, "rev-parse", "--git-common-dir")
        lock = self.repo / common / "upstream-version.lock"
        lock.mkdir()
        self.failure("another upstream version lookup")

    def test_arguments_are_rejected(self):
        result = self.resolve("0.12.0")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("no arguments", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
