"""Offline integration tests: real Git, explicit Docker/build stubs, no game data."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "update-build-arm64.sh"
ORIGIN = "https://github.com/pablovesnine/MHGURecomp.git"

DOCKER_STUB = """#!/usr/bin/env bash
set -eu
if [[ ${TEST_DOCKER_FAIL:-0} == 1 ]]; then
  printf 'test Docker connection refused\\n' >&2
  exit 1
fi
if [[ $1 == context ]]; then
  printf '%s\\n' "${TEST_DOCKER_ENDPOINT:-unix:///test-only-docker.sock}"
elif [[ $1 == --host && $3 == info ]]; then
  printf '["name=rootless"]\\n'
else
  printf 'unexpected test Docker arguments\\n' >&2
  exit 99
fi
"""

WRAPPER_STUB = """#!/usr/bin/env bash
# Test stub only: packages a literal test marker, never game content.
set -euo pipefail
mkdir -p .linux-release
printf '%s\\n' "$@" > .linux-release/test-args
printf 'test wrapper invoked\\n'
if [[ -n ${TEST_BUILD_ENTERED:-} ]]; then
  touch "$TEST_BUILD_ENTERED"
  while [[ ! -e $TEST_BUILD_RELEASE ]]; do sleep 0.05; done
fi
if [[ ${TEST_BUILD_FAIL:-0} == 1 ]]; then
  printf 'test build failed\\n' >&2
  exit 23
fi
version=''
while (($#)); do
  case "$1" in
    --game|--jobs) shift 2 ;;
    --version) version=$2; shift 2 ;;
    *) exit 98 ;;
  esac
done
mkdir -p dist
name="LinuxARM64-MHGURecomp.$version.tar.gz"
printf 'TEST STUB ONLY - NOT A GAME ARCHIVE\\n' > "dist/$name"
(cd dist && sha256sum "$name" > SHA256SUMS)
if [[ ${TEST_CHECKSUM_FAIL:-0} == 1 ]]; then
  printf 'corruption\\n' >> "dist/$name"
fi
if [[ ${TEST_WRONG_MANIFEST:-0} == 1 ]]; then
  printf 'other test output\\n' > dist/other
  (cd dist && sha256sum other > SHA256SUMS)
fi
"""


class UpdateBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCRIPT.is_file():
            raise AssertionError(f"missing implementation: {SCRIPT}")
        for program in ("git", "bash", "flock", "sha256sum"):
            if not shutil.which(program):
                raise unittest.SkipTest(f"requires {program}")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="mhgu update test ")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.home = self.base / "home"
        self.home.mkdir()
        self.bin = self.base / "bin"
        self.bin.mkdir()
        docker = self.bin / "docker"
        docker.write_text(DOCKER_STUB)
        docker.chmod(0o755)
        self.remote = self.base / "authorized remote.git"
        self.seed = self.base / "seed"
        self.checkout = self.base / "checkout with spaces"
        self.game = self.base / "dump with spaces"
        (self.game / "exefs").mkdir(parents=True)
        (self.game / "romfs").mkdir()
        (self.game / "exefs/main").write_text("test fixture, not game data\n")
        (self.game / "exefs/sdk").write_text("test fixture, not game data\n")
        self.config = self.base / "gitconfig"
        self.env = os.environ.copy()
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE",
                     "DOCKER_HOST", "DOCKER_CONTEXT", "CONTAINER_ENGINE",
                     "MHGU_UPDATE_REEXEC_SHA", "MHGU_UPDATE_LOCK_FILE"):
            self.env.pop(name, None)
        self.env.update(
            HOME=str(self.home),
            PATH=f"{self.bin}:{os.environ['PATH']}",
            GIT_CONFIG_GLOBAL=str(self.config),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_TERMINAL_PROMPT="0",
            LC_ALL="C",
        )
        self.git("config", "--global", "user.name", "Offline Test")
        self.git("config", "--global", "user.email", "offline@example.invalid")
        self.git("config", "--global", "protocol.file.allow", "always")
        # The script still accepts only the fixed HTTPS URL. Git's test-local
        # rewrite points that one authorized URL at this real local fixture.
        self.git("config", "--global", f"url.{self.remote.as_uri()}.insteadOf", ORIGIN)
        self.git("init", "--bare", "--initial-branch=master", str(self.remote))
        self.git("clone", str(self.remote), str(self.seed))
        (self.seed / "tools").mkdir()
        (self.seed / "tools/build-linux-release.sh").write_text(WRAPPER_STUB)
        (self.seed / "update-build-arm64.sh").write_bytes(SCRIPT.read_bytes())
        (self.seed / ".gitignore").write_text(".linux-release/\ndist/\n")
        (self.seed / "tracked.txt").write_text("base\n")
        self.commit_seed("initial fixture")

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=check,
        )

    def commit_seed(self, message):
        self.git("add", "-A", cwd=self.seed)
        self.git("commit", "-m", message, cwd=self.seed)
        self.git("push", "origin", "master", cwd=self.seed)

    def clone(self):
        self.git("clone", ORIGIN, str(self.checkout))

    def command(self, *, repo=None, game=None, version="20260101.010203", extra=(),
                script=None):
        command = [
            "bash", str(script or SCRIPT),
            "--repo-dir", str(repo or self.checkout),
            "--game", str(game or self.game),
        ]
        if version is not None:
            command += ["--version", version]
        return command + list(extra)

    def run_script(self, *, env=None, **kwargs):
        return subprocess.run(
            self.command(**kwargs), env={**self.env, **(env or {})}, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout)

    def assert_refused(self, result, pattern):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertRegex(result.stdout.lower(), pattern)
        self.assertFalse((self.checkout / ".linux-release/test-args").exists())

    def test_help(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "--help"], env=self.env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5,
        )
        self.assert_ok(result)
        for text in ("--repo-dir", "--game", "--jobs", "--version",
                     "/home/vesnine/Descargas/MHGU dump/", ORIGIN):
            self.assertIn(text, result.stdout)
        self.assertFalse(self.checkout.exists())

    def test_new_clone_paths_with_spaces_and_explicit_jobs(self):
        result = self.run_script(extra=("--jobs", "3"))
        self.assert_ok(result)
        self.assertEqual(
            (self.checkout / ".linux-release/test-args").read_text().splitlines(),
            ["--game", str(self.game), "--version", "20260101.010203", "--jobs", "3"],
        )
        self.assertIn(
            str(self.checkout / "dist/LinuxARM64-MHGURecomp.20260101.010203.tar.gz"),
            result.stdout,
        )
        self.assertEqual(self.git("config", "--get", "remote.origin.url",
                                  cwd=self.checkout).stdout.strip(), ORIGIN)
        self.assertTrue(list((self.checkout / ".linux-release/update-logs").glob("*.log")))

    def test_default_checkout_jobs_and_utc_numeric_version(self):
        result = self.run_script(repo=self.home / "MHGURecomp-arm64-test", version=None)
        self.assert_ok(result)
        args = (self.home / "MHGURecomp-arm64-test/.linux-release/test-args"
                ).read_text().splitlines()
        self.assertRegex(args[3], r"^[0-9]{8}\.[0-9]{6}$")
        self.assertEqual(args[-1], "2")
        # Exercise the actual default path, not just its equivalent argument.
        command = ["bash", str(SCRIPT), "--game", str(self.game), "--version", "2"]
        result = subprocess.run(command, env=self.env, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=20)
        self.assert_ok(result)

    def test_occupied_path_preserved(self):
        self.checkout.mkdir()
        private = self.checkout / "private"
        private.write_text("keep")
        self.assert_refused(self.run_script(), r"occupied|not.*repository|not.*checkout")
        self.assertEqual(private.read_text(), "keep")

    def test_occupied_file_preserved(self):
        self.checkout.write_text("keep")
        self.assert_refused(self.run_script(), r"occupied|not.*directory")
        self.assertEqual(self.checkout.read_text(), "keep")

    def test_existing_repository_root_required(self):
        self.clone()
        subdir = self.checkout / "subdirectory"
        subdir.mkdir()
        result = self.run_script(repo=subdir)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_clean_fast_forward(self):
        self.clone()
        (self.seed / "tracked.txt").write_text("remote update\n")
        self.commit_seed("remote update")
        self.assert_ok(self.run_script())
        self.assertEqual((self.checkout / "tracked.txt").read_text(), "remote update\n")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.checkout).stdout,
                         self.git("rev-parse", "master", cwd=self.remote).stdout)

    def test_clean_no_change_and_private_cache_preserved(self):
        self.clone()
        for relative in (".linux-release/private-cache", ".linux-release/old.log",
                         "dist/prior.tar.gz", "untracked-private-dump"):
            path = self.checkout / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("private sentinel\n")
        self.assert_ok(self.run_script())
        for relative in (".linux-release/private-cache", ".linux-release/old.log",
                         "dist/prior.tar.gz", "untracked-private-dump"):
            self.assertEqual((self.checkout / relative).read_text(), "private sentinel\n")

    def test_dirty_tracked_refused(self):
        self.clone()
        (self.checkout / "tracked.txt").write_text("private edit\n")
        self.assert_refused(self.run_script(), r"tracked|dirty|changes")
        self.assertEqual((self.checkout / "tracked.txt").read_text(), "private edit\n")

    def test_staged_refused(self):
        self.clone()
        (self.checkout / "tracked.txt").write_text("staged edit\n")
        self.git("add", "tracked.txt", cwd=self.checkout)
        self.assert_refused(self.run_script(), r"tracked|dirty|changes")

    def test_unmerged_refused(self):
        self.clone()
        self.git("checkout", "-b", "side", cwd=self.checkout)
        (self.checkout / "tracked.txt").write_text("side\n")
        self.git("commit", "-am", "side", cwd=self.checkout)
        self.git("checkout", "master", cwd=self.checkout)
        (self.checkout / "tracked.txt").write_text("master\n")
        self.git("commit", "-am", "master", cwd=self.checkout)
        self.git("merge", "side", cwd=self.checkout, check=False)
        self.assert_refused(self.run_script(), r"merge|tracked|dirty|changes")
        self.assertTrue(self.git("ls-files", "-u", cwd=self.checkout).stdout)

    def test_wrong_branch_refused(self):
        self.clone()
        self.git("checkout", "-b", "private", cwd=self.checkout)
        self.assert_refused(self.run_script(), r"branch|master")

    def test_detached_head_refused(self):
        self.clone()
        self.git("checkout", "--detach", cwd=self.checkout)
        self.assert_refused(self.run_script(), r"branch|master|detached")

    def test_wrong_remote_refused(self):
        self.clone()
        self.git("remote", "set-url", "origin", "https://example.invalid/other.git",
                 cwd=self.checkout)
        self.assert_refused(self.run_script(), r"origin|remote")

    def test_multiple_remote_urls_refused(self):
        self.clone()
        self.git("config", "--add", "remote.origin.url", ORIGIN, cwd=self.checkout)
        self.assert_refused(self.run_script(), r"origin|remote")

    def test_origin_optional_git_suffix(self):
        self.clone()
        without_suffix = ORIGIN.removesuffix(".git")
        self.git("config", "--global", f"url.{self.remote.as_uri()}.insteadOf",
                 without_suffix)
        self.git("remote", "set-url", "origin", without_suffix, cwd=self.checkout)
        self.assert_ok(self.run_script())

    def test_untracked_update_collision_keeps_private_file(self):
        self.clone()
        private = self.checkout / "new-file"
        private.write_text("private content\n")
        (self.seed / "new-file").write_text("remote content\n")
        self.commit_seed("add colliding file")
        self.assert_refused(self.run_script(), r"fast-forward|untracked|overwritten")
        self.assertEqual(private.read_text(), "private content\n")

    def local_commit(self):
        (self.checkout / "local-only").write_text("private local commit\n")
        self.git("add", "local-only", cwd=self.checkout)
        self.git("commit", "-m", "unpublished", cwd=self.checkout)
        return self.git("rev-parse", "HEAD", cwd=self.checkout).stdout

    def test_local_ahead_refused_without_loss(self):
        self.clone()
        original = self.local_commit()
        self.assert_refused(self.run_script(), r"local|unpublished|diverg")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.checkout).stdout, original)

    def test_divergent_local_commits_refused(self):
        self.clone()
        original = self.local_commit()
        (self.seed / "remote-only").write_text("remote\n")
        self.commit_seed("remote divergence")
        self.assert_refused(self.run_script(), r"local|unpublished|diverg")
        self.assertEqual(self.git("rev-parse", "HEAD", cwd=self.checkout).stdout, original)

    def test_invalid_dump_refused(self):
        (self.game / "exefs/sdk").unlink()
        self.assert_refused(self.run_script(), r"dump|exefs")
        self.assertFalse(self.checkout.exists())

    def test_docker_inaccessible_refused(self):
        self.assert_refused(self.run_script(env={"TEST_DOCKER_FAIL": "1"}),
                            r"docker")
        self.assertFalse(self.checkout.exists())

    def test_remote_docker_refused(self):
        self.assert_refused(
            self.run_script(env={"TEST_DOCKER_ENDPOINT": "tcp://example.invalid:2375"}),
            r"docker|socket|local",
        )

    def test_missing_requirement_refused_without_installing(self):
        # Real utility symlinks, not command doubles. Deliberately omit tee.
        for name in ("git", "bash", "flock", "tar", "realpath", "sha256sum",
                     "date", "uname", "mkdir", "mktemp"):
            (self.bin / name).symlink_to(shutil.which(name))
        result = self.run_script(env={"PATH": str(self.bin)})
        self.assert_refused(result, r"missing required command: tee")
        self.assertFalse(self.checkout.exists())

    def test_build_error_survives_tee(self):
        self.clone()
        (self.checkout / "dist").mkdir()
        (self.checkout / "dist/SHA256SUMS").write_text("prior manifest\n")
        result = self.run_script(env={"TEST_BUILD_FAIL": "1"})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("test build failed", result.stdout)
        self.assertNotIn("improperly formatted", result.stdout)
        logs = list((self.checkout / ".linux-release/update-logs").glob("*.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("test build failed", logs[0].read_text())
        self.assertEqual((self.checkout / "dist/SHA256SUMS").read_text(),
                         "prior manifest\n")

    def test_checksum_failure_refused(self):
        result = self.run_script(env={"TEST_CHECKSUM_FAIL": "1"})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("FAILED", result.stdout)
        self.assertNotIn("Archive:", result.stdout)

    def test_unrelated_checksum_manifest_refused(self):
        result = self.run_script(env={"TEST_WRONG_MANIFEST": "1"})
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("Archive:", result.stdout)

    def test_invalid_options_refused(self):
        for extra in (("--jobs", "0"), ("--jobs", "-1"), ("--version", "bad"),
                      ("--repo", "https://example.invalid"), ("--game",)):
            with self.subTest(extra=extra):
                result = self.run_script(extra=extra)
                self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.checkout.exists())

    def test_untrusted_reentry_marker_refused(self):
        result = self.run_script(env={"MHGU_UPDATE_REEXEC_SHA": "a" * 40})
        self.assert_refused(result, r"re-entry")
        self.assertFalse(self.checkout.exists())

    def test_self_update_reexec_under_held_lock(self):
        self.clone()
        target = self.seed / "update-build-arm64.sh"
        target.write_text(target.read_text().replace(
            "#!/usr/bin/env bash\n",
            "#!/usr/bin/env bash\nprintf 'UPDATED_SCRIPT_ACTIVE\\n'\n", 1))
        self.commit_seed("self update fixture")
        result = self.run_script(script=self.checkout / "update-build-arm64.sh")
        self.assert_ok(result)
        self.assertEqual(result.stdout.count("UPDATED_SCRIPT_ACTIVE"), 1, result.stdout)
        self.assertIn("Re-executing", result.stdout)
        self.assertNotIn("another update", result.stdout.lower())
        self.assertIn("20260101.010203",
                      (self.checkout / ".linux-release/test-args").read_text())

    def test_standalone_self_update_after_clone(self):
        target = self.seed / "update-build-arm64.sh"
        target.write_text(target.read_text().replace(
            "#!/usr/bin/env bash\n",
            "#!/usr/bin/env bash\nprintf 'CLONED_SCRIPT_ACTIVE\\n'\n", 1))
        self.commit_seed("new downloaded-script logic")
        result = self.run_script()
        self.assert_ok(result)
        self.assertEqual(result.stdout.count("CLONED_SCRIPT_ACTIVE"), 1, result.stdout)
        self.assertIn("Re-executing", result.stdout)

    def test_persistent_sibling_lock_is_not_truncated(self):
        lock = Path(f"{self.checkout}.update-build-arm64.lock")
        lock.write_text("private lock-file sentinel\n")
        self.assert_ok(self.run_script())
        self.assertEqual(lock.read_text(), "private lock-file sentinel\n")

    def test_failed_build_releases_lock_for_next_run(self):
        first = self.run_script(env={"TEST_BUILD_FAIL": "1"})
        self.assertEqual(first.returncode, 23, first.stdout)
        self.assert_ok(self.run_script())

    def test_concurrency_including_clone_bootstrap(self):
        entered = self.base / "entered"
        release = self.base / "release"
        env = {**self.env, "TEST_BUILD_ENTERED": str(entered),
               "TEST_BUILD_RELEASE": str(release)}
        first = subprocess.Popen(
            self.command(), env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 10
            while not entered.exists() and first.poll() is None:
                if time.monotonic() > deadline:
                    self.fail("first build never entered test wrapper")
                time.sleep(0.05)
            self.assertTrue(entered.exists())
            result = self.run_script()
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertRegex(result.stdout.lower(), r"another|lock|active")
            alias = self.base / "checkout alias"
            alias.symlink_to(self.checkout, target_is_directory=True)
            result = self.run_script(repo=alias)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertRegex(result.stdout.lower(), r"another|lock|active")
        finally:
            release.touch()
            output, _ = first.communicate(timeout=10)
        self.assertEqual(first.returncode, 0, output)
        self.assert_ok(self.run_script())


if __name__ == "__main__":
    unittest.main()
