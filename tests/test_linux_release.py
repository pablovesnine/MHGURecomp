"""Container interface tests. The engine and dump files are explicit test fixtures."""
import fnmatch
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

# This fixture records arguments. It does not build images or compile game code.
ENGINE = r"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys
import subprocess

args = sys.argv[1:]
with open(os.environ["ENGINE_LOG"], "a") as stream:
    stream.write(json.dumps(args) + "\n")
while args and args[0].startswith("--"):
    option = args.pop(0)
    if option == "--host":
        args.pop(0)
if args[0] == "context":
    print(os.environ.get("ENGINE_ENDPOINT", "unix:///test/docker.sock"))
elif args[0] == "info":
    if Path(sys.argv[0]).name == "podman":
        print("crun" if any("OCIRuntime" in a for a in args) else
              os.environ.get("ENGINE_ROOTLESS", "true"))
    else:
        print('["name=rootless"]' if os.environ.get("ENGINE_ROOTLESS") == "true" else "[]")
elif args[:2] == ["image", "inspect"]:
    if os.environ.get("ENGINE_MISSING") == "true" and not Path(os.environ["ENGINE_LOG"] + ".built").exists():
        raise SystemExit(1)
    rev = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    print("sha256:" + "a" * 64, "linux", os.environ.get("ENGINE_ARCH", "amd64"),
          os.environ.get("ENGINE_REVISION", rev))
elif args[0] == "pull":
    if os.environ.get("ENGINE_PULL_EXIT", "1") == "0":
        Path(os.environ["ENGINE_LOG"] + ".built").touch()
    raise SystemExit(int(os.environ.get("ENGINE_PULL_EXIT", "1")))
elif args[0] == "build":
    context = Path(args[-1])
    assert (context / "docker/Dockerfile").read_text() == "tracked tools fixture\n"
    assert not (context / "private.txt").exists()
    Path(os.environ["ENGINE_LOG"] + ".built").touch()
elif args[0] == "run":
    raise SystemExit(int(os.environ.get("ENGINE_EXIT", "0")))
"""


def load_module(name):
    spec = importlib.util.spec_from_file_location(
        name, ROOT / "tools/docker" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "checkout with spaces"
        self.repo.mkdir()
        (self.repo / "tools/docker").mkdir(parents=True)
        shutil.copy(ROOT / "tools/build-linux-release.sh", self.repo / "tools")
        shutil.copy(ROOT / "tools/upstream-version.sh", self.repo / "tools")
        (self.repo / "tools/docker/Dockerfile").write_text("tracked tools fixture\n")
        (self.repo / ".gitignore").write_text(
            ".linux-release/\ndist/\n")
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Test Fixture",
                 "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Explicit test fixture")
        self.upstream = self.root / "trusted upstream.git"
        subprocess.run(["git", "clone", "--bare", str(self.repo), str(self.upstream)],
                       check=True, capture_output=True)
        self.git("--git-dir=" + str(self.upstream), "tag", "0.12.0")
        self.pin_version("0.12.0")
        self.git("config", f"url.{self.upstream}.insteadOf",
                 "https://github.com/morerokk/MHGURecomp.git")
        self.game = self.root / "private dump fixture"
        (self.game / "exefs").mkdir(parents=True)
        (self.game / "romfs").mkdir()
        for name in ("main", "sdk"):
            (self.game / "exefs" / name).write_text("test fixture, not game code")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for name in ("docker", "podman"):
            engine = self.bin / name
            engine.write_text(ENGINE)
            engine.chmod(0o755)
        self.log = self.root / "engine.jsonl"
        self.env = os.environ.copy()
        for name in ("DOCKER_HOST", "DOCKER_CONTEXT", "CONTAINER_HOST",
                     "CONTAINER_CONNECTION", "CONTAINER_ENGINE"):
            self.env.pop(name, None)
        self.env.update(PATH=str(self.bin) + os.pathsep + self.env["PATH"],
                        ENGINE_LOG=str(self.log))

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True,
                              capture_output=True, text=True)

    def pin_version(self, version):
        oid = self.git("--git-dir=" + str(self.upstream), "rev-parse",
                       "refs/tags/" + version).stdout.strip()
        base = self.git("rev-parse", "HEAD").stdout.strip()
        state = {
            "schema": "1", "algorithm": "release-base-v1",
            "repository": "morerokk/MHGURecomp", "release_id": "1",
            "version": version, "tag": version, "tag_oid": oid, "commit": oid,
            "published_at": "2026-01-01T00:00:00Z", "fork_base": base,
            "migration_merge": base, "migration_source": base,
        }
        (self.repo / ".github/maintenance").mkdir(parents=True, exist_ok=True)
        (self.repo / ".github/maintenance/upstream-release.tsv").write_text(
            "".join(key + "\t" + value + "\n" for key, value in state.items()))
        self.git("add", ".github/maintenance/upstream-release.tsv")
        self.git("-c", "user.name=Test Fixture",
                 "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Pin fixture stable release " + version)

    def run_script(self, *args):
        return subprocess.run(
            ["bash", str(self.repo / "tools/build-linux-release.sh"), *args],
            cwd=self.repo, env=self.env, capture_output=True, text=True)

    def release(self, *args):
        return self.run_script("--game", str(self.game), "--version", "0.12.0",
                               *args)

    def commands(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def run_command(self):
        return next(command for command in self.commands() if "run" in command)

    def test_0151_network_checks_use_a_second_offline_container(self):
        self.git("--git-dir=" + str(self.upstream), "tag", "0.15.1")
        self.pin_version("0.15.1")
        result = self.run_script("--check", "--version", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        runs = [c for c in self.commands() if "run" in c]
        self.assertEqual(len(runs), 2)
        self.assertNotIn("--network", runs[0])
        offline = runs[1]
        self.assertEqual(offline[offline.index("--network") + 1], "none")
        self.assertEqual(offline[-5], "network-check")
        self.assertEqual(runs[0][-6], offline[-6])
        self.assertFalse(any("/game" in part for c in runs for part in c))

    def test_release_paths_context_and_private_mount(self):
        (self.repo / "untracked-private.txt").write_text("must not be exported")
        result = self.release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(any("build" in c or "pull" in c for c in self.commands()))
        inspected = next(c for c in self.commands() if "image" in c)
        revision = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertEqual(inspected[-1],
                         "ghcr.io/pablovesnine/mhgurecomp-builder:" + revision)
        command = self.run_command()
        self.assertIn(str(self.game) + ":/game:ro,z", command)
        self.assertIn("--user", command)
        self.assertEqual(command[-6:], ["sha256:" + "a" * 64, "release",
                                      "0.12.0", "2", revision,
                                      "sha256:" + "a" * 64])
        exported = list((self.repo / ".linux-release").glob("*/src"))
        self.assertEqual(len(exported), 1)
        self.assertTrue((exported[0] / "tools/build-linux-release.sh").is_file())
        self.assertFalse((exported[0] / "untracked-private.txt").exists())

    def test_check_has_no_game_or_output_mount(self):
        # Check mode must work offline and with shallow CI history.
        shutil.rmtree(self.upstream)
        (self.repo / ".git/shallow").write_text(self.git("rev-parse", "HEAD").stdout)
        result = self.run_script("--check", "--version", "0", "--jobs", "3",
                                 "--image", "mhgurecomp-builder:ci", "--skip-image-build")
        self.assertEqual(result.returncode, 0, result.stderr)
        command = self.run_command()
        self.assertFalse(any(":/game:" in value or ":/out:" in value
                             for value in command))
        self.assertEqual(command[-5:-2], ["check", "0", "3"])
        self.assertFalse(any("build" in c for c in self.commands()))

    def test_missing_image_falls_back_to_tracked_tools(self):
        (self.repo / "tools/private.txt").write_text("untracked private fixture")
        self.env["ENGINE_MISSING"] = "true"
        result = self.release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("pull" in c for c in self.commands()))
        build = next(c for c in self.commands() if "build" in c)
        revision = self.git("rev-parse", "HEAD").stdout.strip()
        self.assertIn("SOURCE_REVISION=" + revision, build)
        self.assertIn("mhgurecomp-builder:" + revision, build)
        self.assertTrue(build[-1].endswith("/tools"))
        self.assertNotIn(":latest", " ".join(sum(self.commands(), [])))

    def test_available_remote_image_is_pulled_without_rebuild(self):
        self.env.update(ENGINE_MISSING="true", ENGINE_PULL_EXIT="0")
        result = self.release()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("pull" in c for c in self.commands()))
        self.assertFalse(any("build" in c for c in self.commands()))

    def test_rebuild_forces_local_build(self):
        result = self.release("--rebuild-image")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any("build" in c for c in self.commands()))
        self.assertFalse(any("pull" in c for c in self.commands()))

    def test_explicit_image_fallback_and_rebuild_keep_requested_name(self):
        self.env["ENGINE_MISSING"] = "true"
        result = self.release("--image", "fixture-builder:debug")
        self.assertEqual(result.returncode, 0, result.stderr)
        build = next(c for c in self.commands() if "build" in c)
        self.assertIn("fixture-builder:debug", build)
        self.assertNotIn("ghcr.io/", " ".join(sum(self.commands(), [])))

    def test_cache_separates_version_and_jobs(self):
        self.assertEqual(self.release().returncode, 0)
        self.assertEqual(self.release("--jobs", "3").returncode, 0)
        self.git("--git-dir=" + str(self.upstream), "tag", "0.13.1")
        self.pin_version("0.13.1")
        self.assertEqual(self.release("--version", "0.13.1").returncode, 0)
        self.assertEqual(len(list((self.repo / ".linux-release").glob("*/src"))), 3)

    def test_release_resolves_version_without_override(self):
        result = self.run_script("--game", str(self.game))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_command()[-5:-3], ["release", "0.12.0"])
        self.assertIn("LinuxARM64-MHGURecomp.0.12.0.tar.gz", result.stdout)

    def test_new_tag_without_pinned_release_does_not_change_build_version(self):
        self.git("--git-dir=" + str(self.upstream), "tag", "99.0")
        result = self.run_script("--game", str(self.game))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.run_command()[-5:-3], ["release", "0.12.0"])

    def test_overrides_must_match_upstream_before_engine(self):
        for version in ("1", "20261101235959", "0.12.0-test"):
            with self.subTest(version=version):
                result = self.release("--version", version)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("version", result.stderr)
                self.assertFalse(self.log.exists())

    def test_upstream_errors_fail_before_engine(self):
        shutil.rmtree(self.upstream)
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot query upstream", result.stderr)
        self.assertFalse(self.log.exists())

    def test_existing_build_lock_is_required(self):
        import fcntl
        work = self.repo / ".linux-release"
        work.mkdir()
        with (work / "lock").open("w") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("another Linux build", result.stderr)
        self.assertFalse(any("run" in c for c in self.commands()))

    def test_wrong_host_is_rejected_before_engine(self):
        uname = self.bin / "uname"
        uname.write_text('#!/bin/sh\nif [ "$1" = -s ]; then echo Linux; else echo aarch64; fi\n')
        uname.chmod(0o755)
        self.assertNotEqual(self.release().returncode, 0)
        self.assertFalse(self.log.exists())

    def test_wrong_image_platform_revision_or_missing_skip_image_fail(self):
        for key, value in (("ENGINE_ARCH", "arm64"), ("ENGINE_REVISION", "0" * 40),
                           ("ENGINE_MISSING", "true")):
            with self.subTest(key=key):
                self.env[key] = value
                self.assertNotEqual(self.release("--skip-image-build").returncode, 0)
                self.assertFalse(any("run" in c for c in self.commands()))
                self.env.pop(key)

    def test_stale_cached_sources_do_not_survive_export(self):
        self.assertEqual(self.release().returncode, 0)
        exported = next((self.repo / ".linux-release").glob("*/src"))
        (exported / "stale-source.c").write_text("explicit stale-source fixture")
        self.assertEqual(self.release().returncode, 0)
        self.assertFalse((exported / "stale-source.c").exists())

    def test_bad_arguments_and_incomplete_dump(self):
        for args in ((), ("--version",), ("--unknown",),
                     ("--version", "0.12.0-test"),
                     ("--version", "0.12.0", "--jobs", "0"),
                     ("--check", "mips", "--version", "0.12.0"),
                     ("--check", "aarch64", "--version", "0"),
                     ("--check", "--version", "0", "--game", str(self.game)),
                     ("--check", "--version", "0", "--skip-image-build",
                      "--rebuild-image")):
            with self.subTest(args=args):
                self.assertNotEqual(self.run_script(*args).returncode, 0)
        (self.game / "exefs/sdk").unlink()
        self.assertNotEqual(self.release().returncode, 0)
        self.assertFalse(self.log.exists())

    def test_dirty_tracked_sources_fail_before_engine(self):
        shutil.rmtree(self.upstream)
        with (self.repo / "tools/build-linux-release.sh").open("a") as stream:
            stream.write("\n# Explicit dirty-file fixture.\n")
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tracked changes", result.stderr)
        self.assertNotIn("cannot query upstream", result.stderr)
        self.assertFalse(self.log.exists())

    def test_untracked_resolver_is_not_executed(self):
        self.git("rm", "--cached", "tools/upstream-version.sh")
        self.git("-c", "user.name=Test Fixture",
                 "-c", "user.email=fixture@example.invalid",
                 "commit", "-qm", "Explicit missing tracked helper fixture")
        result = self.release()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("commit the build tools", result.stderr)
        self.assertFalse(self.log.exists())

    def test_engine_failure_propagates(self):
        self.env["ENGINE_EXIT"] = "23"
        self.assertEqual(self.release().returncode, 23)

    def test_rootless_docker_does_not_override_user(self):
        self.env["ENGINE_ROOTLESS"] = "true"
        self.assertEqual(self.release().returncode, 0)
        self.assertNotIn("--user", self.run_command())

    def test_podman_is_not_supported(self):
        self.env["CONTAINER_ENGINE"] = "podman"
        self.assertNotEqual(self.release().returncode, 0)
        self.assertFalse(self.log.exists())

    def test_remote_docker_is_rejected(self):
        self.env["ENGINE_ENDPOINT"] = "ssh://remote.example.invalid"
        self.assertNotEqual(self.release().returncode, 0)
        self.assertFalse(any("run" in c for c in self.commands()))

    def test_explicit_context_takes_precedence_over_docker_host(self):
        self.env["DOCKER_CONTEXT"] = "remote-fixture"
        self.env["DOCKER_HOST"] = "unix:///test/local.sock"
        self.env["ENGINE_ENDPOINT"] = "tcp://remote.example.invalid:2375"
        self.assertNotEqual(self.release().returncode, 0)


class ImageTests(unittest.TestCase):
    def test_generation_guard_is_on_the_real_packaging_path(self):
        script = (ROOT / "tools/docker/build.sh").read_text()
        guard = script.index('make "${args[@]}" check-generated')
        record = script.index('python3 tools/dist.py record')
        package = script.index('python3 tools/dist.py "$build"')
        self.assertLess(script.index('rm -f "$build/build-metadata.json"'), guard)
        self.assertLess(guard, record)
        self.assertLess(record, package)
        self.assertIn("dist: check-generated", (ROOT / "Makefile").read_text())

    def test_new_upstream_checks_are_version_gated_not_file_gated(self):
        script = (ROOT / "tools/docker/build.sh").read_text()
        block = re.search(
            r"upstream_tests=\(\)\n(.*?)\n(?=if \[\[ \$mode == release)",
            script, re.S)
        self.assertIsNotNone(block)
        for version, expected in (
            ("0.14.0", ""), ("0.14.2", ""),
            ("0.14.3", "test-engine-modules\ntest-cheats"),
            ("0.14.10", "test-engine-modules\ntest-cheats"),
            ("0.15.0", "test-engine-modules\ntest-cheats\ntest-interp\ntest-villagehub"),
            ("0.15.1", "test-engine-modules\ntest-cheats\ntest-interp\ntest-villagehub\ntest-crossplay-bins"),
            ("0.15.2", "test-engine-modules\ntest-cheats\ntest-interp\ntest-villagehub\ntest-crossplay-bins\ntest-textlayout"),
            ("0.15.3", "test-engine-modules\ntest-cheats\ntest-interp\ntest-villagehub\ntest-crossplay-bins\ntest-textlayout\ntest-ldn-direct\ntest-villagehub-demo"),
            ("0.15.4", "test-engine-modules\ntest-cheats\ntest-interp\ntest-villagehub\ntest-crossplay-bins\ntest-textlayout\ntest-ldn-direct\ntest-villagehub-demo\ntest-fastload\ntest-hpscale\ntest-mousecam"),
            ("0.16.0", "test-engine-modules\ntest-cheats\ntest-interp\ntest-villagehub\ntest-crossplay-bins\ntest-textlayout\ntest-ldn-direct\ntest-villagehub-demo\ntest-fastload\ntest-hpscale\ntest-mousecam"),
        ):
            result = subprocess.run(
                ["bash", "-euo", "pipefail", "-c",
                 'version=0\nsource_version=$1\nargs=()\n' + block.group(0) +
                 '\nprintf "%s\\n" "${upstream_tests[@]}"\n'
                 'printf "%s\\n" "${args[@]}" >&2', "-", version],
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(result.stdout.strip(), expected, version)
            expected_flags = []
            pin = tuple(map(int, version.split(".")))
            flags = []
            for minimum, flag in (
                ((0, 15, 0), "FORGE_MENU"), ((0, 15, 1), "MOUSE_CAPTURE"),
                ((0, 15, 2), "TEXT_HDR"), ((0, 15, 3), "DIRECT"),
            ):
                if pin >= minimum:
                    flags.append("-DMHGU_TEST_" + flag)
                    expected_flags.append("PANEL_TEST_FLAGS=" + " ".join(flags))
            self.assertEqual(result.stderr.strip(), "\n".join(expected_flags), version)
        self.assertIn('test-arcmerge "${upstream_tests[@]}"', script)
        self.assertIn(
            'engine-module-test/t/"{good,hidden,badapi,noapi,declines,notamodule}',
            script,
        )
        self.assertNotIn("-f tests/test_engine_module.c", script)

    def test_check_mode_reads_pin_even_when_version_argument_is_zero(self):
        script = (ROOT / "tools/docker/build.sh").read_text()
        function = re.search(r"read_source_version\(\) \{.*?\n\}", script, re.S)
        self.assertIsNotNone(function)
        self.assertIn("source_version=$(read_source_version)", script)
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / ".github/maintenance/upstream-release.tsv"
            state.parent.mkdir(parents=True)
            for content, success in (
                ("schema\t1\nversion\t0.14.3\n", True),
                ("schema\t1\nversion\t0.14.0\n", True),
                ("schema\t1\n", False),
                ("version\tnot-a-version\n", False),
                ("version\t0.14.0\nversion\t0.14.3\n", False),
            ):
                state.write_text(content)
                result = subprocess.run(
                    ["bash", "-euo", "pipefail", "-c",
                     'die() { exit 2; }\n' + function.group(0) +
                     "\nread_source_version"], cwd=tmp,
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode == 0, success, content)
                if success:
                    self.assertEqual(result.stdout.strip(),
                                     content.split("version\t")[1].strip())

    def test_public_tools_directories_are_traversable_after_the_last_copy(self):
        dockerfile = (ROOT / "tools/docker/Dockerfile").read_text()
        last_copy = dockerfile.rindex("\nCOPY ")
        permissions = dockerfile.index(
            "chmod 0755 /opt/mhgu /opt/mhgu/docker")
        self.assertGreater(permissions, last_copy)
        self.assertNotIn("chmod -R", dockerfile)

    def test_public_image_inputs_have_explicit_nonroot_read_permissions(self):
        dockerfile = (ROOT / "tools/docker/Dockerfile").read_text()
        copies = [shlex.split(line) for line in dockerfile.splitlines()
                  if line.startswith("COPY ")]
        self.assertEqual(len(copies), 3)
        copied = set()
        for instruction in copies:
            self.assertEqual(instruction[1], "--chmod=0644")
            copied.update(instruction[2:-1])
        self.assertEqual(copied, {
            "requirements.txt", "docker/prepare-sysroot.sh",
            "docker/normalize-sysroot.py", "docker/build.sh",
            "docker/check-elf.py",
        })

    def test_ffmpeg_cross_build_selects_native_host_compiler(self):
        for arch in ("aarch64",):
            for compiler in ("clang", "clang-18"):
                with self.subTest(arch=arch, compiler=compiler):
                    result = subprocess.run(
                        ["make", "--no-print-directory", "-s",
                         "--eval=print-ffmpeg-host-flags:;"
                         '@printf "%s\\n" $(FFMPEG_TARGET_FLAGS)',
                         "print-ffmpeg-host-flags",
                         "HOST_ARCH=x86_64", "TARGET_ARCH=" + arch,
                         "CC=" + compiler],
                        cwd=ROOT, check=True, capture_output=True, text=True)
                    flags = result.stdout.splitlines()
                    if arch == "aarch64":
                        self.assertIn("--host-cc=" + compiler, flags)
                        self.assertNotIn("--host-cc=" + compiler +
                                         " --target=aarch64-linux-gnu", flags)
                    else:
                        self.assertFalse(any(
                            flag.startswith("--host-cc=") for flag in flags))

    def test_context_allowlist(self):
        # The allowlist has no glob exceptions. No project tree enters the image.
        patterns = (ROOT / "tools/.dockerignore").read_text().splitlines()
        self.assertEqual(patterns[0], "**")
        allowed = {p[1:] for p in patterns[1:] if p.startswith("!")}
        self.assertEqual(allowed, {
            "requirements.txt", "docker/", "docker/Dockerfile",
            "docker/prepare-sysroot.sh", "docker/normalize-sysroot.py",
            "docker/build.sh", "docker/check-elf.py"})
        for private in ("generated/main/part.c", "../data/exefs/main",
                        "docker/game.nsp", "venv/bin/python"):
            self.assertFalse(any(fnmatch.fnmatch(private, p) for p in allowed))

    def test_sysroot_links_stay_inside_root(self):
        module = load_module("normalize-sysroot")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "usr/lib").mkdir(parents=True)
            (root / "usr/lib/target").write_text("link fixture")
            (root / "usr/lib/absolute").symlink_to("/usr/lib/target")
            (root / "usr/lib/chain").symlink_to("absolute")
            module.normalize(root)
            self.assertEqual((root / "usr/lib/chain").resolve(),
                             root / "usr/lib/target")
            (root / "usr/lib/escape").symlink_to("../../../../outside")
            with self.assertRaises(ValueError):
                module.normalize(root)
        with self.assertRaises(ValueError):
            module.normalize("/")

    def test_elf_rejects_wrong_machine_before_symbol_tool(self):
        module = load_module("check-elf")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "header-only-fixture"
            path.write_bytes(b"\x7fELF" + bytes(60))
            with self.assertRaises(ValueError):
                module.check(path, "aarch64")

    def test_image_and_entrypoint_do_not_copy_or_package_dump(self):
        dockerfile = (ROOT / "tools/docker/Dockerfile").read_text()
        script = (ROOT / "tools/docker/build.sh").read_text()
        self.assertNotIn("COPY .", dockerfile)
        self.assertNotIn("--platform=linux/arm64", dockerfile)
        self.assertNotIn(" dist ", script)
        self.assertIn('make -j1 "${args[@]}" licenses pipelist', script)
        self.assertNotIn("build_target x86_64", script)
        self.assertNotIn("mhgurecomp-updater", script)
        self.assertNotIn("if ! make", script)
        self.assertNotIn("::warning::", script)
        self.assertIn("test-settings-panel", script)
        self.assertIn("org.opencontainers.image.revision", dockerfile)

    def test_packager_rejects_missing_game_library(self):
        spec = importlib.util.spec_from_file_location(
            "dist", ROOT / "tools/dist.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp)
            for name in ("mhgurecomp",):
                (build / name).write_bytes(
                    b"explicit test fixture, not executable code")
            with self.assertRaises(SystemExit):
                module.files(tmp, "linux")


if __name__ == "__main__":
    unittest.main(verbosity=2)
