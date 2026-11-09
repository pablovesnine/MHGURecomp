"""Portable 0.15.4 contracts, using production text and synthetic memory only."""
import contextlib
import importlib.util
import io
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def function(source, signature):
    """Extract one complete production function without copying its semantics."""
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    return source[start:end]


def compiler_check(source, execute=True):
    def run(args):
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "fixture.c"
        binary = Path(tmp) / "fixture"
        path.write_text(source)
        # The cross check is freestanding: no target sysroot or GPU dependency.
        run(
            ["clang", "--target=aarch64-linux-gnu", "-march=armv8-a",
             "-ffreestanding", "-fsigned-char", "-Wall", "-Wextra", "-Werror",
             "-fsyntax-only", str(path)],
        )
        if execute:
            run(
                ["clang", "-std=gnu11", "-O1", "-g", "-fsigned-char",
                 "-fno-strict-aliasing", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all",
                 "-fno-omit-frame-pointer", str(path), "-o", str(binary)],
            )
            run([str(binary)])


class Portable0154Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            "portable_imgui_thunks", ROOT / "tools/imgui_thunks.py")
        cls.thunks = importlib.util.module_from_spec(spec)
        with patch.object(sys, "argv", [str(ROOT / "tools/imgui_thunks.py")]):
            spec.loader.exec_module(cls.thunks)

    def test_compiler_harness_rejects_undefined_behavior(self):
        with self.assertRaisesRegex(AssertionError, "runtime error: signed integer overflow"):
            compiler_check("int main(void) { volatile int n = 2147483647; "
                           "volatile int result = n + 1; (void)result; return 0; }")

    def test_production_hook_fixtures_pass_native_sanitizers(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("fastload", "hpscale", "mousecam"):
                with self.subTest(hook=name):
                    binary = Path(tmp) / name
                    for command in (
                        ["clang", "-std=gnu11", "-O1", "-g", "-Wall", "-Wextra",
                         "-Werror", "-fsigned-char", "-fno-strict-aliasing",
                         "-ffp-contract=off", "-fsanitize=address,undefined",
                         "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                         "-I" + str(ROOT / "runtime"),
                         str(ROOT / f"tests/test_{name}.c"),
                         "-pthread", "-lm", "-o", str(binary)],
                        [str(binary)],
                    ):
                        result = subprocess.run(command, capture_output=True, text=True)
                        self.assertEqual(result.returncode, 0,
                                         result.stdout + result.stderr)

    def test_generated_thunks_are_current_without_rewriting_tracked_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "thunks.inc"
            old = self.thunks.OUT
            try:
                self.thunks.OUT = output
                with contextlib.redirect_stdout(io.StringIO()):
                    self.thunks.main()
                self.assertEqual(output.read_bytes(),
                                 (ROOT / "runtime/forge_imgui_thunks.inc").read_bytes())
            finally:
                self.thunks.OUT = old

    def test_draw_cursor_abi_and_production_mirror_roundtrip(self):
        gs, hs, fields = self.thunks.fields_table("ImDrawList")
        self.assertEqual(next(f for f in fields if f[:2] == (48, 64)),
                         (48, 64, 0, "data", None))
        self.assertEqual(next(f for f in fields if f[:2] == (52, 72)),
                         (52, 72, 0, "data", None))
        self.assertEqual(next(f for f in fields if f[:2] == (44, 56))[3:],
                         ("obj", "ImDrawListSharedData"))
        source = (ROOT / "runtime/forge_imgui.c").read_text()
        generated = (ROOT / "runtime/forge_imgui_thunks.inc").read_text()
        table = re.search(r"static const MField mf_ImDrawList\[\] = \{.*?\n\};",
                          generated, re.S).group(0)
        # No ImGui dependency: only the actual mirror leaves are exercised.
        prefix = r"""
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
extern void *memcpy(void *, const void *, size_t);
extern int memcmp(const void *, const void *, size_t);
extern void abort(void);
#define CHECK(x) do { if (!(x)) abort(); } while (0)
static uint8_t arena[4096];
#define GUEST_BASE ((uintptr_t)arena)
static void *mapped(uint32_t a) { CHECK(a < sizeof arena); return arena + a; }
#define G2H(a) mapped(a)
#define GP(a) ((a) ? G2H(a) : NULL)
enum { MF_RAW, MF_SIZE, MF_STR, MF_OBJ, MF_DATA, MF_FN };
typedef struct { uint32_t g, h, n; uint8_t kind; uint16_t type; } MField;
typedef struct { const char *name; uint32_t gsize, hsize; const MField *f; uint32_t nf; bool hot; } MType;
typedef struct { void *host; uint32_t guest; uint16_t type; uint8_t flags; uint8_t *shadow; } Mirror;
static uint32_t ig_str_out(const char *s) { CHECK(!s); return 0; }
static uint32_t mirror_of(const void *h, int t, bool r) {
    (void)t; (void)r; CHECK(!h); return 0;
}
static Mirror *find_guest(uint32_t g) { CHECK(!g); return NULL; }
"""
        functions = "\n".join(function(source, signature) for signature in (
            "static bool in_guest(", "static uint32_t h2g_quiet(",
            "static void pull(Mirror *m) {", "static void push(Mirror *m) {"))
        types = (table + "\nstatic const MType mtypes[] = "
                 f'{{{{"ImDrawList", {gs}, {hs}, mf_ImDrawList, '
                 "sizeof mf_ImDrawList / sizeof *mf_ImDrawList, false}};\n")
        main = r"""
int main(void) {
    _Static_assert(sizeof(void *) == 8, "64-bit host pointers");
    _Static_assert(sizeof(uint32_t) == 4, "32-bit guest pointers");
    uint8_t host[1024] = {0}, shadow[1024] = {0};
    Mirror m = {host, 1024, 0, 0, shadow};
    const MType *t = &mtypes[0];
    CHECK(t->hsize <= sizeof host && t->gsize <= sizeof shadow);
    CHECK(!h2g_quiet(NULL));
    CHECK(!h2g_quiet((void *)(GUEST_BASE - 1)));
    CHECK(!h2g_quiet((void *)(GUEST_BASE + 0x100000000ull)));
    CHECK(h2g_quiet((void *)(GUEST_BASE + 0xffffffffull)) == 0xffffffffu);
    for (uint32_t i = 1; i < 20000; i++) {
        uint32_t g = 1 + i % 512, read = 0;
        void *p = arena + g, *got = NULL;
        memcpy(host + 64, &p, sizeof p);
        memcpy(host + 72, &p, sizeof p);
        pull(&m);
        memcpy(&read, arena + m.guest + 48, 4);
        CHECK(read == g);
        memcpy(&read, arena + m.guest + 52, 4);
        CHECK(read == g);
        g++;
        memcpy(arena + m.guest + 48, &g, 4);
        push(&m);
        memcpy(&got, host + 64, sizeof got);
        CHECK(got == arena + g);
        memcpy(&got, host + 72, sizeof got);
        CHECK(got == p);
    }
    void *outside = (void *)(GUEST_BASE - 1), *got = outside;
    memcpy(host + 64, &outside, sizeof outside);
    pull(&m);
    uint32_t read;
    memcpy(&read, arena + m.guest + 48, 4);
    CHECK(read == 0);
    read = 5;
    memcpy(arena + m.guest + 48, &read, 4);
    push(&m);
    read = 0;
    memcpy(arena + m.guest + 48, &read, 4);
    push(&m);
    memcpy(&got, host + 64, sizeof got);
    CHECK(got == NULL);
    return 0;
}
"""
        compiler_check(prefix + types + functions + main)

    def test_front_face_uniform_and_shader_conversion_are_paired(self):
        translate = (ROOT / "runtime/nvn/maxwell/translate.c").read_text()
        execute = (ROOT / "runtime/nvn/vulkan/exec.c").read_text()
        block = translate.split("else if (addr == 0x3FC) {", 1)[1].split(
            "else if (addr == 0x2E0", 1)[0]
        self.assertIn("c->uses_front_facing = true", block)
        self.assertIn("c->uses_rscale = true", block)
        self.assertIn("(front_facing ? uint(int(rscale[66][0])) : 0u)", block)
        self.assertIn("(front_facing ? 0xFFFFFFFFu : 0u)", block)
        self.assertIn("c->uses_front_facing ? 67", translate)
        producer = re.search(
            r"float rs\[67\]\[4\];\s*for \(int k.*?rs\[66\]\[0\] = -1;",
            execute, re.S).group(0)
        self.assertNotIn("memset(rs[66]", execute)
        compiler_check(r"""
#include <stdint.h>
extern void abort(void);
#define CHECK(x) do { if (!(x)) abort(); } while (0)
int main(void) {
    _Static_assert(sizeof(float) == 4, "shader float ABI");
""" + producer + r"""
    CHECK(sizeof rs == 67 * 16);
    CHECK(rs[66][0] == -1.0f);
    CHECK((uint32_t)(int32_t)rs[66][0] == UINT32_MAX);
    for (int k = 0; k < 67; k++) {
        CHECK(rs[k][1] == 1 && rs[k][2] == 0 && rs[k][3] == 0);
        if (k != 66) CHECK(rs[k][0] == 1);
    }
    return 0;
}
""")

    def test_fastload_is_built_and_registered_without_desktop_android_calls(self):
        makefile = (ROOT / "Makefile").read_text()
        self.assertIn("$(wildcard runtime/hle/*.c)", makefile)
        self.assertIn("fastload_init();", (ROOT / "runtime/main.c").read_text())
        self.assertIn("void fastload_init(void);", (ROOT / "runtime/mods.h").read_text())
        linux = (ROOT / "runtime/platform/linux.c").read_text()
        # The shared header itself must remain usable on an ARM64 desktop.
        compiler_check(f'#include "{ROOT / "runtime/android_files.h"}"\n'
                       'int main(void) { return 0; }\n', execute=False)
        for marker in ("void android_first_start(void);", "android_first_start();"):
            pos = linux.index(marker)
            guard = linux.rfind("#ifdef __ANDROID__", 0, pos)
            self.assertGreater(guard, linux.rfind("#endif", 0, pos))


if __name__ == "__main__":
    unittest.main()
