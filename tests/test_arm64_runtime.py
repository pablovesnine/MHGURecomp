"""Public ARM64 ABI regressions, without a dump or generated game code."""

import hashlib
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


def build_values(*arguments):
    names = ("GENFLAGS", "RTFLAGS", "IMGUIFLAGS", "GAMELIB_ID")
    recipe = "probe:\n\t@printf '%s\\n' " + " ".join(
        f"'{name}=$({name})'" for name in names) + "\n"
    result = subprocess.run(
        ["make", "-s", "-f", "Makefile", "-f", "-", "probe", *arguments],
        input=recipe, cwd=ROOT, text=True, capture_output=True, check=True,
    )
    return dict(line.split("=", 1) for line in result.stdout.splitlines())


class Arm64AbiTests(unittest.TestCase):
    def test_linux_defaults_and_launcher_exclude_retired_products(self):
        source = (ROOT / "runtime/config.c").read_text()
        declaration = source.split("static const char DEFAULT_INI[] =", 1)[1]
        declaration = declaration.split("\nvoid config_path(", 1)[0]
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "default-ini"
            subprocess.run(
                ["clang", "-x", "c", "-o", str(executable), "-"],
                input="#include <stdio.h>\nconst char ini[] =" + declaration +
                      "\nint main(void) { fputs(ini, stdout); }\n",
                text=True, capture_output=True, check=True,
            )
            ini = subprocess.check_output([executable], text=True)
        for residue in ("[Android]", "ShowBattery", "GameFolder", "%APPDATA%",
                        "mhgurecomp-updater"):
            self.assertNotIn(residue, ini)
        self.assertIn("ignored", ini.lower())
        panel = (ROOT / "runtime/settings_panel.cpp").read_text()
        self.assertNotIn('add_choice(r, "updates"', panel)
        launcher = (ROOT / "runtime/ui.c").read_text().split(
            "static void install_launcher(void)", 1)[1].split(
                "static void set_window_icon(void)", 1)[0]
        self.assertNotIn("mhgurecomp-updater", launcher)

    def test_picker_api_header_is_self_contained(self):
        for language in ("c", "c++"):
            with self.subTest(language=language):
                subprocess.run(
                    ["clang", "-Werror", "-fsyntax-only", "-x", language,
                     "-Iruntime", "-"],
                    input='#include "app_actions.h"\n', cwd=ROOT,
                    text=True, capture_output=True, check=True,
                )

    def test_partial_arc_fixtures_and_required_cross_target(self):
        self.assertIn("test-arcmerge", (ROOT / "tools/docker/build.sh").read_text())
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("tests/test_arcmerge.c", makefile)
        self.assertIn("$(TEST_RUNNER) $(O)/arc-test/test-arcmerge", makefile)
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "arc-test"
            subprocess.run(
                ["clang", "-O2", "-Wall", "-Wextra", "-Werror", "-fsigned-char",
                 "-Iruntime", "tests/test_arcmerge.c", "runtime/arcmerge.c",
                 "-o", str(executable)], cwd=ROOT, check=True,
            )
            subprocess.run([executable], check=True, capture_output=True)

    def test_own_c_and_cpp_and_generated_code_use_signed_char(self):
        for alias in ("arm64", "aarch64"):
            values = build_values(f"TARGET_ARCH={alias}")
            for name in ("GENFLAGS", "RTFLAGS", "IMGUIFLAGS"):
                with self.subTest(alias=alias, flags=name):
                    self.assertIn("-fsigned-char", shlex.split(values[name]))

    def test_signed_char_flag_changes_real_unsigned_char_compilation(self):
        values = build_values()
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "char-test"
            for name in ("GENFLAGS", "RTFLAGS", "IMGUIFLAGS"):
                # ARM's unsigned default is modelled on the host. The selected
                # build flags must actually restore the expected semantics.
                flags = [
                    flag for flag in shlex.split(values[name])
                    if flag in ("-fsigned-char", "-funsigned-char")
                ]
                subprocess.run(
                    ["clang", "-x", "c", "-funsigned-char", *flags,
                     "-o", str(executable), "-"],
                    input="int main(void) { return (char)255 < 0 ? 0 : 1; }\n",
                    text=True, check=True,
                )
                with self.subTest(flags=name):
                    self.assertEqual(subprocess.run([executable]).returncode, 0)

    def test_arm_guest_base_fits_39_bit_address_space(self):
        result = subprocess.run(
            ["clang", "-dM", "-E", "-x", "c", "-D__aarch64__",
             "-Iruntime", "runtime/cpu.h"],
            cwd=ROOT, text=True, capture_output=True, check=True,
        )
        definition = next(line for line in result.stdout.splitlines()
                          if line.startswith("#define GUEST_BASE "))
        value = int(definition.split()[2].removesuffix("ull"), 16)
        self.assertEqual(value, 64 * 1024**3)
        self.assertLess(value + 4 * 1024**3, 1 << 39)

    def test_runtime_and_game_identity_cover_abi_inputs(self):
        values = build_values()
        source = (ROOT / "Makefile").read_text()
        inputs = source.split("GAMELIB_SRCS :=", 1)[1].split(
            "GAMELIB_ID :=", 1)[0].replace("\\\n", " ").split()
        digest = hashlib.sha256()
        for path in inputs:
            digest.update((ROOT / path).read_bytes())
        digest.update((values["GENFLAGS"] + "\n").encode())
        self.assertEqual(values["GAMELIB_ID"], digest.hexdigest()[:16])
        self.assertIn("runtime/cpu.h", inputs)

    def test_real_abi_probe_is_required_by_cross_validation(self):
        source = (ROOT / "tools/docker/build.sh").read_text()
        self.assertIn("test-arm64-abi", source)
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("tests/test_arm64_abi.c", makefile)
        self.assertIn("$(TEST_RUNNER) $(O)/abi-test/runtime", makefile)
        self.assertIn("$(TEST_RUNNER) $(O)/abi-test/generated", makefile)

    def test_fault_probe_uses_actual_guest_base(self):
        source = (ROOT / "tests/test_linux_fault.c").read_text()
        self.assertIn('#include "cpu.h"', source)
        self.assertIn("const uint64_t base = GUEST_BASE;", source)
        self.assertIn("UINT32_MAX", source)

    def test_differential_harness_matches_char_semantics(self):
        source = (ROOT / "tools/test_lift.py").read_text()
        self.assertIn("'-fsigned-char'", source)


if __name__ == "__main__":
    unittest.main()
