"""Mandatory 0.16.0 production hooks, synthetic memory and fail-closed checks."""
import ast
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_0154_portable import compiler_check

ROOT = Path(__file__).resolve().parents[1]
STATE = dict(line.split("\t", 1) for line in
             (ROOT / ".github/maintenance/upstream-release.tsv")
             .read_text().splitlines())
ENABLED = tuple(map(int, STATE["version"].split("."))) >= (0, 16, 0)
CROSSPLAY = tuple(map(int, STATE["version"].split("."))) >= (0, 16, 1)


def build_fixture(name, target, extra=()):
    flags = (["-DMHGU_TEST_HITSYNC_CROSSPLAY=" + str(int(CROSSPLAY))]
             if name in ("hitsync", "hitsync_vsock") else [])
    return subprocess.run(
        ["clang", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
         "-fsigned-char", "-fno-strict-aliasing", "-ffp-contract=off",
         "-fsanitize=address,undefined", "-fno-sanitize-recover=all",
         "-fno-omit-frame-pointer", "-ffunction-sections", "-fdata-sections",
         "-Wl,--gc-sections", "-I" + str(ROOT / "runtime"),
         "-I" + str(ROOT / "runtime/hle"), *flags, *extra,
         str(ROOT / f"tests/test_{name}.c"), "-pthread", "-lm", "-o", str(target)],
        capture_output=True, text=True,
    )


@unittest.skipUnless(ENABLED, "Requires source pin 0.16.0, not package version")
class Portable0160Tests(unittest.TestCase):
    def test_real_hooks_pass_fail_closed_native_sanitizers(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("hitsync", "chat", "itembar", "combowin",
                         "villagehub_text"):
                with self.subTest(hook=name):
                    binary = Path(tmp) / name
                    result = build_fixture(name, binary)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(binary)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_known_upstream_limits_remain_explicit_expected_red_proofs(self):
        # These probes must fail for the recorded reason, never count as safe input.
        cases = (
            ("hitsync", "--red-active-drain", "observed_damage == 0"),
            ("chat", "--red-truncated-utf8", "AddressSanitizer: stack-buffer-overflow"),
            ("itembar", "--red-step-overflow", "runtime error: signed integer overflow"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for name, option, diagnostic in cases:
                with self.subTest(limit=name):
                    binary = Path(tmp) / name
                    result = build_fixture(name, binary)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(binary), option],
                                            capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(diagnostic, result.stderr)

    def test_combo_fixture_rejects_disabled_window_stop(self):
        source = (ROOT / "runtime/hle/combowin.c").read_text()
        anchor = "if (g_stop) return 0.0f;"
        self.assertIn(anchor, source)
        with tempfile.TemporaryDirectory() as tmp:
            mutated = Path(tmp) / "combowin.c"
            mutated.write_text(source.replace(anchor, "if (g_stop) return 1.0f;", 1))
            binary = Path(tmp) / "mutant"
            result = build_fixture("combowin", binary, (
                '-DMHGU_COMBOWIN_SOURCE="' + str(mutated) + '"',))
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("check failed", result.stderr)

    def test_generated_combo_patches_preserve_original_instruction_order(self):
        tree = ast.parse((ROOT / "tools/gen.py").read_text())
        patches = next(node.value for node in tree.body
                       if isinstance(node, ast.Assign) and any(
                           isinstance(t, ast.Name) and t.id == "PATCHES"
                           for t in node.targets))
        selected = {ast.literal_eval(key): ast.literal_eval(value)
                    for key, value in zip(patches.keys, patches.values)
                    if isinstance(key, ast.Tuple)
                    and ast.literal_eval(key) in (
                        ("main", 0x47ca38), ("main", 0x47cc58))}
        self.assertEqual(set(selected), {("main", 0x47ca38), ("main", 0x47cc58)})
        self.assertEqual(selected["main", 0x47ca38][0], 0xE1A06004)
        self.assertEqual(selected["main", 0x47cc58][0], 0xE1D910B0)
        prefix = r"""
#include <stdint.h>
extern void abort(void);
#define CHECK(x) do { if (!(x)) abort(); } while (0)
typedef struct { uint32_t r[16]; } Cpu;
static Cpu cpu, *c = &cpu;
static int phase;
static uint16_t memory = 0x1234;
#define LD16(a) (CHECK_LOAD(a))
static uint16_t CHECK_LOAD(uint32_t a) { CHECK(phase == 2 && a == 4); phase++; return memory; }
void combowin_begin(uint32_t a) { CHECK(a == 8 && c->r[6] == 8 && phase == 0); phase++; }
void combowin_end(uint32_t a) { CHECK(a == 8 && phase == 1); phase++; }
int main(void) {
    c->r[4] = 8; c->r[9] = 4;
"""
        compiler_check(prefix + selected["main", 0x47ca38][1] +
                       selected["main", 0x47cc58][1] +
                       "\nCHECK(phase == 3 && c->r[1] == memory); return 0;\n}\n")


@unittest.skipUnless(CROSSPLAY, "Requires source pin 0.16.1 or later")
class Crossplay0161Tests(unittest.TestCase):
    def test_actual_vsock_routing_native_sanitizers(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "vsock"
            for flags in ((), ("-DNDEBUG",)):
                result = build_fixture("hitsync_vsock", binary, flags)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([str(binary)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_crossplay_sender_and_echo_and_dispatch_mutations_rejected(self):
        cases = (
            ("hitsync", "hitsync", "MHGU_HITSYNC_SOURCE",
             "UDP_PORT, UDP_PORT, VPROTO_UDP",
             "UDP_PORT + 1, UDP_PORT, VPROTO_UDP",
             "p->src_port == 47318 && p->dst_port == 47318"),
            ("hitsync", "hitsync", "MHGU_HITSYNC_SOURCE",
             "h.slot < 4 && (int)h.slot != local_slot()", "h.slot < 4",
             "g_hello[1] == (MHGU_TEST_HITSYNC_CROSSPLAY ? 0 : clock_ns)"),
            ("hitsync", "hitsync", "MHGU_HITSYNC_SOURCE",
             " || (int)r.slot == local_slot()", "",
             "g_nq == (MHGU_TEST_HITSYNC_CROSSPLAY ? 0 : 1)"),
            ("hitsync_vsock", "vsock", "MHGU_VSOCK_SOURCE",
             "if (p->proto == VPROTO_UDP && p->dst_port == HITSYNC_UDP_PORT)",
             "if (false)",
             "nreceived == before + (hit && MHGU_TEST_HITSYNC_CROSSPLAY)"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            for fixture, leaf, define, old, new, diagnostic in cases:
                with self.subTest(mutation=old):
                    source = (ROOT / f"runtime/net/{leaf}.c").read_text()
                    self.assertEqual(source.count(old), 1)
                    mutated = Path(tmp) / f"{leaf}.c"
                    mutated.write_text(source.replace(old, new, 1))
                    binary = Path(tmp) / "mutant"
                    result = build_fixture(fixture, binary, (
                        "-DNDEBUG", "-I" + str(ROOT / "runtime/net"),
                        "-D" + define + '="' + str(mutated) + '"'))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    result = subprocess.run([str(binary)],
                                            capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(diagnostic, result.stderr)


if __name__ == "__main__":
    unittest.main()
