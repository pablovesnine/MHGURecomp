"""Mandatory source-pin >=0.16.1 contracts; no game, network, GPU or plugins.

Old preparation skips ONLY after the canonical release-state parser validates
its pin. Explicit audit: MHGU_0161_SOURCE=/exact/upstream/0.16.1/worktree.
Production C is included or extracted, never replaced with facsimile logic.
"""
import ast
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from test_0160_contracts import LIBC, function, functions, region, without_includes

ROOT = Path(__file__).resolve().parents[1]
PIN = "5c7cb615ebb51a7309437670f5766f4c47e2a133"
COMMON = ["-std=gnu11", "-fsigned-char", "-fno-strict-aliasing",
          "-ffp-contract=off", "-Wall", "-Wextra", "-Werror",
          "-Wno-unused-function", "-Wno-unused-variable",
          "-Wno-missing-field-initializers"]


def run_checked(command, **kwargs):
    result = subprocess.run(command, capture_output=True, text=True, timeout=60, **kwargs)
    if result.returncode:
        raise AssertionError(f"{' '.join(command)}\n{result.stdout}{result.stderr}")
    return result


def compile_and_run(path, directory, extra=(), cross_extra=(), failure=None):
    """Fail closed: both real AArch64 object emission and native ASan/UBSan.

    An expected mutant failure applies ONLY to native execution, never compiler
    failure. Every baseline and mutant must compile for both target families.
    """
    obj, binary = directory / "fixture.o", directory / "fixture"
    run_checked(["clang", *COMMON, "--target=aarch64-linux-gnu", "-march=armv8-a",
                 "-ffreestanding", *extra, *cross_extra, "-c", str(path), "-o", str(obj)])
    elf = obj.read_bytes()
    if elf[:4] != b"\x7fELF" or struct.unpack_from("<H", elf, 18)[0] != 183:
        raise AssertionError("Cross compiler did not emit an AArch64 ELF object")
    run_checked(["clang", *COMMON, "-O1", "-g", "-fsanitize=address,undefined",
                 "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
                 *extra, str(path), "-pthread", "-lm", "-o", str(binary)])
    env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:halt_on_error=1",
               UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=60, env=env)
    if failure:
        if result.returncode == 0 or failure not in result.stderr:
            raise AssertionError(f"Expected specific runtime rejection {failure!r}; "
                                 f"exit={result.returncode}\n{result.stdout}{result.stderr}")
    elif result.returncode:
        raise AssertionError(result.stdout + result.stderr)


def compiler_check(source, failure=None):
    with tempfile.TemporaryDirectory(prefix="mhgu-0161-c-") as tmp:
        directory = Path(tmp)
        path = directory / "fixture.c"
        path.write_text(source)
        compile_and_run(path, directory, failure=failure)


def pin_enabled(root):
    """Use the ACTUAL maintenance parser (including its strict old-pin checks)."""
    spec = importlib.util.spec_from_file_location(
        "mhgu_0161_pin_parser", root / ".github/maintenance/sync-upstream.py")
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    state = policy.parse_release_state(
        (root / ".github/maintenance/upstream-release.tsv").read_bytes())
    return policy.numeric_version(state["version"]) >= policy.numeric_version("0.16.1")


class PinGateTests(unittest.TestCase):
    def test_only_valid_old_pin_skips(self):
        parser = ROOT / ".github/maintenance/sync-upstream.py"
        valid = (ROOT / ".github/maintenance/upstream-release.tsv").read_text()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            maintenance = root / ".github/maintenance"
            maintenance.mkdir(parents=True)
            (maintenance / "sync-upstream.py").write_bytes(parser.read_bytes())
            pin = maintenance / "upstream-release.tsv"
            # Use canonical metadata with matched version and tag replacements.
            lines = valid.splitlines()
            for version, enabled in (("0.16.0", False), ("0.16.1", True),
                                     ("0.17.0", True), ("0.16.1.0", True)):
                pin.write_text("\n".join(
                    k + "\t" + (version if k in ("version", "tag") else v)
                    for k, v in (line.split("\t", 1) for line in lines)) + "\n")
                self.assertIs(pin_enabled(root), enabled)
            pin.unlink()
            with self.assertRaises(FileNotFoundError):
                pin_enabled(root)
            old = "\n".join(k + "\t" + ("0.16.0" if k in ("version", "tag") else v)
                            for k, v in (line.split("\t", 1) for line in lines)) + "\n"
            invalid = [
                "", "version\t0.16.0\n", old.replace("0.16.0", "v0.16.0"),
                old.replace("schema\t1", "schema\t9"),
                old.replace("commit\t", "commit\tbad"),
                old + "version\t0.16.0\n",
                old.replace("tag\t0.16.0", "tag\t0.15.4"),
                old.replace("\n", "\r\n"), old.rstrip("\n"),
            ]
            for text in invalid:
                with self.subTest(invalid=text[:50]):
                    pin.write_bytes(text.encode())
                    with self.assertRaises(Exception):
                        pin_enabled(root)


class Contracts0161(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        override = os.environ.get("MHGU_0161_SOURCE")
        if override:
            cls.root = Path(override).resolve()
            head = run_checked(["git", "--no-replace-objects", "-C", str(cls.root),
                                "rev-parse", "HEAD"]).stdout.strip()
            if head != PIN:
                raise AssertionError("MHGU_0161_SOURCE must be the exact audited 0.16.1 commit")
        else:
            if not pin_enabled(ROOT):
                raise unittest.SkipTest("Requires valid source pin 0.16.1 or later")
            cls.root = ROOT

    @classmethod
    def read(cls, path):
        return (cls.root / path).read_text()

    def test_sanitizers_fail_closed(self):
        compiler_check(LIBC + "int main(void) { volatile int x=2147483647; return x+1; }",
                       failure="runtime error: signed integer overflow")
        compiler_check(LIBC + r"""
__attribute__((noinline)) static int read_bad(volatile int *p, int n) { return p[n]; }
int main(void) { volatile int p[1] = {0}; return read_bad(p, 1); }
""", failure="AddressSanitizer: stack-buffer-overflow")

    def title_fixture(self, mutation=None, failure=None):
        with tempfile.TemporaryDirectory(prefix="mhgu-title-") as tmp:
            directory = Path(tmp)
            tests = directory / "tests"
            tests.mkdir()
            (directory / "runtime").symlink_to(self.root / "runtime", target_is_directory=True)
            path = tests / "test_title_exit.c"
            path.write_bytes((ROOT / "tests/test_title_exit.c").read_bytes())
            (tests / "test_0160_fixture.h").write_bytes(
                (ROOT / "tests/test_0160_fixture.h").read_bytes())
            headers = directory / "headers"
            (headers / "SDL3").mkdir(parents=True)
            (headers / "vulkan").mkdir()
            # Type-only boundaries for overlay.h. Nothing is linked or executed
            # from SDL/Vulkan. Native uses the platform libc headers unchanged.
            (headers / "SDL3/SDL.h").write_text("typedef union SDL_Event SDL_Event;\n")
            (headers / "vulkan/vulkan.h").write_text(
                "#include <stdint.h>\n" + "\n".join(
                    "typedef uintptr_t " + name + ";" for name in
                    ("VkInstance", "VkPhysicalDevice", "VkDevice", "VkQueue",
                     "VkPipelineCache", "VkRenderPass", "VkCommandBuffer")) + "\n")
            cross = directory / "cross"
            cross.mkdir()
            # Freestanding DECLARATIONS only: no target libc sysroot needed.
            # The real Cpu, rt/hle/platform headers and complete fixture compile.
            shims = {
                "assert.h": "#define assert(x) do { if (!(x)) abort(); } while (0)\n"
                            "extern void abort(void) __attribute__((noreturn));\n",
                "stdlib.h": "#include <stddef.h>\nextern void abort(void) __attribute__((noreturn));\n"
                            "extern char *getenv(const char *);\n",
                "stdio.h": "#include <stddef.h>\ntypedef struct fixture_FILE FILE;\n"
                           "extern FILE *stderr;\nextern int fprintf(FILE *, const char *, ...);\n"
                           "extern int puts(const char *);\n",
                "string.h": "#include <stddef.h>\n"
                            "extern void *memcpy(void *, const void *, size_t);\n"
                            "extern void *memset(void *, int, size_t);\n"
                            "extern int memcmp(const void *, const void *, size_t);\n",
                "pthread.h": "/* rt.h does not expose pthread types in this fixture. */\n",
                "math.h": "#define signbit(x) __builtin_signbit(x)\n"
                          "extern double floor(double), ceil(double), round(double), trunc(double);\n"
                          "extern double nearbyint(double), ldexp(double,int), fma(double,double,double);\n"
                          "extern float ldexpf(float,int), sqrtf(float);\n",
            }
            for name, text in shims.items():
                (cross / name).write_text(text)
            extra = ["-I" + str(headers)]
            if mutation:
                old, new = mutation
                source = self.read("runtime/hle/title_exit.c")
                self.assertEqual(source.count(old), 1)
                mutated = directory / "title_exit.c"
                # Preserve actual includes relative to the runtime/hle source.
                # -I runtime/hle resolves ../hle.h exactly as production.
                mutated.write_text(source.replace(old, new, 1))
                extra += ["-I" + str(self.root / "runtime/hle"),
                          '-DMHGU_TITLE_EXIT_SOURCE="' + str(mutated) + '"']
            compile_and_run(path, directory, extra=extra,
                            cross_extra=["-I" + str(cross)], failure=failure)

    def test_title_actual_hook_native_and_generic_aarch64(self):
        self.title_fixture()

    def test_title_narrow_mutations_are_rejected(self):
        cases = [
            ("bool pressed = down && !((was >> BTN_B) & 1);",
             "bool pressed = down; (void)was;", "requests == before + wanted"),
            ("uint32_t title = c->r[0];", "uint32_t title = 0;", "state_reads == expected_reads"),
            ("fnhook_call_original(c, FN_TITLE_UPDATE);", "(void)c;", "phase == 1"),
            ("title < 0x08000000u", "title < 0u", "read_permitted"),
            ("title >= 0xF0000000u", "title > 0xF0000000u", "read_permitted"),
            ("(title & 3)", "(title & 0)", "read_permitted"),
            ("!= STATE_MAIN_MENU", "== STATE_MAIN_MENU", "requests == before + wanted"),
            ("swallow = true; return;", "swallow = false; return;", "read_permitted"),
            ("if (!down) swallow = false;", "if (down) swallow = false;", "state_reads == expected_reads"),
        ]
        for old, new, diagnostic in cases:
            with self.subTest(mutation=old):
                self.title_fixture((old, new), failure=diagnostic)

    def decoration_patch(self):
        tree = ast.parse(self.read("tools/gen.py"))
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id == "PATCHES" for t in node.targets)]
        self.assertEqual(len(assignments), 1)
        patches = ast.literal_eval(assignments[0].value)
        self.assertIn(("main", 0x2db778), patches)
        word, code = patches["main", 0x2db778]
        self.assertEqual(word, 0xE1D410BA)  # ldrh r1, [r4, #0xa]
        return word, code

    def decoration_fixture(self, code):
        return LIBC + r"""
typedef struct { uint32_t r[16]; } Cpu;
static Cpu cpu;
static unsigned loads;
static uint16_t payload;
static uint32_t ld16(uint32_t a) {
    CHECK(a == 0x0800000au);
    ++loads;
    return payload;
}
#define LD16(a) ld16(a)
static void patch_word(Cpu *c) {
""" + code + r"""
}
int main(void) {
    static const struct { uint32_t input, output; } cases[] = {
        {0x80000000u, 0}, {0xffffff00u, 0}, {0xfffffffeu, 0}, {0xffffffffu, 0},
        {0, 0}, {1, 1}, {2, 2}, {3, 3}, {255, 255}, {0x7fffffffu, 0x7fffffffu}
    };
    static const uint16_t values[] = {0, 1, 0x1234, 0x8000, 0xffff};
    for (size_t i=0; i<sizeof cases/sizeof *cases; ++i) {
        for (size_t j=0; j<sizeof values/sizeof *values; ++j) {
            for (unsigned k=0; k<16; ++k) cpu.r[k] = 0xface0000u+k;
            cpu.r[4]=0x08000000u; cpu.r[8]=cases[i].input;
            uint32_t before[16]; memcpy(before, cpu.r, sizeof before);
            payload=values[j]; loads=0;
            patch_word(&cpu);
            CHECK(cpu.r[8] == cases[i].output);
            CHECK(cpu.r[1] == values[j] && loads == 1);
            for (unsigned k=0; k<16; ++k)
                if (k != 1 && k != 8) CHECK(cpu.r[k] == before[k]);
        }
    }
    return 0;
}
"""

    def test_decoration_patch_numeric_signed_edges_and_original_load(self):
        _, code = self.decoration_patch()
        compiler_check(self.decoration_fixture(code))

    def test_decoration_narrow_mutations_are_rejected(self):
        _, code = self.decoration_patch()
        cases = [
            ("(int32_t)", "(uint32_t)", "cpu.r[8] == cases[i].output"),
            ("c->r[8] = 0;", "c->r[8] = 1;", "cpu.r[8] == cases[i].output"),
            ("c->r[1] = LD16(c->r[4] + 0xau);", "(void)0;",
             "cpu.r[1] == values[j] && loads == 1"),
            ("+ 0xau", "+ 0x8u", "a == 0x0800000au"),
        ]
        for old, new, diagnostic in cases:
            with self.subTest(mutation=old):
                self.assertEqual(code.count(old), 1)
                compiler_check(self.decoration_fixture(code.replace(old, new, 1)), failure=diagnostic)

    def test_generator_actual_lift_installs_patch_and_rejects_wrong_word(self):
        # Real generator Module.lift + real lifter; no NSO construction/game file.
        # AST extraction avoids importing Nso/lz4 (irrelevant disk decompression).
        tree = ast.parse(self.read("tools/gen.py"))
        selected = [node for node in tree.body if
                    isinstance(node, ast.ClassDef) and node.name == "Module"]
        self.assertEqual(len(selected), 1)
        lift_tree = ast.Module(body=selected, type_ignores=[])
        tools = self.root / "tools"
        spec = importlib.util.spec_from_file_location("mhgu_0161_lifter", tools / "lifter.py")
        lifter = importlib.util.module_from_spec(spec)
        # Only sibling neon.py is imported; no plugins or foreign bytecode.
        with patch.object(sys, "path", [str(tools), *sys.path]):
            spec.loader.exec_module(lifter)
        word, code = self.decoration_patch()
        ns = dict(vars(lifter), PATCHES={("main", 0x2db778): (word, code)},
                  MOV_LR_PC=0xE1A0E00F, sys=sys)
        exec(compile(lift_tree, str(self.root / "tools/gen.py"), "exec"), ns)
        module_type = ns["Module"]
        for module_name, actual_word, patched in (
                ("main", word, True), ("sdk", word, False)):
            obj = module_type.__new__(module_type)
            obj.name, obj.lo, obj.hi = module_name, 0x2db778, 0x2db77c
            obj.words, obj.cache = (actual_word,), {}
            obj.lifter = lifter.Lifter(bytearray(4), obj.lo, obj.lo, obj.hi)
            ins = obj.lift(obj.lo)
            self.assertEqual(ins.code == code, patched)
            self.assertIs(obj.lift(obj.lo), ins)
        obj = module_type.__new__(module_type)
        obj.name, obj.lo, obj.hi = "main", 0x2db778, 0x2db77c
        obj.words, obj.cache = (word ^ 1,), {}
        obj.lifter = lifter.Lifter(bytearray(4), obj.lo, obj.lo, obj.hi)
        with self.assertRaisesRegex(SystemExit, "patch expects e1d410ba, found e1d410bb"):
            obj.lift(obj.lo)

    def ui_fixture(self, mutation=None):
        ui = self.read("runtime/ui.c")
        drain = region(ui, "        int action = SDL_SetAtomicInt(&requested_action, 0);",
                       "        if (action == 1)")
        window = function(ui, "if (e.type == SDL_EVENT_QUIT)")
        if mutation:
            old, new = mutation
            self.assertEqual(drain.count(old), 1)
            drain = drain.replace(old, new, 1)
        return LIBC + r"""
typedef struct { int value; } SDL_AtomicInt;
static SDL_AtomicInt requested_action;
static unsigned swaps, closes, exits;
static bool confirm_exit, dirty;
enum { SDL_EVENT_QUIT = 1 };
static int SDL_SetAtomicInt(SDL_AtomicInt *p, int n) {
    int old=p->value; p->value=n; ++swaps; return old;
}
static bool config_confirm_exit(void) { return confirm_exit; }
static bool overlay_settings_dirty(void) { return dirty; }
static void overlay_request_close(void) { ++closes; }
static void fixture_exit(int code) { CHECK(code == 0); ++exits; }
#define exit(code) do { fixture_exit(code); return; } while (0)
""" + functions(ui, "void ui_request_exit_menu(", "void ui_request_action(") + r"""
static void drain_once(void) {
""" + drain + r"""
}
static void window_close(void) {
    struct { int type; } e = {SDL_EVENT_QUIT};
    do {
""" + window + r"""
    } while (0);
}
int main(void) {
    for (unsigned mask=0; mask<4; ++mask) {
        confirm_exit=(mask&1)!=0; dirty=(mask&2)!=0;
        closes=exits=swaps=0; requested_action.value=0;
        ui_request_exit_menu(); CHECK(requested_action.value == 12 && swaps == 1);
        ui_request_exit_menu(); CHECK(requested_action.value == 12 && swaps == 2);
        drain_once();
        CHECK(requested_action.value == 0 && swaps == 3);
        CHECK(exits == (mask == 0 ? 1u : 0u));
        CHECK(closes == (mask == 0 ? 0u : 1u));
        drain_once();
        CHECK(exits == (mask == 0 ? 1u : 0u));
        CHECK(closes == (mask == 0 ? 0u : 1u));
        ui_request_action(false); CHECK(requested_action.value == 1);
        drain_once(); CHECK(requested_action.value == 0);
        ui_request_action(true); CHECK(requested_action.value == 2);
        drain_once(); CHECK(requested_action.value == 0);
        closes=exits=0;
        window_close();
        CHECK(exits == (mask == 0 ? 1u : 0u));
        CHECK(closes == (mask == 0 ? 0u : 1u));
    }
    return 0;
}
"""

    def test_ui_actual_request_drain_and_confirmation_truth_table(self):
        compiler_check(self.ui_fixture())

    def test_actual_overlay_close_requests_panel_and_opens_settings(self):
        overlay = self.read("runtime/overlay.cpp")
        compiler_check(LIBC + r"""
static bool g_forge_over, g_settings_open, g_forge_open;
static unsigned requests, opened;
static void settings_panel_request_close(void) { ++requests; }
static void set_open(bool forge) {
    CHECK(requests == 1 && !g_forge_over && g_settings_open);
    CHECK(forge == g_forge_open);
    ++opened;
}
""" + function(overlay, "void overlay_request_close(") + r"""
int main(void) {
    for (unsigned mask=0; mask<8; ++mask) {
        g_forge_over=(mask&1)!=0; g_settings_open=(mask&2)!=0;
        g_forge_open=(mask&4)!=0; requests=opened=0;
        overlay_request_close();
        CHECK(requests == 1 && opened == 1);
        CHECK(!g_forge_over && g_settings_open);
    }
    return 0;
}
""")

    def test_ui_narrow_mutations_are_rejected(self):
        for old, new, diagnostic in (
                ("action == 12", "action == 13", "exits == (mask == 0 ? 1u : 0u)"),
                ("!config_confirm_exit() && !overlay_settings_dirty()",
                 "!config_confirm_exit() || !overlay_settings_dirty()",
                 "exits == (mask == 0 ? 1u : 0u)"),
                ("SDL_SetAtomicInt(&requested_action, 0)",
                 "SDL_SetAtomicInt(&requested_action, 12)",
                 "requested_action.value == 0 && swaps == 3"),
                ("overlay_request_close();", "(void)0;",
                 "closes == (mask == 0 ? 0u : 1u)")):
            with self.subTest(mutation=old):
                compiler_check(self.ui_fixture((old, new)), failure=diagnostic)

    def forge_fixture(self, mutation=None):
        forge = self.read("runtime/forge.c")
        app = function(forge, "static void app_run(")
        if mutation:
            old, new = mutation
            self.assertEqual(app.count(old), 1)
            app = app.replace(old, new, 1)
        declarations = region(forge, "#define MAX_PLUGINS", "static int nplugins;")
        return LIBC + r"""
#define MAX_MODULES 16
#define FORGE_MAJOR 1
#define FORGE_MINOR 5
#define FORGE_PATCH 1
#define OFF_APP_RUN 0xB8692Cu
typedef struct { uint32_t r[16]; } Cpu;
typedef struct { const char *name; } Module;
""" + declarations + r"""
static int nplugins;
static unsigned phase, constructors, loads, inits, originals, allocations;
static unsigned looked_up;
static unsigned char mem[2048];
static uint32_t saved_args[4];
static const char *names[] = {
    "Lag Compensation", "Other plugin", "lag compensation",
    "Lag Compensation ", "Lag Compensation", "Lag Compensation",
    "No onLoad", "Lag CompensationX"
};
static uint32_t guest(uint32_t a, unsigned n) {
    CHECK(a >= 0x04000000u && a-0x04000000u+n <= sizeof mem);
    return a-0x04000000u;
}
static uint32_t ld16(uint32_t a) {
    unsigned i=guest(a,2); return mem[i] | ((uint32_t)mem[i+1]<<8);
}
static void st8(uint32_t a, uint32_t v) { mem[guest(a,1)]=(unsigned char)v; }
#define LD16(a) ld16(a)
#define ST8(a,v) st8(a,v)
static const char *gstr(uint32_t a) {
    ++looked_up; return (const char *)(mem+guest(a,1));
}
static void flog(int level, const char *fmt, ...) { (void)level; (void)fmt; }
static uint32_t text_addr(uint32_t a) { return 0x00200000u+a; }
static void singletons_resolve(Cpu *c, bool all) {
    CHECK(phase == 0 && all); phase=1; c->r[0]=0xdead;
}
static uint32_t f_sock_init_default_value(Cpu *c) {
    CHECK(phase == 1); phase=2; c->r[1]=0xbeef; return 0;
}
static void plugin_initializers(Cpu *c, Module *m) {
    CHECK(phase == 2 && m && m->name); ++constructors; c->r[2]=constructors;
}
static uint32_t hle_alloc(unsigned n) {
    CHECK(n == 72 && constructors == (unsigned)nplugins);
    ++allocations; return 0x04000000u+72u*(allocations-1);
}
static void gcall(Cpu *c, uint32_t fn, uint32_t a0, uint32_t a1,
                  uint32_t a2, uint32_t a3) {
    CHECK(constructors == (unsigned)nplugins && !a1 && !a2 && !a3);
    CHECK(allocations > 0);
    unsigned index=allocations-1;
    CHECK(plugins[index].active);
    if (fn == 0x100u+index) {
        CHECK(a0 == plugins[index].param);
        CHECK(inits == (index > 1 ? (index > 3 ? 3u : index-1) : 0u));
        ++loads;
        unsigned off=guest(a0,72);
        unsigned major=index==4 ? 2u : 1u, minor=index==5 ? 6u : 5u;
        mem[off]=(unsigned char)major; mem[off+2]=(unsigned char)minor;
        mem[off+4]=255; /* patch version never rejects compatible plugin */
        memcpy(mem+off+6,names[index],strlen(names[index])+1);
        mem[off+69]=0x7f; /* app_run MUST terminate this byte */
        c->r[0]=0xaaaa; c->r[3]=0xbbbb;
    } else {
        CHECK(fn == 0x200u+index && a0 == 0);
        CHECK(index == 1 || index == 2 || index == 3 || index == 7);
        CHECK(mem[guest(plugins[index].param+69,1)] == 0);
        ++inits;
    }
}
static void fnhook_call_original(Cpu *c, uint32_t a) {
    CHECK(a == 0x00200000u+OFF_APP_RUN);
    CHECK(memcmp(c->r,saved_args,sizeof saved_args) == 0);
    CHECK(constructors == 8 && allocations == 8 && loads == 7 && inits == 4);
    ++originals; c->r[0]=0x13579bdfu;
}
""" + app + r"""
int main(void) {
    Cpu c = {{11,22,33,44}};
    memcpy(saved_args,c.r,sizeof saved_args);
    Module modules[8];
    nplugins=8;
    for (unsigned i=0;i<8;++i) {
        modules[i].name="synthetic"; plugins[i].m=&modules[i];
        strcpy(plugins[i].name,i==0 ? "renamed.nro" : "lagcomp.nro");
        plugins[i].on_load=i==6 ? 0 : 0x100u+i;
        plugins[i].on_init=0x200u+i;
        plugins[i].on_update=0x300u+i;
    }
    app_run(&c);
    CHECK(originals == 1 && c.r[0] == 0x13579bdfu);
    CHECK(!plugins[0].active && !plugins[4].active && !plugins[5].active);
    CHECK(plugins[1].active && plugins[2].active && plugins[3].active &&
          plugins[6].active && plugins[7].active);
    CHECK(looked_up == 5); /* version rejection before skip predicate */
    return 0;
}
"""

    def test_forge_actual_skip_predicate_and_startup_order(self):
        compiler_check(self.forge_fixture())

    def test_forge_narrow_mutations_are_rejected(self):
        for old, new, diagnostic in (
                ('!strcmp(gstr(p->param + 6), "Lag Compensation")',
                 '!strcmp(p->name, "lagcomp.nro")',
                 "index == 1 || index == 2 || index == 3 || index == 7"),
                ('!strcmp(gstr(p->param + 6), "Lag Compensation")', 'false',
                 "index == 1 || index == 2 || index == 3 || index == 7"),
                ("p->active = false;\n            continue;\n        }\n        if (p->on_init)",
                 "p->active = true;\n            continue;\n        }\n        if (p->on_init)",
                 "!plugins[0].active && !plugins[4].active && !plugins[5].active"),
                ("plugin_initializers(c, plugins[i].m);", "(void)c;",
                 "n == 72 && constructors == (unsigned)nplugins"),
                ("gcall(c, p->on_load, p->param, 0, 0, 0);",
                 "if (p->on_init) gcall(c, p->on_init, 0, 0, 0, 0);\n"
                 "        gcall(c, p->on_load, p->param, 0, 0, 0);",
                 "index == 1 || index == 2 || index == 3 || index == 7")):
            with self.subTest(mutation=old):
                compiler_check(self.forge_fixture((old, new)), failure=diagnostic)


if __name__ == "__main__":
    unittest.main()
