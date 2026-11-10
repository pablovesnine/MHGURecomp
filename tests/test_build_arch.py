"""ARM64-only build regressions; ELF headers are explicit test fixtures."""
import argparse
import ast
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REVISION = "1" * 40
IMAGE = "sha256:" + "2" * 64


def probe(*args):
    names = ("TARGET_ARCH", "TARGET_FLAGS", "CMAKE_TARGET_FLAGS",
             "FFMPEG_TARGET_FLAGS", "GENARCH", "GAMELIB_ID", "B", "O",
             "CC", "CXX", "PKG_CONFIG_LIBDIR", "PKG_CONFIG_SYSROOT_DIR",
             "FFMPEG_CC", "RT_SRC", "GEN_ID")
    recipe = "probe:\n\t@printf '%s\\n' " + " ".join(
        f"'{name}=$({name})'" for name in names) + "\n"
    return subprocess.run(["make", "-s", "-f", "Makefile", "-f", "-",
                           "probe", *args], input=recipe, cwd=ROOT,
                          capture_output=True, text=True)


def elf_header(machine=183):
    # Deliberate header-only fixture, not executable code or game contents.
    header = bytearray(64)
    header[:7] = b"\x7fELF\x02\x01\x01"
    header[16] = 3
    header[18:20] = machine.to_bytes(2, "little")
    header[20] = 1
    header[52] = 64
    return header


def load_dist():
    spec = importlib.util.spec_from_file_location("dist", ROOT / "tools/dist.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BuildTests(unittest.TestCase):
    def test_0160_hooks_are_mandatory_and_cross_compiled(self):
        entry = (ROOT / "tools/docker/build.sh").read_text()
        names = ("hitsync", "chat", "itembar", "combowin", "villagehub-text")
        self.assertIn("upstream_tests+=(" +
                      " ".join(f"test-{name}" for name in names) + ")", entry)
        self.assertIn("MHGU_TEST_LAGCOMP", entry)
        for name in names:
            self.assertIn(f"/work/obj-aarch64/{name}-test/test-{name}", entry)
            self.assertNotIn(f"-f tests/test_{name.replace('-', '_')}.c", entry)
        result = subprocess.run(
            ["make", "-n", *(f"test-{name}" for name in names),
             "HOST_ARCH=x86_64", "SYSROOT=/test/sysroot", "O=/test/objects",
             "TEST_RUNNER=qemu-aarch64 -L /test/sysroot"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        compiles = [line for line in result.stdout.splitlines()
                    if line.startswith("clang ")]
        self.assertEqual(len(compiles), len(names))
        for name, command in zip(names, compiles):
            for flag in ("--target=aarch64-linux-gnu", "--sysroot=/test/sysroot",
                         "-march=armv8-a", "-fsigned-char",
                         "-fno-strict-aliasing", "-ffp-contract=off"):
                self.assertIn(flag, command)
            self.assertIn(f"tests/test_{name.replace('-', '_')}.c", command)
            self.assertNotIn("-mavx", command)
            self.assertIn("qemu-aarch64 -L /test/sysroot "
                          f"/test/objects/{name}-test/test-{name}", result.stdout)

    def test_0154_hook_checks_are_required_with_target_abi(self):
        makefile = (ROOT / "Makefile").read_text()
        entry = (ROOT / "tools/docker/build.sh").read_text()
        names = ("fastload", "hpscale", "mousecam")
        for name in names:
            self.assertIn(f"test-{name}:", makefile)
            self.assertIn(f"$(TEST_RUNNER) $(O)/{name}-test/test-{name}", makefile)
            self.assertIn(f"/work/obj-aarch64/{name}-test/test-{name}", entry)
            self.assertNotIn(f"-f tests/test_{name}.c", entry)
        self.assertIn("upstream_tests+=(test-fastload test-hpscale test-mousecam)", entry)
        result = subprocess.run(
            ["make", "-n", *(f"test-{name}" for name in names),
             "HOST_ARCH=x86_64", "SYSROOT=/test/sysroot", "O=/test/objects",
             "TEST_RUNNER=qemu-aarch64 -L /test/sysroot"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        compiles = [line for line in result.stdout.splitlines()
                    if line.startswith("clang ")]
        self.assertEqual(len(compiles), len(names))
        for command in compiles:
            for flag in ("--target=aarch64-linux-gnu", "--sysroot=/test/sysroot",
                         "-march=armv8-a", "-fsigned-char",
                         "-fno-strict-aliasing"):
                self.assertIn(flag, command)
            self.assertNotIn("-mavx", command)

    def test_0153_direct_and_demo_checks_are_required(self):
        makefile = (ROOT / "Makefile").read_text()
        entry = (ROOT / "tools/docker/build.sh").read_text()
        for name in ("ldn-direct", "villagehub-demo"):
            self.assertIn(f"test-{name}:", makefile)
            self.assertIn(f"$(TEST_RUNNER) $(O)/{name}-test/test-{name}", makefile)
            self.assertIn(f"/work/obj-aarch64/{name}-test/test-{name}", entry)
        self.assertIn("upstream_tests+=(test-ldn-direct test-villagehub-demo)", entry)
        self.assertIn("MHGU_TEST_DIRECT", entry)
        self.assertNotIn("-f tests/test_ldn_direct.c", entry)

    def test_0152_text_dependencies_and_public_checks_are_required(self):
        recipe = "probe:\n\t@printf '%s\\n' '$(LDFLAGS)'\n"
        result = subprocess.run(
            ["make", "-s", "-f", "Makefile", "-f", "-", "probe",
             "SYSROOT=/test/sysroot", "SDL3=system", "SHADERC=system",
             "ZSTD=system"],
            input=recipe, cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn("-lz", shlex.split(result.stdout))
        for path in ("tools/docker/Dockerfile", "tools/docker/prepare-sysroot.sh"):
            self.assertIn("zlib1g-dev", (ROOT / path).read_text())
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("tests/frame_counter_fixture.c", makefile)
        self.assertIn("test-textlayout:", makefile)
        self.assertIn("$(TEST_RUNNER) $(O)/textlayout-test/test-textlayout", makefile)
        entry = (ROOT / "tools/docker/build.sh").read_text()
        self.assertIn("0.15.2", entry)
        self.assertIn("upstream_tests+=(test-textlayout)", entry)
        self.assertIn("/work/obj-aarch64/textlayout-test/test-textlayout", entry)

    def test_0151_cpu_metadata_has_no_x86_requirement_on_arm64(self):
        state = dict(line.split("\t", 1) for line in
                     (ROOT / ".github/maintenance/upstream-release.tsv")
                     .read_text().splitlines())
        if tuple(map(int, state["version"].split("."))) < (0, 15, 1):
            self.skipTest("CPU metadata starts at source pin 0.15.1")
        source = (ROOT / "tools/gamelib_entry.c").read_text()
        declaration = re.search(
            r"GAMELIB_EXPORT const uint32_t mhgugame_cpu_needs =.*?;",
            source, re.S)
        self.assertIsNotNone(declaration)
        result = subprocess.run(
            ["clang", "--target=aarch64-linux-gnu", "-march=armv8-a",
             "-E", "-P", "-x", "c", "-"],
            input=declaration.group(0), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"mhgugame_cpu_needs = 0\s*;")
        loader = (ROOT / "runtime/gamelib.c").read_text()
        guard = loader.index("#if defined(__x86_64__) || defined(_M_X64)")
        end = loader.index("#else", guard)
        self.assertIn('__builtin_cpu_supports("avx2")', loader[guard:end])
        self.assertNotIn("__builtin_cpu_", loader[end:])

    def test_crossplay_dependency_recipes_keep_the_target_abi(self):
        # Empty prerequisites let the old pin inspect future compile recipes.
        extra = (
            "runtime/net/ryusrv/server.cpp:\n"
            "runtime/net/ryusrv.h:\n"
            "third_party/enet/unix.c:\n"
        )
        result = subprocess.run(
            ["make", "-n", "-f", "Makefile", "-f", "-",
             "/test/objects/rt/net/ryusrv/server.o",
             "/test/objects/enet/unix.o", "HOST_ARCH=x86_64",
             "SYSROOT=/test/sysroot", "O=/test/objects",
             "SDL3=system", "SHADERC=system", "ZSTD=system"],
            input=extra, cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        compiles = [line for line in result.stdout.splitlines()
                    if line.startswith(("clang ", "clang++ "))]
        self.assertEqual(len(compiles), 2)
        for command in compiles:
            for flag in ("--target=aarch64-linux-gnu",
                         "--sysroot=/test/sysroot", "-fsigned-char"):
                self.assertIn(flag, command)
            self.assertNotIn("-mavx", command)
        self.assertIn("-std=c++20", compiles[0])
        self.assertIn("-DHAS_POLL", compiles[1])

    def test_zstd_is_verified_cross_compiled_and_packaged(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "zstd-1.5.7.tar.gz"
            for cached in (False, True):
                with self.subTest(cached=cached):
                    if cached:
                        # Make never executes this explicit public cache fixture.
                        archive.write_text("cached-file dry-run fixture\n")
                    # Inspect the whole recipe graph, not cache freshness.
                    result = subprocess.run(
                        ["make", "-B", "-n", "build/licenses/zstd.txt",
                         "HOST_ARCH=x86_64", "SYSROOT=/test/sysroot",
                         "O=/test/objects", f"ZSTD_TAR={archive}",
                         "SDL3=system", "SHADERC=system"],
                        cwd=ROOT, capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for token in (
                        "tools/fetch-verified.sh", "zstd-1.5.7.tar.gz",
                        "eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3",
                        "--target=aarch64-linux-gnu", "--sysroot=/test/sysroot",
                        "-fsigned-char", "-DZSTD_DISABLE_ASM", "llvm-ar rcs",
                        "src/LICENSE",
                    ):
                        self.assertIn(token, result.stdout)
        self.assertIn("zstd", load_dist().LICENSES)
        wrapper = (ROOT / "tools/build-linux-release.sh").read_text()
        self.assertIn("for library in ffmpeg sdl3 shaderc zstd;", wrapper)

    def test_village_target_cross_compiles_and_uses_runner(self):
        result = subprocess.run(
            ["make", "-n", "test-villagehub", "HOST_ARCH=x86_64",
             "SYSROOT=/test/sysroot", "O=/test/objects",
             "SDL3=system", "SHADERC=system",
             "TEST_RUNNER=qemu-aarch64 -L /test/sysroot"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for required in (
            "--target=aarch64-linux-gnu", "--sysroot=/test/sysroot",
            "-fuse-ld=lld", "-fsigned-char", "tests/test_villagehub.c",
            "-Wl,--gc-sections",
            "qemu-aarch64 -L /test/sysroot "
            "/test/objects/villagehub-test/test-villagehub",
        ):
            self.assertIn(required, result.stdout)

    def test_forge_panel_fixture_is_enabled_explicitly(self):
        fixture = (ROOT / "tests/test_settings_panel.cpp").read_text()
        for token in ("forge_plugin_titles", "forge_plugins_have",
                      "settings_panel_take_forge", 'selected("mods.forge")',
                      "MHGU_TEST_FORGE_MENU", "MHGU_TEST_MOUSE_CAPTURE",
                      "SDL_BUTTON_X1"):
            self.assertIn(token, fixture)
        result = subprocess.run(
            ["make", "-n", "test-settings-panel", "HOST_ARCH=x86_64",
             "SYSROOT=/test/sysroot", "SDL3=system", "SHADERC=system",
             "PANEL_TEST_FLAGS=-DMHGU_TEST_FORGE_MENU"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        command = next(line for line in result.stdout.splitlines()
                       if "tests/test_settings_panel.cpp" in line)
        self.assertIn("-DMHGU_TEST_FORGE_MENU", command)

    def test_interp_target_cross_compiles_and_uses_runner(self):
        result = subprocess.run(
            ["make", "-n", "test-interp", "HOST_ARCH=x86_64",
             "SYSROOT=/test/sysroot", "O=/test/objects",
             "SDL3=system", "SHADERC=system",
             "TEST_RUNNER=qemu-aarch64 -L /test/sysroot"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        for required in (
            "--target=aarch64-linux-gnu", "--sysroot=/test/sysroot",
            "-fuse-ld=lld", "-fsigned-char", "tests/test_interp.c",
            "runtime/interp.c", "runtime/neon.c", "runtime/simd_int.c",
            "-lm", "-pthread",
            "qemu-aarch64 -L /test/sysroot "
            "/test/objects/interp-test/test-interp",
        ):
            self.assertIn(required, result.stdout)

    def test_lift_predecoded_mode_preserves_target_and_runner_options(self):
        # Exercise real parser/selection/compiler expressions, not an NSO.
        tree = ast.parse((ROOT / "tools/test_lift.py").read_text())
        main = next(n for n in tree.body
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        parser = []
        for statement in main.body:
            if isinstance(statement, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "rng"
                for t in statement.targets
            ):
                break
            parser.append(statement)
        command = next(n for n in ast.walk(main)
                       if isinstance(n, ast.Assign) and any(
                           isinstance(t, ast.Name) and t.id == "cmd"
                           for t in n.targets))
        for option, function in (("--interp-ops", "interp_exec_op"),
                                 ("--interp", "interp_exec"), (None, None)):
            argv = ["test_lift.py", "/public-fixture", "0x200000",
                    "--cc", "clang --target=aarch64-linux-gnu "
                    "--sysroot=/test/sysroot -fuse-ld=lld",
                    "--genarch=-march=armv8-a",
                    "--runner", "qemu-aarch64 -L /test/sysroot"]
            if option:
                argv.append(option)
            env = dict(argparse=argparse, platform=SimpleNamespace(
                machine=lambda: "aarch64"), shlex=shlex, os=os,
                ROOT=str(ROOT), HERE=str(ROOT / "tools"), exe="/test/exe",
                work="/test/work")
            with patch.object(sys, "argv", argv):
                exec(compile(ast.Module(parser, type_ignores=[]),
                             "<lift-parser>", "exec"), env)
            self.assertEqual(env.get("interp_fn"), function)
            exec(compile(ast.Module([command], type_ignores=[]),
                         "<lift-command>", "exec"), env)
            for value in ("--target=aarch64-linux-gnu",
                          "--sysroot=/test/sysroot", "-fsigned-char",
                          "-fuse-ld=lld", "-march=armv8-a"):
                self.assertIn(value, env["cmd"])
            self.assertEqual(str(ROOT / "runtime/interp.c") in env["cmd"],
                             function is not None)
            self.assertEqual(shlex.split(env["args"].runner),
                             ["qemu-aarch64", "-L", "/test/sysroot"])

    def test_generation_identity_and_stale_guard(self):
        sources = ("tools/gen.py", "tools/lifter.py", "tools/neon.py",
                   "tools/nso.py", "runtime/hle/hle_symbols.txt")
        expected = hashlib.sha256(b"".join(
            (ROOT / path).read_bytes().replace(b"\r", b"")
            for path in sources)).hexdigest()[:16]
        self.assertIn("GEN_ID=" + expected + "\n", probe().stdout)
        with tempfile.TemporaryDirectory() as tmp:
            generated = Path(tmp) / "generated"
            generated.mkdir()
            stamp = generated / "gen.id"
            for value, success in (
                (None, False), ("stale\n", False),
                (expected + "\n", True),
            ):
                if value is not None:
                    stamp.write_text(value)
                result = subprocess.run(
                    ["make", "-s", "check-generated", f"GEN={generated}"],
                    cwd=ROOT, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode == 0, success, value)
                if not success:
                    self.assertIn("run make gen", result.stderr)

    def test_generation_records_only_complete_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated"
            generated.mkdir()
            stamp = generated / "gen.id"
            driver = root / "generator_fixture.py"
            # This public stand-in exercises Make's orchestration, not a dump.
            driver.write_text(
                "from pathlib import Path\nimport os, sys\n"
                "Path(sys.argv[5]).mkdir(parents=True, exist_ok=True)\n"
                "if sys.argv[2] == 'main' and os.getenv('FAIL_MAIN'):\n"
                "    raise SystemExit(7)\n"
            )
            command = ["make", "-s", "gen", f"GEN={generated}",
                       "GAME=/public-fixture", f"PY={sys.executable} {driver}"]
            stamp.write_text("must be invalidated\n")
            result = subprocess.run(
                command, cwd=ROOT, env=dict(os.environ, FAIL_MAIN="1"),
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(stamp.exists(), "failed generation kept an old stamp")
            result = subprocess.run(
                command, cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(stamp.is_file())
            subprocess.run(
                ["make", "-s", "check-generated", f"GEN={generated}"],
                cwd=ROOT, check=True, capture_output=True,
            )

    def test_defaults_and_arm64_alias(self):
        for args in ((), ("TARGET_ARCH=arm64",), ("TARGET_ARCH=aarch64",)):
            result = probe(*args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("TARGET_ARCH=aarch64\n", result.stdout)
            self.assertIn("B=build\nO=obj\n", result.stdout)
        self.assertIn("B=my-build\nO=my-objects\n",
                      probe("B=my-build", "O=my-objects").stdout)

    def test_cross_flags_and_identity(self):
        ids = []
        for root in ("/tmp/sysroot-one", "/tmp/sysroot-two"):
            result = probe("HOST_ARCH=x86_64", f"SYSROOT={root}")
            self.assertEqual(result.returncode, 0, result.stderr)
            for text in ("--target=aarch64-linux-gnu", f"--sysroot={root}",
                         "CMAKE_SYSTEM_PROCESSOR=aarch64", "--arch=aarch64",
                         "-DCMAKE_EXE_LINKER_FLAGS=-fuse-ld=lld",
                         "--extra-ldflags=-fuse-ld=lld",
                         f"PKG_CONFIG_SYSROOT_DIR={root}\n"):
                self.assertIn(text, result.stdout)
            self.assertNotIn("x86-64-v3", result.stdout)
            ids.append(next(x for x in result.stdout.splitlines()
                            if x.startswith("GAMELIB_ID=")))
        self.assertEqual(*ids)

    def test_unsupported_targets(self):
        for args in (("TARGET_ARCH=mips",), ("TARGET_ARCH=x86_64",),
                     ("TARGET_ARCH=amd64",), ("PLATFORM=windows",),
                     ("PLATFORM=android",), ("PLATFORM=darwin",)):
            with self.subTest(args=args):
                self.assertNotEqual(probe(*args).returncode, 0)

    def test_ffmpeg_native_host_compiler_and_target_flags(self):
        result = probe("HOST_ARCH=x86_64", "SYSROOT=/desktop/sysroot",
                       "CC=my-clang", "CXX=my-clang++")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--host-cc=my-clang", shlex.split(result.stdout))
        self.assertIn("FFMPEG_CC=my-clang --target=aarch64-linux-gnu",
                      result.stdout)
        self.assertIn("--sysroot=/desktop/sysroot", result.stdout)
        self.assertIn("CXX=my-clang++", result.stdout)
        self.assertIn("FFMPEG_CC=explicit-ffmpeg-cc\n",
                      probe("FFMPEG_CC=explicit-ffmpeg-cc").stdout)

    def test_updater_not_built_but_runtime_sha256_remains(self):
        text = (ROOT / "Makefile").read_text()
        self.assertIn("$(O)/updater/sha256.o", text)
        self.assertNotIn("$(UPDATER)", text)
        self.assertTrue((ROOT / "updater/sha256.c").is_file())
        self.assertTrue((ROOT / "updater/updater.h").is_file())
        self.assertTrue((ROOT / "runtime/platform/win_compat.h").is_file())

    def test_engine_modules_and_cheats_cross_compile_and_use_runner(self):
        result = subprocess.run(
            ["make", "-n", "example-engine-module", "test-engine-modules",
             "test-cheats", "HOST_ARCH=x86_64", "SYSROOT=/test/sysroot",
             "O=/test/objects", "SDL3=system", "SHADERC=system",
             "TEST_RUNNER=qemu-aarch64 -L /test/sysroot"],
            cwd=ROOT, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        compiles = [line for line in result.stdout.splitlines()
                    if line.startswith("clang ")]
        self.assertGreaterEqual(len(compiles), 8)
        for line in compiles:
            self.assertIn("--target=aarch64-linux-gnu", line)
            self.assertIn("--sysroot=/test/sysroot", line)
            self.assertIn("-fuse-ld=lld", line)
            self.assertIn("-fsigned-char", line)
        self.assertIn(
            "qemu-aarch64 -L /test/sysroot "
            "/test/objects/engine-module-test/test-engine-module",
            result.stdout,
        )
        self.assertIn(
            "cd /test/objects/settings-test && "
            "qemu-aarch64 -L /test/sysroot ./test-cheats", result.stdout,
        )
        self.assertNotIn(".dll", result.stdout)

    def test_only_shared_hash_remains_and_computes_correct_digest(self):
        self.assertEqual(
            {p.name for p in (ROOT / "updater").iterdir() if p.is_file()},
            {"sha256.c", "updater.h"},
        )
        # This is a public unit test vector, never game-derived content.
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "hash.c"
            source.write_text(
                '#include "updater/updater.h"\n#include <stdio.h>\n'
                'int main(void) { Sha256 s; char out[65]; sha256_init(&s);'
                'sha256_update(&s, "abc", 3); sha256_hex(&s, out);'
                'puts(out); return 0; }\n'
            )
            exe = str(Path(tmp) / "test")
            subprocess.run(
                ["clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                 "-I.", str(source), "updater/sha256.c", "-o", exe],
                cwd=ROOT, check=True,
            )
            result = subprocess.check_output([exe], text=True).strip()
            self.assertEqual(result, hashlib.sha256(b"abc").hexdigest())


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / "build"
        self.build.mkdir()
        (self.build / "licenses").mkdir()
        for name in ("LICENSE", "THIRD_PARTY_NOTICES", "FFmpeg", "SDL3", "shaderc", "zstd"):
            (self.build / "licenses" / (name + ".txt")).write_text("license fixture")
        (self.build / "pipelines.list").write_text("pipeline fixture")
        for name in ("mhgurecomp", "mhgugame.so"):
            (self.build / name).write_bytes(elf_header())
        # ObjDump is deliberately mocked for the header-only fixtures.
        self.bin = self.root / "bin"
        self.bin.mkdir()
        objdump = self.bin / "llvm-objdump"
        objdump.write_text(
            "#!/bin/sh\nprintf '%s\\n' \"${FIXTURE_SYMBOLS:-"
            "0000000000000000      DF *UND* 0000000000000000 "
            "(GLIBC_2.39) fixture_import}\"\n")
        objdump.chmod(0o755)
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.module = load_dist()
        self.record()

    def record(self):
        self.module.record_metadata(self.build, "1.2.3", REVISION, IMAGE,
                                    {"compiler": "explicit fixture compiler"})

    def command(self, *args):
        return subprocess.run([sys.executable, str(ROOT / "tools/dist.py"),
                               str(self.build), str(self.root / "out"),
                               "linux", "1.2.3", "--revision", REVISION,
                               "--image", IMAGE, *args],
                              env=self.env, capture_output=True, text=True)

    def test_only_arm64_package_and_no_private_files_or_updater(self):
        for name in ("mhgurecomp-updater", "settings.ini", "log.txt"):
            (self.build / name).write_text("must not ship")
        (self.build / "data/exefs").mkdir(parents=True)
        (self.build / "data/exefs/main").write_text("private fixture")
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        archive = self.root / "out/LinuxARM64-MHGURecomp.1.2.3.tar.gz"
        with tarfile.open(archive) as tar:
            top = "LinuxARM64-MHGURecomp/"
            self.assertEqual(tar.getmember(top + "mhgurecomp").mode, 0o755)
            self.assertEqual(tar.getmember(top + "build-metadata.json").mode, 0o644)
            self.assertTrue(tar.getmember(top + "licenses/THIRD_PARTY_NOTICES.txt"))
            for private in ("mhgurecomp-updater", "data/exefs/main",
                            "settings.ini", "log.txt"):
                self.assertNotIn(top + private, tar.getnames())
        self.assertNotIn("upload", result.stdout.lower())

    def test_missing_or_stale_metadata_is_rejected(self):
        path = self.build / "build-metadata.json"
        original = json.loads(path.read_text())
        for key, value in (("version", "9"), ("source_revision", "3" * 40),
                           ("builder_image", "sha256:" + "4" * 64),
                           ("architecture", "x86_64"), ("schema", 99)):
            path.write_text(json.dumps(dict(original, **{key: value})))
            self.assertNotEqual(self.command().returncode, 0, key)
        path.unlink()
        self.assertNotEqual(self.command().returncode, 0)

    def test_metadata_cannot_be_reused_for_modified_programs(self):
        for name in ("mhgurecomp", "mhgugame.so"):
            (self.build / name).write_bytes(elf_header() + b"modified fixture")
            self.assertNotEqual(self.command().returncode, 0, name)
            (self.build / name).write_bytes(elf_header())
        (self.build / "mhgugame.so").unlink()
        self.assertNotEqual(self.command().returncode, 0)

    def test_wrong_elf_and_abi_are_rejected_even_with_current_metadata(self):
        for content in (elf_header(62), elf_header()[:20]):
            (self.build / "mhgugame.so").write_bytes(content)
            self.record()
            self.assertNotEqual(self.command().returncode, 0)
        (self.build / "mhgugame.so").write_bytes(elf_header())
        self.record()
        for version in ("GLIBC_2.40", "GLIBCXX_3.4.33"):
            self.env["FIXTURE_SYMBOLS"] = (
                f"0000000000000000 DF *UND* 0000000000000000 "
                f"({version}) fixture_import")
            self.assertNotEqual(self.command().returncode, 0)

    def test_exported_versions_do_not_raise_import_ceiling(self):
        self.env["FIXTURE_SYMBOLS"] = (
            "0000000000001000 g DF .text 0000000000000010 "
            "GLIBC_2.40 fixture_export\n"
            "0000000000000000 DF *UND* 0000000000000000 "
            "(GLIBC_2.39) fixture_import")
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unsupported_cli_and_metadata_provenance(self):
        for args in (("--arch", "x86_64"), ("--arch", "mips"),
                     ("--bonus", "private-save"), ("--arch",)):
            self.assertNotEqual(self.command(*args).returncode, 0)
        for revision, image in (("latest", IMAGE), (REVISION, "builder:latest")):
            with self.assertRaises(ValueError):
                self.module.record_metadata(self.build, "1.2.3", revision,
                                            image, {"compiler": "fixture"})

    def test_metadata_write_is_atomic(self):
        old = (self.build / "build-metadata.json").read_bytes()
        with patch.object(self.module.os, "replace", side_effect=OSError("fixture")):
            with self.assertRaises(OSError):
                self.record()
        self.assertEqual((self.build / "build-metadata.json").read_bytes(), old)
        self.assertEqual(list(self.build.glob("*.part")), [])

    def test_missing_licenses_and_unsupported_platform_are_rejected(self):
        (self.build / "licenses/THIRD_PARTY_NOTICES.txt").unlink()
        self.assertNotEqual(self.command().returncode, 0)
        result = subprocess.run([sys.executable, str(ROOT / "tools/dist.py"),
                                 str(self.build), str(self.root), "windows", "1.2.3",
                                 "--revision", REVISION, "--image", IMAGE],
                                env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)

    def test_existing_archive_and_predictable_part_symlink_are_safe(self):
        out = self.root / "out"
        out.mkdir()
        name = "LinuxARM64-MHGURecomp.1.2.3.tar.gz"
        victim = self.root / "unrelated.txt"
        victim.write_text("do not change")
        (out / (name + ".part")).symlink_to(victim)
        self.assertEqual(self.command().returncode, 0)
        self.assertEqual(victim.read_text(), "do not change")
        old = (out / name).read_bytes()
        (self.build / "mhgugame.so").write_bytes(b"invalid fixture")
        self.assertNotEqual(self.command().returncode, 0)
        self.assertEqual((out / name).read_bytes(), old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
