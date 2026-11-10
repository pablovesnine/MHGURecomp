"""0.16.0 production-source contracts; no game, GPU, SDL runtime, or plugin.

Install as tests/test_0160_contracts.py. Old-source preparation skips this class.
Audit an exact upstream worktree with MHGU_0160_SOURCE=/path/to/worktree.
SDL leaves below are deliberately single-threaded boundary doubles, NOT an
atomicity/concurrency claim. C statements/functions are extracted, not rewritten.
"""
import ast
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PIN = "dc26e6d9a22afbedc1138fd07e94f3e3c55efed3"


def region(text, start, stop):
    assert text.count(start) == 1, start
    a = text.index(start)
    return text[a:text.index(stop, a)]


def function(text, signature):
    """Brace extraction ignoring C strings/comments (shader strings have braces)."""
    assert text.count(signature) == 1, signature
    a = text.index(signature)
    masked = re.sub(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|'
                    r'/\*.*?\*/|//[^\n]*',
                    lambda m: " " * len(m[0]), text, flags=re.S)
    brace = masked.index("{", a)
    depth = 1
    end = brace + 1
    while depth:
        depth += (masked[end] == "{") - (masked[end] == "}")
        end += 1
    return text[a:end] + "\n"


def functions(text, *signatures):
    return "\n".join(function(text, s) for s in signatures) + "\n"


def without_includes(text):
    return re.sub(r'^\s*#(?:include[^\n]*|pragma once)', "", text, flags=re.M)


def compiler_check(source, expected_runtime_failure=None):
    """Actual C, native sanitizer execution plus freestanding ARM64 syntax."""
    common = ["-std=gnu11", "-fsigned-char", "-fno-strict-aliasing",
              "-ffp-contract=off", "-Wall", "-Wextra", "-Werror",
              "-Wno-unused-function", "-Wno-unused-variable",
              "-Wno-missing-field-initializers"]
    with tempfile.TemporaryDirectory(prefix="mhgu-0160-") as tmp:
        c, exe = Path(tmp) / "fixture.c", Path(tmp) / "fixture"
        c.write_text(source)
        commands = [
            ["clang", *common, "--target=aarch64-linux-gnu", "-march=armv8-a",
             "-ffreestanding", "-fsyntax-only", str(c)],
            ["clang", *common, "-O1", "-g", "-fsanitize=address,undefined",
             "-fno-sanitize-recover=all", "-fno-omit-frame-pointer",
             str(c), "-lm", "-o", str(exe)],
            [str(exe)],
        ]
        for index, cmd in enumerate(commands):
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if expected_runtime_failure and index == 2:
                if not proc.returncode or expected_runtime_failure not in proc.stderr:
                    raise AssertionError(
                        f"Expected the specific known runtime limit: {expected_runtime_failure!r}\n"
                        f"exit={proc.returncode}\n{proc.stdout}{proc.stderr}")
                continue
            if proc.returncode:
                raise AssertionError(f"{' '.join(cmd)}\n{proc.stdout}{proc.stderr}")


# Only compiler-resource headers: no target libc/SDL/Vulkan sysroot required.
LIBC = r"""
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdarg.h>
#include <float.h>
extern void abort(void);
extern int printf(const char *, ...);
#if __STDC_HOSTED__
#include <stdio.h>
#else
typedef struct fixture_FILE FILE;
extern int fprintf(FILE *, const char *, ...);
extern FILE *stderr;
#endif
extern int sprintf(char *, const char *, ...);
extern int snprintf(char *, size_t, const char *, ...);
extern int vsnprintf(char *, size_t, const char *, va_list);
extern void *memcpy(void *, const void *, size_t);
extern void *memset(void *, int, size_t);
extern int memcmp(const void *, const void *, size_t);
extern size_t strlen(const char *);
extern size_t strspn(const char *, const char *);
extern size_t strcspn(const char *, const char *);
extern char *strchr(const char *, int);
extern char *strpbrk(const char *, const char *);
extern char *strstr(const char *, const char *);
extern char *strcpy(char *, const char *);
extern char *strcat(char *, const char *);
extern int strcmp(const char *, const char *);
extern int strncmp(const char *, const char *, size_t);
extern int strcasecmp(const char *, const char *);
extern int strncasecmp(const char *, const char *, size_t);
extern int isspace(int);
extern int tolower(int);
extern void *calloc(size_t, size_t);
extern void *realloc(void *, size_t);
extern void free(void *);
extern char *getenv(const char *);
extern int atoi(const char *);
extern float strtof(const char *, char **);
extern int sscanf(const char *, const char *, ...);
extern void qsort(void *, size_t, size_t, int (*)(const void *, const void *));
extern float fminf(float, float);
extern float fmaxf(float, float);
extern float fabsf(float);
extern float roundf(float);
extern float fmaf(float, float, float);
#define alloca(n) __builtin_alloca(n)
#define INFINITY (__builtin_inff())
#define NAN (__builtin_nanf(""))
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "CHECK line %d: %s\n", __LINE__, #x); abort(); } } while (0)
#define NEAR(x,y) CHECK(fabsf((x)-(y)) < 0.002f)
#define LOG(...) ((void)0)
"""

# SDL3 scancode/mouse constants (boundary ABI, not a replacement key parser).
SDL = r"""
typedef int SDL_Scancode;
enum {
 SDL_SCANCODE_UNKNOWN=0, SDL_SCANCODE_A=4, SDL_SCANCODE_D=7,
 SDL_SCANCODE_E=8, SDL_SCANCODE_Q=20, SDL_SCANCODE_R=21,
 SDL_SCANCODE_S=22, SDL_SCANCODE_T=23, SDL_SCANCODE_W=26,
 SDL_SCANCODE_RETURN=40, SDL_SCANCODE_ESCAPE=41, SDL_SCANCODE_BACKSPACE=42,
 SDL_SCANCODE_TAB=43, SDL_SCANCODE_SPACE=44, SDL_SCANCODE_SEMICOLON=51,
 SDL_SCANCODE_COMMA=54, SDL_SCANCODE_SLASH=56,
 SDL_SCANCODE_F1=58, SDL_SCANCODE_F7=64, SDL_SCANCODE_F8=65,
 SDL_SCANCODE_F9=66, SDL_SCANCODE_F10=67, SDL_SCANCODE_F11=68,
 SDL_SCANCODE_F12=69, SDL_SCANCODE_INSERT=73, SDL_SCANCODE_RIGHT=79,
 SDL_SCANCODE_LEFT=80, SDL_SCANCODE_DOWN=81, SDL_SCANCODE_UP=82,
 SDL_SCANCODE_KP_ENTER=88, SDL_SCANCODE_KP_COMMA=133, SDL_SCANCODE_KP_HASH=204,
 SDL_SCANCODE_LCTRL=224, SDL_SCANCODE_LSHIFT=225, SDL_SCANCODE_LALT=226,
 SDL_SCANCODE_RCTRL=228, SDL_SCANCODE_RALT=230, SDL_SCANCODE_COUNT=512,
 SDL_BUTTON_LEFT=1, SDL_BUTTON_MIDDLE=2, SDL_BUTTON_RIGHT=3,
 SDL_BUTTON_X1=4, SDL_BUTTON_X2=5, SDL_MOUSEWHEEL_FLIPPED=1,
 SDL_EVENT_KEY_DOWN=1, SDL_EVENT_MOUSE_BUTTON_DOWN=2, SDL_EVENT_MOUSE_WHEEL=3,
 SDL_EVENT_KEY_UP=4
};
static const struct { int code; const char *name; } sdl_names[] = {
 {SDL_SCANCODE_W,"W"}, {SDL_SCANCODE_A,"A"}, {SDL_SCANCODE_Q,"Q"},
 {SDL_SCANCODE_R,"R"}, {SDL_SCANCODE_E,"E"}, {SDL_SCANCODE_RETURN,"Return"},
 {SDL_SCANCODE_KP_ENTER,"Keypad Enter"}, {SDL_SCANCODE_ESCAPE,"Escape"},
 {SDL_SCANCODE_F1,"F1"}, {SDL_SCANCODE_INSERT,"Insert"},
 {SDL_SCANCODE_F7,"F7"}, {SDL_SCANCODE_F8,"F8"}, {SDL_SCANCODE_F9,"F9"},
 {SDL_SCANCODE_F10,"F10"}, {SDL_SCANCODE_F11,"F11"}, {SDL_SCANCODE_F12,"F12"},
 {SDL_SCANCODE_LCTRL,"Left Ctrl"}, {SDL_SCANCODE_SLASH,"/"},
 {SDL_SCANCODE_COMMA,","}, {SDL_SCANCODE_SEMICOLON,";"}
};
static const char *SDL_GetScancodeName(SDL_Scancode c) {
 for (size_t i=0;i<sizeof sdl_names/sizeof *sdl_names;i++)
  if(sdl_names[i].code==c) return sdl_names[i].name;
 return "";
}
static SDL_Scancode SDL_GetScancodeFromName(const char *n) {
 for(size_t i=0;i<sizeof sdl_names/sizeof *sdl_names;i++)
  if(!strcasecmp(sdl_names[i].name,n)) return sdl_names[i].code;
 return 0;
}
#define SDL_strncasecmp strncasecmp
typedef struct { int value; } SDL_AtomicInt;
typedef int SDL_SpinLock;
static int SDL_GetAtomicInt(SDL_AtomicInt *p) { return p->value; }
static int SDL_SetAtomicInt(SDL_AtomicInt *p,int v) { int old=p->value;p->value=v;return old; }
static bool SDL_CompareAndSwapAtomicInt(SDL_AtomicInt *p,int old,int v) {
 if(p->value!=old) return false;
 p->value=v; return true;
}
static void SDL_LockSpinlock(SDL_SpinLock *p) { (void)p; }
static void SDL_UnlockSpinlock(SDL_SpinLock *p) { (void)p; }
typedef struct {
 int type;
 struct { int scancode; bool repeat; } key;
 struct { int button; } button;
 struct { int integer_y, direction; } wheel;
} SDL_Event;
"""


class Contracts0160(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        override = os.environ.get("MHGU_0160_SOURCE")
        if override:
            cls.root = Path(override).resolve()
            head = subprocess.run(
                ["git", "--no-replace-objects", "-C", str(cls.root),
                 "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
            if head != PIN:
                raise AssertionError("MHGU_0160_SOURCE must be the exact audited 0.16.0 commit")
        else:
            state = ROOT / ".github/maintenance/upstream-release.tsv"
            pin = dict(line.split("\t", 1) for line in state.read_text().splitlines())
            if tuple(map(int, pin["version"].split("."))) < (0, 16, 0):
                raise unittest.SkipTest("0.16.0 contracts await source pin 0.16.0 or later")
            if not re.fullmatch(r"[0-9a-f]{40}", pin["commit"]):
                raise AssertionError("Invalid pinned upstream commit")
            cls.root = ROOT

    @classmethod
    def read(cls, path):
        return (cls.root / path).read_text()

    def config_fixture(self, forge=False):
        c = self.read("runtime/config.c")
        store = self.read("runtime/config_store.c")
        code = LIBC + without_includes(self.read("runtime/config.h")) + SDL
        code += function(self.read("runtime/keymap.h"), "static inline const char *key_reserved(")
        code += region(c, "#define DEFAULT_BINDS", "uint32_t g_render_size")
        code += region(c, "#define ERR_SIZE", "// [Keybinds] names:")
        code += region(c, "static const struct { int code; const char *name; } key_names[]", "// Is name (squashed)")
        code += functions(c, "static void squash(", "static bool spelled(",
                          "const ConfigSetting *config_setting(",
                          "bool config_parse_keys(", "void config_format_keys(")
        code += region(store, "static Config saved, startup;", "static void publish_live(")
        code += functions(store, "static void publish_live(", "void config_store_loaded(",
                          "int config_live_chat_key(", "int config_live_lag_compensation(")
        code += region(store, "static SDL_AtomicInt mod_binds", "void config_live_ldn(")
        if forge:
            f = self.read("runtime/forge.c")
            code += r"""
typedef struct { uint32_t args[3], result; } Cpu;
static uint8_t guest[4096];
static void *guest_at(uint32_t a) { CHECK(a && a<sizeof guest); return guest+a; }
static const char *gstr(uint32_t a) {
 CHECK(a && a<sizeof guest); CHECK(memchr(guest+a,0,sizeof guest-a)); return guest_at(a);
}
#define G2H(a) guest_at(a)
#define ARG(i) (c->args[i])
#define RET(v) (c->result=(v))
#define HLE_FUNC(exported,name) static void name(Cpu *c)
static int pressed_key;
"""
            # memchr is an external libc leaf, not a guest-memory mapping shortcut.
            code = code.replace("extern void abort(void);",
                                "extern void *memchr(const void *, int, size_t);\nextern void abort(void);")
            code += functions(f, "static int bind_of(", "static void keys_out(",
                              'HLE_FUNC("forge_input_setKeybind",',
                              'HLE_FUNC("forge_input_getKeybind",',
                              'HLE_FUNC("forge_input_getModKeybind",',
                              'HLE_FUNC("forge_input_getKeyPressed",')
        return code

    def translator_fixture(self):
        t = self.read("runtime/nvn/maxwell/translate.c")
        return LIBC + without_includes(self.read("runtime/nvn/maxwell/shader.h")) + without_includes(t)

    def test_harness_detects_native_ub(self):
        with self.assertRaisesRegex(AssertionError, "runtime error: signed integer overflow"):
            compiler_check(LIBC + "int main(void) { volatile int x=2147483647; return x+1; }")

    def test_parser_formatter_defaults_and_live_override(self):
        compiler_check(self.config_fixture() + r"""
int main(void) {
 Config c=config_defaults();
 CHECK(c.lag_compensation==1);
 CHECK(c.binds[BIND_L][0]==SDL_SCANCODE_Q);
 CHECK(c.binds[BIND_PLUS][0]==SDL_SCANCODE_RETURN &&
       c.binds[BIND_PLUS][1]==SDL_SCANCODE_KP_ENTER);
 config_store_loaded(&c);
 CHECK(config_live_lag_compensation()==1 && !config_mod_bound(BIND_L));
 int k[BIND_KEYS]={99,98};
 CHECK(config_parse_keys(" Left Ctrl , Q ",k) && k[0]==224 && k[1]==20);
 CHECK(config_parse_keys("Q,Q",k) && k[0]==20 && !k[1]);
 CHECK(config_parse_keys("Q,Q,Return",k) && k[0]==20 && k[1]==40);
 const char *bad[]={"NoSuchKey", "Q,","Q,,Return","Q,Return,W","Q,Return,Q",
                    "Escape","F1","Insert","F7","F8","F9","F10","F11","F12"};
 for(size_t i=0;i<sizeof bad/sizeof *bad;i++) {
  k[0]=99;k[1]=98; CHECK(!config_parse_keys(bad[i],k)); CHECK(k[0]==99&&k[1]==98);
 }
 CHECK(config_parse_keys("Comma, Semicolon",k) && k[0]==54 && k[1]==51);
 CHECK(config_parse_keys("Mouse 4, Wheel Up",k) && k[0]==KEY_MOUSE+4 && k[1]==KEY_WHEEL_UP);
 char buf[128];
 config_format_keys(k,buf,sizeof buf); CHECK(!strcmp(buf,"Mouse 4, Wheel Up"));
 CHECK(config_parse_keys(" N_o-n e ",k) && !k[0]&&!k[1]);
 CHECK(config_parse_keys("",k) && !k[0]&&!k[1]); /* parser permits; Forge rejects */
 config_format_keys(k,buf,sizeof buf); CHECK(!strcmp(buf,"None"));
 char tiny[4]={'x','x','x','Z'};
 config_format_keys(k,tiny,3); CHECK(!strcmp(tiny,"No") && tiny[3]=='Z');
 config_format_keys(k,tiny,0); CHECK(tiny[0]=='N' && tiny[3]=='Z');
 int mod[2]={SDL_SCANCODE_RETURN,KEY_WHEEL_UP};
 config_mod_bind(-1,mod); config_mod_bind(BINDS,mod); /* setter range guard */
 config_mod_bind(BIND_L,mod);
 CHECK(config_live_bind(BIND_L,0)==40 && config_player_bind(BIND_L,0)==20);
 c.binds[BIND_L][0]=SDL_SCANCODE_W;c.lag_compensation=0;config_store_loaded(&c);
 CHECK(config_live_bind(BIND_L,0)==40 && config_player_bind(BIND_L,0)==26);
 CHECK(!config_live_lag_compensation());
 int disabled[2]={0,0}; config_mod_bind(BIND_L,disabled);
 CHECK(config_mod_bound(BIND_L) && !config_live_bind(BIND_L,0));
 config_mod_bind(BIND_L,NULL);
 CHECK(!config_mod_bound(BIND_L) && config_live_bind(BIND_L,0)==26);
 CHECK(config_bind_setting(BIND_L)==config_setting(" L "));
 return 0;
}
""")

    def test_forge_bindings_bounded_guest_strings_and_live_separation(self):
        compiler_check(self.config_fixture(forge=True) + r"""
static void put(uint32_t a,const char *s) {
 CHECK(a+strlen(s)+1<sizeof guest); memcpy(guest+a,s,strlen(s)+1);
}
int main(void) {
 Config settings=config_defaults();config_store_loaded(&settings);
 Cpu c={{64,128,0},0};put(64,"L");put(128,"Left Ctrl, Q");
 f_in_set_keybind(&c);CHECK(c.result==1 && config_live_bind(BIND_L,0)==224);
 CHECK(config_player_bind(BIND_L,0)==20);
 c.args[1]=512;c.args[2]=32;memset(guest+512,0xa5,40);
 f_in_get_keybind(&c);CHECK(c.result==1&&!strcmp((char *)guest+512,"Q"));
 f_in_get_mod_keybind(&c);CHECK(c.result==1&&!strcmp((char *)guest+512,"Left Ctrl, Q"));
 CHECK(guest[544]==0xa5);
 /* invalid requests leave current mod row and output untouched */
 const char *bad[]={""," \t","Escape","F1","NoSuchKey","Q,Return,W","/","Q, /"};
 for(size_t i=0;i<sizeof bad/sizeof *bad;i++) {
  c.args[1]=128;put(128,bad[i]);f_in_set_keybind(&c);
  CHECK(!c.result && config_live_bind(BIND_L,0)==224);
 }
 put(64,"Port");put(128,"Q");f_in_set_keybind(&c);CHECK(!c.result);
 c.args[0]=0;f_in_set_keybind(&c);CHECK(!c.result);
 c.args[0]=64;put(64,"l");put(128," None ");f_in_set_keybind(&c);
 CHECK(c.result && config_mod_bound(BIND_L)&&!config_live_bind(BIND_L,0));
 /* Last caller wins; there is no plugin owner token. */
 put(128,"Return");f_in_set_keybind(&c);CHECK(c.result&&config_live_bind(BIND_L,0)==40);
 settings.binds[BIND_L][0]=26;config_store_loaded(&settings);
 CHECK(config_live_bind(BIND_L,0)==40);
 c.args[1]=0;f_in_set_keybind(&c);
 CHECK(c.result&&!config_mod_bound(BIND_L)&&config_live_bind(BIND_L,0)==26);
 c.args[1]=512;c.args[2]=32;put(512,"sentinel");
 f_in_get_mod_keybind(&c);CHECK(!c.result&&!strcmp((char *)guest+512,"sentinel"));
 /* bounded formatting: short output, zero size, null output */
 settings.binds[BIND_L][0]=224;config_store_loaded(&settings);
 c.args[2]=5;guest[517]=0x5a;f_in_get_keybind(&c);
 CHECK(c.result&&!strcmp((char *)guest+512,"Left")&&guest[517]==0x5a);
 c.args[2]=0;f_in_get_keybind(&c);CHECK(c.result);
 c.args[1]=0;c.args[2]=32;f_in_get_keybind(&c);CHECK(c.result);
 c.args[0]=512;c.args[1]=32;pressed_key=KEY_WHEEL_DOWN;f_in_key_pressed(&c);
 CHECK(c.result&&!strcmp((char *)guest+512,"Wheel Down"));
 pressed_key=SDL_SCANCODE_ESCAPE;f_in_key_pressed(&c);
 CHECK(c.result&&!strcmp((char *)guest+512,"Escape"));
 pressed_key=0;put(512,"unchanged");f_in_key_pressed(&c);
 CHECK(!c.result&&!strcmp((char *)guest+512,"unchanged"));
 pressed_key=511;f_in_key_pressed(&c);CHECK(!c.result);
 return 0;
}
""")

    def test_host_key_first_event_repeat_reserved_mouse_wheel_and_take(self):
        h = self.read("runtime/host_input.c")
        f = self.read("runtime/forge.c")
        # Structural wiring complements actual execution of event/take leaves.
        event = function(h, "void host_input_event(")
        self.assertLess(event.index("mods_key_event(e);"), event.index("if (overlay_event(e))"))
        self.assertIn("pressed_key = host_input_key_take();", function(f, "static void input_frame("))
        code = LIBC + without_includes(self.read("runtime/config.h")) + SDL
        code += function(self.read("runtime/keymap.h"), "static inline const char *key_reserved(")
        code += "\nstatic SDL_AtomicInt mods_key;\n"
        code += functions(h, "static int wheel_notches(", "static void mods_key_event(",
                          "int host_input_key_take(")
        compiler_check(code + r"""
int main(void) {
 SDL_Event e={0};CHECK(!host_input_key_take());
 e.type=SDL_EVENT_KEY_DOWN;e.key.scancode=SDL_SCANCODE_Q;e.key.repeat=true;
 mods_key_event(&e);CHECK(!host_input_key_take());
 e.key.repeat=false;mods_key_event(&e);e.key.scancode=SDL_SCANCODE_RETURN;mods_key_event(&e);
 CHECK(host_input_key_take()==SDL_SCANCODE_Q);CHECK(!host_input_key_take());
 int reserved[]={SDL_SCANCODE_F1,SDL_SCANCODE_INSERT,SDL_SCANCODE_F7,SDL_SCANCODE_F8,
                 SDL_SCANCODE_F9,SDL_SCANCODE_F10,SDL_SCANCODE_F11,SDL_SCANCODE_F12};
 for(size_t i=0;i<sizeof reserved/sizeof *reserved;i++) {
  e.key.scancode=reserved[i];mods_key_event(&e);CHECK(!host_input_key_take());
 }
 e.key.scancode=SDL_SCANCODE_ESCAPE;mods_key_event(&e);CHECK(host_input_key_take()==41);
 e.key.scancode=SDL_SCANCODE_COUNT;mods_key_event(&e);CHECK(!host_input_key_take());
 e.type=SDL_EVENT_KEY_UP;e.key.scancode=20;mods_key_event(&e);CHECK(!host_input_key_take());
 e.type=SDL_EVENT_MOUSE_BUTTON_DOWN;
 for(int b=0;b<=6;b++) {
  e.button.button=b;mods_key_event(&e);
  CHECK(host_input_key_take()==(b>=1&&b<=5?KEY_MOUSE+b:0));
 }
 e.type=SDL_EVENT_MOUSE_WHEEL;
 for(int n=-3;n<=3;n++) for(int flip=0;flip<=1;flip++) {
  e.wheel.integer_y=n;e.wheel.direction=flip;mods_key_event(&e);
  int v=flip?-n:n;CHECK(host_input_key_take()==(v>0?KEY_WHEEL_UP:v<0?KEY_WHEEL_DOWN:0));
 }
 return 0;
}
""")

    def test_fragment_fmz_dataflow_predicates_dialects_and_emission(self):
        compiler_check(self.translator_fixture() + r"""
static void reset_body(Ctx *c) { free(c->body.buf);c->body=(Str){0}; }
static uint64_t ins(uint64_t op,int d,int a,int b) {
 return op | (uint64_t)d | ((uint64_t)a<<8) | (7ull<<16) | ((uint64_t)b<<20);
}
int main(void) {
 ShaderInfo info={0};Ctx c={0};c.info=&info;c.glsl=true;c.stage=STAGE_FRAGMENT;
 /* Noncontiguous mask packs alpha into the next destination, TEXS has two pairs. */
 write_tex_result(&c,0,"sample()",9,10,20,false,false);
 CHECK(!c.tex_alpha[10]&&c.tex_alpha[11]&&!c.tex_alpha[13]);
 write_tex_result(&c,0,"sample()",15,30,40,true,false);
 CHECK(c.tex_alpha[41]&&!c.tex_alpha[31]);
 c.guarded=true;write_tex_result(&c,0,"sample()",1,11,0,false,false);
 CHECK(c.tex_alpha[11]);c.guarded=false;
 write_tex_result(&c,0,"sample()",1,11,0,false,false);CHECK(!c.tex_alpha[11]);
 write_tex_result(&c,0,"sample()",8,10,0,false,false);CHECK(c.tex_alpha[10]);
 reset_body(&c);
 emit_insn(&c,ins(0x5080000000000000ull,12,10,4),8); /* MUFU.RCP */
 CHECK(!c.fail&&c.inf_now[12]&&c.inf_ever[12]&&!c.tex_alpha[12]);
 CHECK(fmz_check(&c,1,12,RZ)&&fmz_check(&c,1,RZ,12));
 CHECK(!fmz_check(&c,0,12,RZ)&&!fmz_check(&c,2,12,RZ)&&!fmz_check(&c,3,12,RZ));
 CHECK(!fmz_check(&c,1,RZ,RZ));
 c.stage=STAGE_VERTEX;CHECK(!fmz_check(&c,1,12,0));
 c.stage=STAGE_COMPUTE;CHECK(!fmz_check(&c,1,12,0));
 c.stage=STAGE_FRAGMENT;c.glsl=false;CHECK(!fmz_check(&c,1,12,0));c.glsl=true;
 reset_body(&c);
 emit_insn(&c,ins(0x5c68000000000000ull,14,12,13)|(1ull<<44),16);
 CHECK(!c.fail&&strstr(c.body.buf,"fmz_mul(")&&!c.inf_now[14]);
 reset_body(&c);
 emit_insn(&c,ins(0x5980000000000000ull,14,12,13)|(1ull<<53),24);
 CHECK(!c.fail&&strstr(c.body.buf,"fmz_fma("));
 /* FFMA cbuf form uses bits39..46 for multiplier B, not bits20..27. */
 reset_body(&c);
 emit_insn(&c,ins(0x5180000000000000ull,14,13,0)|(12ull<<39)|(1ull<<53),32);
 CHECK(!c.fail&&strstr(c.body.buf,"fmz_fma("));
 reset_body(&c);
 emit_insn(&c,ins(0x5c68000000000000ull,14,12,13),40);
 CHECK(!c.fail&&!strstr(c.body.buf,"fmz_mul("));
 c.guarded=true;c.tex_alpha[12]=1;set_reg(&c,12,"0u");
 CHECK(c.inf_now[12]&&c.tex_alpha[12]);
 c.guarded=false;set_reg(&c,12,"0u");
 CHECK(!c.inf_now[12]&&!c.tex_alpha[12]&&c.inf_ever[12]);
 /* @!PT never writes; RZ writes never alter flags or reg_used. */
 c.inf_now[12]=1;
 emit_insn(&c,ins(0x5080000000000000ull,12,10,4)|(1ull<<19),48);
 CHECK(c.inf_now[12]);
 set_reg(&c,RZ,"x");CHECK(!c.reg_used[RZ]);
 reset_body(&c);
 return 0;
}
""")

    def test_glsl_fmz_helper_numeric_edges_are_actual_prelude_text(self):
        t = self.read("runtime/nvn/maxwell/translate.c")
        lines = [ast.literal_eval(line.strip()) for line in t.splitlines()
                 if line.strip().startswith(('"float fmz_mul(', '"float fmz_fma('))]
        self.assertEqual(len(lines), 2)
        # GLSL's float scalar/fma syntax is C-compatible. Only rename overloaded fma.
        code = "".join(lines).replace("fma(a, b, c)", "fmaf(a, b, c)")
        compiler_check(LIBC + code + r"""
int main(void) {
 CHECK(fmz_mul(0.0f,INFINITY)==0 && fmz_mul(-INFINITY,-0.0f)==0);
 CHECK(fmz_mul(0.0f,NAN)==0);
 CHECK(fmz_fma(0.0f,INFINITY,3.0f)==3.0f);
 CHECK(fmz_fma(INFINITY,-0.0f,-2.0f)==-2.0f);
 CHECK(__builtin_isnan(fmz_mul(1.0f,NAN)));
 CHECK(__builtin_isinf(fmz_mul(1.0f,INFINITY)));
 CHECK(fmz_mul(3.0f,4.0f)==12.0f && fmz_fma(3.0f,4.0f,5.0f)==17.0f);
 return 0;
}
""")

    def test_forward_branch_target_restores_ever_reciprocal_taint(self):
        compiler_check(self.translator_fixture() + r"""
int main(void) {
 uint64_t blob[26]={0};
 /* TEX alpha->r10, RCP->r12, BRA over an overwrite of r12 to FMUL. */
 blob[17]=0xc038000000000000ull | 10 | (20ull<<8) | (7ull<<16) | (1ull<<29) | (8ull<<31);
 blob[18]=0x5080000000000000ull | 12 | (10ull<<8) | (7ull<<16) | (4ull<<20);
 blob[19]=0xe240000000000000ull | 15 | (7ull<<16) | (24ull<<20);
 blob[21]=0x5080000000000000ull | 12 | (13ull<<8) | (7ull<<16);
 blob[22]=0x50b0000000070000ull;
 blob[23]=0x5c68000000000000ull | 14 | (12ull<<8) | (7ull<<16) | (13ull<<20) | (1ull<<44);
 blob[25]=0xe30000000007000full;
 ShaderKey key={0};key.glsl=1;
 ShaderInfo *s=maxwell_translate((uint8_t *)blob,sizeof blob,STAGE_FRAGMENT,&key);
 CHECK(s&&s->msl&&!s->error[0]);
 const char *body=strstr(s->msl,"void main(");CHECK(body);
 CHECK(strstr(body,"case 56u:")&&strstr(body,"fmz_mul("));
 maxwell_free(s);return 0;
}
""")

    def test_red_backward_branch_target_must_see_later_reciprocal(self):
        """Known RED: single-pass inf_ever merge misses a later backedge writer."""
        compiler_check(self.translator_fixture() + r"""
int main(void) {
 uint64_t blob[23]={0};
 /* FMUL at loop head, TEX/RCP later, BRA back to head: next iteration
    may multiply 0 by infinity. The shader is translated, never executed. */
 blob[17]=0x5c68000000000000ull | 14 | (12ull<<8) | (7ull<<16) | (13ull<<20) | (1ull<<44);
 blob[18]=0xc038000000000000ull | 10 | (20ull<<8) | (7ull<<16) | (1ull<<29) | (8ull<<31);
 blob[19]=0x5080000000000000ull | 12 | (10ull<<8) | (7ull<<16) | (4ull<<20);
 blob[21]=0xe240000000000000ull | 15 | (7ull<<16) | (0xffffd8ull<<20);
 blob[22]=0xe30000000007000full;
 ShaderKey key={0};key.glsl=1;
 ShaderInfo *s=maxwell_translate((uint8_t *)blob,sizeof blob,STAGE_FRAGMENT,&key);
 CHECK(s&&s->msl&&!s->error[0]);
 CHECK(strstr(s->msl,"case 8u:")&&strstr(s->msl,"pc = 8u;"));
 /* Desired contract, currently fails on exactly the audited upstream. */
 const char *body=strstr(s->msl,"void main(");CHECK(body);
 bool guarded=strstr(body,"fmz_mul(")!=NULL;
 maxwell_free(s);CHECK(guarded);return 0;
}
""", expected_runtime_failure=": guarded\n")

    def test_frontface_mask_producer_actual_translation_and_negative_controls(self):
        e = self.read("runtime/nvn/vulkan/exec.c")
        producer = re.search(r"float rs\[67\]\[4\];\s*for \(int k.*?rs\[66\]\[0\] = -1;", e, re.S)
        self.assertIsNotNone(producer)
        compiler_check(self.translator_fixture() + r"""
int main(void) {
""" + producer[0] + r"""
 CHECK(sizeof rs==67*16 && rs[66][0]==-1.0f);
 CHECK((uint32_t)(int32_t)rs[66][0]==UINT32_MAX);
 for(int k=0;k<67;k++) {
  CHECK(rs[k][1]==1&&rs[k][2]==0&&rs[k][3]==0);
  if(k!=66)CHECK(rs[k][0]==1);
 }
 ShaderInfo info={0};Ctx c={0};c.info=&info;c.stage=STAGE_FRAGMENT;c.glsl=true;
 attr_load(&c,4,0x3FC,NULL);
 CHECK(c.uses_front_facing&&c.uses_rscale);
 CHECK(strstr(c.body.buf,"uint(int(rscale[66][0]))"));
 free(c.body.buf);c=(Ctx){0};c.info=&info;c.stage=STAGE_FRAGMENT;
 attr_load(&c,4,0x3FC,NULL);
 CHECK(c.uses_front_facing&&!c.uses_rscale&&strstr(c.body.buf,"0xFFFFFFFFu"));
 free(c.body.buf);
 for(int stage=0;stage<=5;stage++) {
  c=(Ctx){0};c.info=&info;c.stage=stage;c.glsl=true;
  attr_load(&c,4,0x400,NULL); /* out-of-range ATTRIBUTE, not invalid register index */
  CHECK(!c.uses_front_facing&&!c.uses_rscale&&strstr(c.body.buf,"0u"));
  free(c.body.buf);
 }
 /* Synthetic, aligned blob: header + scheduling word + IPA front face + EXIT. */
 uint64_t blob[20]={0};
 blob[17]=0xe00000000000ff00ull | 2ull | (7ull<<16) | (0x3FCull<<28);
 blob[18]=0xe30000000007000full;blob[19]=0x50b0000000070000ull;
 ShaderKey key={0};key.glsl=1;
 ShaderInfo *s=maxwell_translate((uint8_t *)blob,sizeof blob,STAGE_FRAGMENT,&key);
 CHECK(s&&s->msl&&!s->error[0]);
 CHECK(strstr(s->msl,"rscale[67]")&&strstr(s->msl,"gl_FrontFacing ? uint(int(rscale[66][0]))"));
 maxwell_free(s);
 return 0;
}
""")

    def ui_fixture(self):
        e = self.read("runtime/nvn/vulkan/exec.c")
        code = LIBC + r"""
static float g_render_aspect=1.6f,g_ui_anchor_aspect=16.0f/9.0f;
static uint32_t g_render_size[2]={1280,720};
static uint64_t g_present_count=100;
static float g_preview_box_aspect[4];
static uint64_t g_preview_box_present[4];
static uint32_t pass_w=1280,pass_h=720;
static float pass_sx=1,pass_sy=1;
static struct { uint32_t ds[1];float viewport[1][4];int scissor[1][4]; } st;
"""
        code += region(e, "static bool ui_relax_scissor;", "static VkRenderPass pass_rp;")
        code += function(e, "static void pass_guest_size(")
        code += region(e, "typedef struct { float sx, kx, sy, ky; } PreviewMap;", "static VkRect2D scissor_rect(")
        return code

    def test_ui_group_threshold_stacking_bounds_and_widescreen_controls(self):
        compiler_check(self.ui_fixture() + r"""
static float m[UI_GROUP_MAX+2][16];
static void reset(void) {
 memset(&ui_group,0,sizeof ui_group);memset(&ui_group_prev,0,sizeof ui_group_prev);
 memset(ui_recent,0,sizeof ui_recent);memset(ui_group_known,0,sizeof ui_group_known);
 memset(m,0,sizeof m);ui_nrecent=0;ui_nknown=0;g_render_aspect=1.6f;
}
static void add(int i,float x,float y,int v) {
 CHECK(i<UI_GROUP_MAX+2);m[i][13]=v==0?y*.9f:v==2?720-(720-y)*.9f:360+(y-360)*.9f;
 ui_nrecent++;ui_group_add(m[i],100,x,y,v);
}
int main(void) {
 reset();add(0,100,100,0);add(1,100,536,2);CHECK(ui_group.n==2);
 ui_group_end();NEAR(m[0][13],126);NEAR(m[1][13],518.4f); /* centre */
 reset();add(0,100,42,0);add(1,100,560,2);CHECK(ui_group.n==1&&ui_group_prev.n==1);
 /* Threshold is inclusive at 470, split just above. */
 reset();add(0,100,100,0);add(1,100,570,2);CHECK(ui_group.n==2);
 reset();add(0,100,100,0);add(1,100,570.01f,2);CHECK(ui_group.n==1);
 /* Chat label and box: separate by a nonoverlapping diagonal piece, then settle. */
 reset();add(0,100,547,0);add(1,300,598,0);ui_group_end();
 add(2,100,596,2);add(3,300,708,2);ui_group_end();
 CHECK(ui_group_prev.v==2);
 NEAR(m[0][13],564.3f);NEAR(m[1][13],610.2f);
 NEAR(m[2][13],608.4f);NEAR(m[3][13],709.2f);
 CHECK(ui_recent[0].vanchor==2&&ui_recent[3].vanchor==2);
 /* No join on another layer, no horizontal overlap, or gap >8. */
 for(int mode=0;mode<3;mode++) {
  reset();add(0,100,100,0);add(1,300,200,0);ui_group_end();
  if(mode==0)ui_group_prev.z=102;
  if(mode==1)ui_group_prev.xmax=99;
  add(2,100,mode==2?209:208,2);add(3,300,300,2);ui_group_end();
  NEAR(m[0][13],90);
 }
 /* Cap does not write past 512; ring wrap and stale history are bounded. */
 reset();
 for(int i=0;i<UI_GROUP_MAX+1;i++) add(i,100,200,0);
 CHECK(ui_group.n==1&&ui_group_prev.n==UI_GROUP_MAX);ui_group_end();
 reset();g_render_aspect=21.0f/9.0f;
 add(0,500,100,0);add(1,780,536,2);ui_group_end();
 NEAR(m[0][12],640+(500-640)*(16.0f/21.0f));
 CHECK(!ui_group_prev.n); /* wider path is horizontal, not stacked vertical */
 return 0;
}
""")

    def test_preview_mapping_recent_tolerance_menu_age_and_rejections(self):
        compiler_check(self.ui_fixture() + r"""
int main(void) {
 PreviewMap pm;
 st.ds[0]=1;st.viewport[0][0]=204;st.viewport[0][1]=100;
 st.viewport[0][2]=300;st.viewport[0][3]=300;
 ui_nrecent=1;ui_recent[0].x=161;ui_recent[0].y=100;
 ui_recent[0].z=100;ui_recent[0].vanchor=2;ui_recent[0].hanchor=0;
 ui_menu_frame=99;
 CHECK(ui_preview_map(&pm));NEAR(pm.ky,.9f);NEAR(pm.sy,0);
 NEAR(ui_pv_y0,100);NEAR(ui_pv_y1,400);CHECK(ui_pv_v==0);
 ui_menu_frame=98;CHECK(ui_preview_map(&pm));NEAR(pm.sy,72);
 ui_menu_frame=99;ui_recent[0].x=143; /* outside 60-unit tolerance */
 CHECK(ui_preview_map(&pm));NEAR(pm.sy,72);
 ui_recent[0].x=144;CHECK(ui_preview_map(&pm));NEAR(pm.sy,0);
 /* Negative-height viewport records ordered top/bottom. */
 st.viewport[0][1]=400;st.viewport[0][3]=-300;
 CHECK(ui_preview_map(&pm));NEAR(ui_pv_y0,100);NEAR(ui_pv_y1,400);
 /* At 16:9 / full screen / no depth / wrong pass size no mapping. */
 g_render_aspect=16.0f/9.0f;CHECK(!ui_preview_map(&pm));g_render_aspect=1.6f;
 st.ds[0]=0;CHECK(!ui_preview_map(&pm));st.ds[0]=1;
 st.viewport[0][2]=1280;CHECK(!ui_preview_map(&pm));st.viewport[0][2]=7;
 CHECK(!ui_preview_map(&pm));st.viewport[0][2]=300;
 pass_h=600;CHECK(!ui_preview_map(&pm));pass_h=720;
 g_render_aspect=21.0f/9.0f;ui_recent[0].x=161;
 CHECK(ui_preview_map(&pm));NEAR(pm.kx,16.0f/21.0f);NEAR(pm.ky,1);
 return 0;
}
""")

    def test_red_stacked_group_final_anchor_must_update_scissor_prediction(self):
        """Known RED: stacked matrices change but remembered first-group anchor does not."""
        compiler_check(self.ui_fixture() + r"""
int main(void) {
 float m[4][16]={{0}};
 ui_nrecent=1;ui_group_add(m[0],100,100,547,0);
 ui_nrecent=2;ui_group_add(m[1],100,300,598,0);ui_group_end();
 ui_nrecent=3;ui_group_add(m[2],100,100,596,2);
 ui_nrecent=4;ui_group_add(m[3],100,300,708,2);ui_group_end();
 CHECK(ui_group_prev.v==2&&ui_recent[0].vanchor==2);
 CHECK(ui_group_lookup(100,100,596)==2);
 /* ui_scissor_v uses ui_group.predict, which is this lookup next frame. */
 CHECK(ui_group_lookup(100,100,547)==2);
 return 0;
}
""", expected_runtime_failure=": ui_group_lookup(100,100,547)==2\n")

    def test_changed_hud_anchor_leaves_loading_reticle_ammo_and_preview(self):
        e = self.read("runtime/nvn/vulkan/exec.c")
        loading = region(e, "bool loading_strip = false;", "// Front-end screens keep")
        ammo = region(e, "if (pos_y < 500.0f && pos_x < 900.0f)",
                      "} else if (fabsf(pos_z - 105.0f)")
        reticle = region(e, "if (fabsf(pos_z - 110.0f) < 0.5f && !ui_loading_pass)", "// A model preview's window")
        preview = region(e, "if (sy < 1.0f && ui_pv_v >= 0", "// The loading backdrop's tiles")
        compiler_check(LIBC + r"""
enum { ANCHOR_LEFT,ANCHOR_RIGHT,ANCHOR_CENTER,V_TOP,V_CENTER,V_BOTTOM };
static bool ui_loading_pass,ui_relax_scissor;
static float sy,pos_x,pos_y,pos_z,ui_pv_x0=204,ui_pv_x1=504,ui_pv_y0=100,ui_pv_y1=400;
static uint64_t ui_pv_present=100,g_present_count=100;
static int ui_pv_v=0,anchor,vanchor;
static bool load(void) {
""" + loading + r"""
 return loading_strip;
}
static void ammo(void) {
""" + ammo + r"""
}
static void vertical(void) {
""" + reticle + preview + r"""
}
int main(void) {
 pos_z=110;pos_y=150;sy=.9f;
 CHECK(!load()&&!ui_loading_pass);NEAR(sy,.9f);
 vanchor=V_TOP;vertical();CHECK(vanchor==V_CENTER);
 float mapped=360+(pos_y-360)*sy;NEAR(mapped,171);
 float strips[]={168,433,570};
 for(int i=0;i<3;i++) {
  ui_loading_pass=false;pos_y=strips[i];sy=.9f;
  CHECK(load()&&ui_loading_pass);NEAR(sy,1);
  pos_y=150;CHECK(!load());NEAR(sy,1);
 }
 pos_z=103;
 for(int y=360;y<=568;y+=104) {
  pos_x=970;pos_y=(float)y;ui_relax_scissor=false;ammo();
  CHECK(anchor==ANCHOR_RIGHT&&vanchor==V_BOTTOM&&ui_relax_scissor);
 }
 pos_x=899;pos_y=499;ui_relax_scissor=false;ammo();
 CHECK(anchor==ANCHOR_LEFT&&vanchor==V_TOP&&!ui_relax_scissor);
 pos_x=900;ammo();CHECK(anchor==ANCHOR_RIGHT&&vanchor==V_BOTTOM);
 pos_x=100;pos_y=500;ammo();CHECK(anchor==ANCHOR_RIGHT&&vanchor==V_BOTTOM);
 sy=.9f;pos_z=100;pos_x=144;pos_y=40;vanchor=V_BOTTOM;vertical();CHECK(vanchor==V_TOP);
 pos_x=143;vanchor=V_BOTTOM;vertical();CHECK(vanchor==V_BOTTOM);
 pos_x=204;pos_y=440;vertical();CHECK(vanchor==V_TOP);
 pos_y=441;vanchor=V_BOTTOM;vertical();CHECK(vanchor==V_BOTTOM);
 pos_y=100;g_present_count=103;vertical();CHECK(vanchor==V_BOTTOM);
 return 0;
}
""")

    def test_default_ini_lagcomp_environment_live_wiring(self):
        c = self.read("runtime/config.c")
        self.assertIn('"LagCompensation = On\\n"', c)
        self.assertIn('ON_OFF("Multiplayer", "LagCompensation", lag_compensation, false)', c)
        env = re.search(r'if \(\(e = getenv\("MHGU_LAGCOMP"\)\)\).*?;', c)[0]
        # Execute the production override statement with a controlled getenv leaf.
        code = LIBC + r"""
static const char *override;
static char *fake_getenv(const char *name) { CHECK(!strcmp(name,"MHGU_LAGCOMP"));return (char *)override; }
#define getenv fake_getenv
static struct { int lag_compensation; } g_config;
static void apply(void) { const char *e;
""" + env + r"""
}
int main(void) {
 g_config.lag_compensation=1;override=NULL;apply();CHECK(g_config.lag_compensation==1);
 override="0";apply();CHECK(!g_config.lag_compensation);
 override="1";apply();CHECK(g_config.lag_compensation);
 override="-1";apply();CHECK(g_config.lag_compensation);
 override="garbage";apply();CHECK(!g_config.lag_compensation);
 return 0;
}
"""
        compiler_check(code)


if __name__ == "__main__":
    unittest.main()
