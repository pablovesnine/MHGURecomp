"""ARM64-only build regressions; ELF headers are explicit test fixtures."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REVISION = "1" * 40
IMAGE = "sha256:" + "2" * 64


def probe(*args):
    names = ("TARGET_ARCH", "TARGET_FLAGS", "CMAKE_TARGET_FLAGS",
             "FFMPEG_TARGET_FLAGS", "GENARCH", "GAMELIB_ID", "B", "O",
             "CC", "CXX", "PKG_CONFIG_LIBDIR", "PKG_CONFIG_SYSROOT_DIR",
             "FFMPEG_CC", "RT_SRC")
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
        for name in ("LICENSE", "THIRD_PARTY_NOTICES", "FFmpeg", "SDL3", "shaderc"):
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
