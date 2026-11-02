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
        self.tag("0.13.1")
        self.pin()

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

    def pin(self, version="0.13.1", repo=None, **overrides):
        values = dict(
            schema="1", algorithm="release-base-v1",
            repository="morerokk/MHGURecomp", release_id="430720896",
            version=version, tag=version,
            tag_oid=self.git(self.writer, "rev-parse", "refs/tags/" + version),
            commit=self.git(self.writer, "rev-parse", "refs/tags/" + version + "^{}"),
            published_at="2026-11-01T16:56:04Z", fork_base=self.base,
            migration_merge=self.base, migration_source=self.base)
        values.update(overrides)
        path = (repo or self.repo) / "tools/upstream-release.tsv"
        path.parent.mkdir(exist_ok=True)
        path.write_bytes("".join(f"{key}\t{value}\n" for key, value in values.items()).encode())
        return path

    def resolve(self, *args, repo=None):
        return subprocess.run(["bash", str(SCRIPT), *args], cwd=repo or self.repo,
                              env=self.env, capture_output=True, text=True)

    def success(self, version="0.13.1", repo=None):
        result = self.resolve(repo=repo)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, version + "\n")

    def failure(self, message, repo=None):
        result = self.resolve(repo=repo)
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn(message, result.stderr)

    def shim(self, body):
        """Inject only a transport fault/race; all other operations use real Git."""
        shimdir = self.root / "bin"
        shimdir.mkdir(exist_ok=True)
        git = shutil.which("git")
        (shimdir / "git").write_text(
            "#!/bin/bash\n" + body + f'\nexec "{git}" "$@"\n')
        (shimdir / "git").chmod(0o755)
        self.env["PATH"] = str(shimdir) + os.pathsep + self.env["PATH"]

    def assert_clean(self):
        self.assertEqual(self.git(self.repo, "for-each-ref", "--format=%(refname)",
                                  "refs/upstream-version/"), "")
        common = Path(self.git(self.repo, "rev-parse", "--path-format=absolute",
                               "--git-common-dir"))
        self.assertEqual(list(common.glob("upstream-version.*")), [])

    def test_pin_not_highest_historical_ancestor(self):
        for name in ("0.9", "0.13", "0.13.2", "999", "v999", "999-rc1"):
            self.tag(name, annotated=name == "0.13.2")
        self.success()

    def test_annotated_pin(self):
        self.tag("0.13.0", annotated=True)
        self.pin("0.13.0")
        self.success("0.13.0")
        self.assert_clean()

    def test_local_tags_are_not_authority_or_overwritten(self):
        self.git(self.repo, "tag", "999")
        blob = self.git(self.repo, "hash-object", "-w", "fixture")
        self.git(self.repo, "tag", "0.13.1", blob)
        self.success()
        self.assertEqual(self.git(self.repo, "rev-parse", "refs/tags/999"), self.base)
        self.assertEqual(self.git(self.repo, "rev-parse", "refs/tags/0.13.1"), blob)
        self.assertEqual(self.git(self.repo, "tag", "--list"), "0.13.1\n999")

    def test_higher_release_never_overrides_pin(self):
        future = self.commit("not integrated")
        self.tag("99", future)
        self.success()
        self.git(self.repo, "fetch", "--no-tags", str(self.remote), future)
        self.git(self.repo, "merge", "--ff-only", "FETCH_HEAD")
        self.success()

    def test_pin_must_be_ancestor(self):
        future = self.commit("not integrated")
        self.tag("99", future)
        self.pin("99")
        self.failure("not an ancestor")
        self.assert_clean()

    def test_unrelated_pin_is_refused(self):
        self.git(self.writer, "checkout", "--orphan", "unrelated")
        unrelated = self.commit("unrelated")
        self.tag("999", unrelated, annotated=True)
        self.pin("999")
        self.failure("not an ancestor")

    def test_deleted_tag_never_falls_back(self):
        self.tag("0.9")
        self.success()
        self.git(self.remote, "update-ref", "-d", "refs/tags/0.13.1")
        self.failure("not advertised")
        self.assert_clean()

    def move_tag(self):
        changed = self.commit("new target")
        self.git(self.writer, "push", str(self.remote), "HEAD:refs/heads/main")
        self.git(self.remote, "update-ref", "refs/tags/0.13.1", changed)
        self.failure("does not match")

    def test_moved_tag_refused_on_first_lookup(self):
        self.move_tag()

    def test_previously_verified_tag_move_is_refused(self):
        self.success()
        self.move_tag()

    def test_annotation_change_same_commit_is_refused(self):
        self.tag("0.13.0", annotated=True)
        self.pin("0.13.0")
        self.success("0.13.0")
        self.git(self.writer, "tag", "-fa", "-m", "Changed annotation", "0.13.0", self.base)
        self.git(self.writer, "push", "--force", str(self.remote), "refs/tags/0.13.0")
        self.failure("does not match")

    def test_deleted_recreated_tag_move_is_refused(self):
        self.tag("0.13.0", annotated=True)
        self.pin("0.13.0")
        self.success("0.13.0")
        self.git(self.remote, "update-ref", "-d", "refs/tags/0.13.0")
        self.failure("not advertised")
        self.git(self.remote, "update-ref", "refs/tags/0.13.0", self.base)
        self.failure("does not match")

    def test_network_failure_never_uses_cache(self):
        self.success()
        shutil.rmtree(self.remote)
        self.failure("cannot query upstream")
        self.assert_clean()

    def test_fetch_failure_never_uses_cache(self):
        self.success()
        self.shim('for arg in "$@"; do [[ $arg != fetch ]] || exit 23; done')
        self.failure("cannot fetch upstream")
        self.assert_clean()

    def test_exact_oid_fetch_and_double_snapshot(self):
        logfile = self.root / "transport.log"
        self.shim(f'''for arg in "$@"; do
  if [[ $arg == fetch || $arg == ls-remote ]]; then
    printf '%s\\n' "$*" >> "{logfile}"
  fi
done''')
        self.success()
        lines = logfile.read_text().splitlines()
        self.assertEqual(sum("ls-remote" in line for line in lines), 2)
        fetch = next(line for line in lines if "fetch" in line)
        self.assertIn(self.base + ":refs/upstream-version/", fetch)
        for flag in ("--no-tags", "--no-write-fetch-head", "--no-recurse-submodules"):
            self.assertIn(flag, fetch)
        self.assertFalse((self.repo / ".git/FETCH_HEAD").exists())
        self.assert_clean()

    def test_tag_deleted_during_fetch_is_refused(self):
        git = shutil.which("git")
        self.shim(f'''for arg in "$@"; do
  if [[ $arg == fetch ]]; then
    "{git}" "$@" || exit $?
    "{git}" -C "{self.remote}" update-ref -d refs/tags/0.13.1
    exit 0
  fi
done''')
        self.failure("not advertised")
        self.assert_clean()

    def test_annotation_changed_during_fetch_is_refused(self):
        self.tag("0.13.0", annotated=True)
        self.pin("0.13.0")
        git = shutil.which("git")
        self.shim(f'''for arg in "$@"; do
  if [[ $arg == fetch ]]; then
    "{git}" "$@" || exit $?
    "{git}" -C "{self.remote}" update-ref refs/tags/0.13.0 "{self.base}"
    exit 0
  fi
done''')
        self.failure("does not match")
        self.assert_clean()

    def test_second_snapshot_network_failure_is_refused(self):
        git = shutil.which("git")
        self.shim(f'''for arg in "$@"; do
  if [[ $arg == fetch ]]; then
    "{git}" "$@" || exit $?
    mv "{self.remote}" "{self.root}/withdrawn.git"
    exit 0
  fi
done''')
        self.failure("cannot query upstream")
        self.assert_clean()

    def test_failed_fetch_cleans_a_partially_created_ref(self):
        git = shutil.which("git")
        self.shim(f'''for arg in "$@"; do
  if [[ $arg == fetch ]]; then
    "{git}" "$@" || exit $?
    exit 23
  fi
done''')
        self.failure("cannot fetch upstream")
        self.assert_clean()

    def test_incorrect_fetched_object_is_refused(self):
        git = shutil.which("git")
        blob = self.git(self.repo, "hash-object", "-w", "fixture")
        self.shim(f'''fetching=false
for arg in "$@"; do
  [[ $arg != fetch ]] || fetching=true
done
if $fetching; then
  "{git}" "$@" || exit $?
  destination="${{!#}}"
  "{git}" update-ref "${{destination#*:}}" "{blob}"
  exit 0
fi''')
        self.failure("does not match")
        self.assert_clean()

    def test_noncommit_lightweight_tag_is_refused(self):
        blob = self.git(self.writer, "hash-object", "-w", "fixture")
        self.tag("99", blob)
        self.pin("99")
        self.failure("not a commit")

    def test_noncommit_annotated_tag_is_refused(self):
        blob = self.git(self.writer, "hash-object", "-w", "fixture")
        self.tag("99", blob, annotated=True)
        self.pin("99")
        self.failure("not a commit")

    def test_pinned_lightweight_commit_mismatch(self):
        self.pin(commit="a" * 40)
        self.failure("does not match")

    def test_pinned_annotated_commit_mismatch(self):
        self.tag("99", annotated=True)
        self.pin("99", commit="a" * 40)
        self.failure("does not match")

    def test_missing_state(self):
        (self.repo / "tools/upstream-release.tsv").unlink()
        self.failure("state")

    def test_invalid_state_structure_before_network(self):
        state = (self.repo / "tools/upstream-release.tsv").read_bytes()
        lines = state.splitlines(keepends=True)
        variants = {
            "missing final LF": state[:-1],
            "CRLF": state.replace(b"\n", b"\r\n"),
            "NUL": state.replace(b"release-base", b"release\x00-base"),
            "duplicate": state + lines[0], "missing": b"".join(lines[:-1]),
            "unknown": state + b"extra\tvalue\n",
            "reordered": b"".join([lines[1], lines[0], *lines[2:]]),
            "blank line": state + b"\n", "empty": b"",
            "extra tab": state.replace(b"schema\t1", b"schema\t\t1"),
            "space delimiter": state.replace(b"schema\t1", b"schema 1"),
            "BOM": b"\xef\xbb\xbf" + state,
        }
        shutil.rmtree(self.remote)
        for label, data in variants.items():
            with self.subTest(label=label):
                (self.repo / "tools/upstream-release.tsv").write_bytes(data)
                self.failure("state")

    def test_invalid_state_values_before_network(self):
        shutil.rmtree(self.remote)
        invalid = {
            "schema": ("0", "01", ""),
            "algorithm": ("other", "release-base-v2"),
            "repository": ("fork/MHGURecomp", UPSTREAM),
            "release_id": ("0", "-1", "01", "1x", " 1"),
            "version": ("v0.13.1", "0.13.1-rc1", "0..1", "1.", "1 2"),
            "tag": ("0.13.2", "v0.13.1"),
            "tag_oid": ("a" * 39, "A" * 40, "g" * 40),
            "commit": ("a" * 41, "A" * 40),
            "published_at": ("2026-11-01T16:56:04+00:00", "2026-11-01",
                             "2026-02-30T16:56:04Z", "2026-11-01T24:00:00Z",
                             "2026-13-01T16:56:04Z", "2025-02-29T16:56:04Z"),
            "fork_base": ("a" * 39,), "migration_merge": ("bad",),
            "migration_source": ("A" * 40,),
        }
        for key, values in invalid.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    path = self.pin()
                    lines = path.read_text().splitlines()
                    path.write_text("".join(
                        f"{key}\t{value}\n" if line.startswith(key + "\t")
                        else line + "\n" for line in lines))
                    self.failure("state")

    def test_state_is_never_executed(self):
        marker = self.root / "should-not-exist"
        self.pin(algorithm=f"$(touch '{marker}')")
        self.failure("state")
        self.assertFalse(marker.exists())

    def test_valid_leap_day(self):
        self.pin(published_at="2024-02-29T00:00:00Z")
        self.success()

    def test_shallow_history_refuses_matching_tag(self):
        shallow = self.root / "shallow"
        self.git(self.root, "clone", "--depth=1", self.remote.as_uri(), str(shallow))
        self.git(shallow, "config", f"url.{self.remote}.insteadOf", UPSTREAM)
        self.pin(repo=shallow)
        self.failure("shallow", repo=shallow)
        self.assertIn("git fetch --unshallow origin", self.resolve(repo=shallow).stderr)

    def test_history_becoming_shallow_during_fetch(self):
        git = shutil.which("git")
        self.shim(f'''for arg in "$@"; do
  if [[ $arg == fetch ]]; then
    "{git}" "$@" || exit $?
    printf '%s\\n' "{self.base}" > "{self.repo}/.git/shallow"
    exit 0
  fi
done''')
        self.failure("shallow")
        self.assert_clean()

    def test_replace_refs_do_not_override_valid_pin(self):
        future = self.commit("future")
        self.tag("99", future)
        self.git(self.repo, "fetch", "--no-tags", str(self.remote), future)
        self.git(self.repo, "replace", self.base, future)
        self.success()

    def test_replace_refs_cannot_forge_ancestry(self):
        future = self.commit("future")
        self.tag("99", future)
        self.pin("99")
        self.git(self.repo, "fetch", "--no-tags", str(self.remote), future)
        self.git(self.repo, "replace", self.base, future)
        self.failure("not an ancestor")

    def test_grafts_cannot_forge_ancestry(self):
        future = self.commit("future")
        self.tag("99", future)
        self.pin("99")
        self.git(self.repo, "fetch", "--no-tags", str(self.remote), future)
        (self.repo / ".git/info/grafts").write_text(f"{self.base} {future}\n")
        self.failure("graft")

    def test_common_lock_refuses_without_network(self):
        common = self.git(self.repo, "rev-parse", "--git-common-dir")
        lock = self.repo / common / "upstream-version.lock"
        lock.mkdir()
        shutil.rmtree(self.remote)
        self.failure("another upstream version lookup")
        self.assertTrue(lock.exists())

    def test_linked_worktree_common_lock_and_own_state(self):
        worktree = self.root / "linked checkout"
        self.git(self.repo, "worktree", "add", "--detach", str(worktree), "HEAD")
        self.pin(repo=worktree)
        self.success(repo=worktree)
        lock = self.repo / ".git/upstream-version.lock"
        lock.mkdir()
        self.failure("another upstream version lookup", repo=worktree)

    def test_cleanup_allows_repeated_lookup(self):
        self.success()
        self.assert_clean()
        self.success()
        self.assert_clean()

    def test_subdirectory_uses_repository_state(self):
        nested = self.repo / "nested directory"
        nested.mkdir()
        self.success(repo=nested)

    def test_arguments_are_rejected(self):
        for args in (("0.13.1",), ("--check", "--version", "0"), ("",)):
            with self.subTest(args=args):
                result = self.resolve(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")
                self.assertIn("no arguments", result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
