// Synthetic text/list lifecycle regression: real production file, no game files or fixed mappings.
// Build with the project's runtime headers (old 0.15.4 or new 0.16.0), see run-tests.sh.
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "config.h"
#include "hle.h"
#include "mods.h"
#include "hle/input.h"

#define CHECK(x) do { if (!(x)) { \
    fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #x); exit(1); \
} } while (0)

// Fixture addresses are independent of implementation macros. All subtraction happens before
// pointer addition: notably, no temporarily out-of-object `mem + address - base`.
enum { GC = 0x1000, MGR = 0x2000, VT = 0x2100, SEL = 0x3000, LIST = 0x4000,
       UI = 0x6000, ARC = 0x7000, QUEST = 0x8000, PATH = 0x9000, GET = 0xabcdef };
static _Alignas(16) unsigned char memory[0x8000], globals[3][16];
static struct { unsigned char before[16], text[64], after[16]; } pathbuf;
static void *guest(uint32_t a) {
    static const uint32_t bases[] = {0x1a8ca48, 0x2326a64, 0x1a8ae38};
    for (unsigned i = 0; i < 3; i++)
        if (a >= bases[i] && a - bases[i] <= sizeof globals[i] - 8)
            return globals[i] + (a - bases[i]);
    if (a >= PATH && a - PATH <= sizeof pathbuf.text - 8)
        return pathbuf.text + (a - PATH);
    CHECK(a >= GC && a - GC <= sizeof memory - 8);
    return memory + (a - GC);
}
static char last_log[1024];
static unsigned logs;
static void capture(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(last_log, sizeof last_log, fmt, ap);
    va_end(ap);
    CHECK(n >= 0 && (size_t)n < sizeof last_log);
    logs++;
}
#undef G2H
#define G2H(a) guest((uint32_t)(a))
#undef LOG
#define LOG(...) capture(__VA_ARGS__)
#include "../runtime/hle/villagehub.c"

enum { E_ARCHIVE = 1, E_RELEASE, E_LIST, E_DONE, E_CATEGORIES, E_BUILD, E_UI,
       E_LOOKUP, E_UNLOCK, E_QUEST, E_DRAW, E_ROWS, E_FILL, E_GET };
static unsigned events[20000], nevents, gets, releases, loads, dones, cats, lookups, sleeps;
static int setting;
static bool unlocked, arc_null, quest_null, arc_ready, done_never, lookup_exists;
static unsigned ready_after, done_after, expected_load_sleeps;
static uint64_t now;
static uint64_t buttons;
static Cpu cpu;
static uint32_t initial[16], last_args[16];
static unsigned expected_ui_area, expected_category_area;
static bool check_reloading;
static void event(unsigned e) { CHECK(nevents < sizeof events / sizeof *events); events[nevents++] = e; }
static void sequence(const unsigned *v, size_t n) {
    CHECK(nevents == n);
    CHECK(!memcmp(events, v, n * sizeof *v));
}
#define SEQ(...) do { const unsigned v[] = {__VA_ARGS__}; sequence(v, sizeof v / sizeof *v); } while (0)
static void guards(void) {
    for (unsigned i = 0; i < 16; i++) CHECK(pathbuf.before[i] == 0xa5 && pathbuf.after[i] == 0xa5);
}
static void regs(void) {
    for (unsigned i = 0; i < 16; i++) cpu.r[i] = 0xcafe0000 + i;
    memcpy(initial, cpu.r, sizeof initial);
}
static void clobber(Cpu *c, uint32_t result) {
    for (unsigned i = 0; i < 16; i++) c->r[i] = 0xbad00000 + i;
    c->r[0] = result;
}
int config_live_village_in_hub(void) { return setting; }
bool hpscale_village_from_hub(uint32_t q) { (void)q; CHECK(0); return false; }
uint64_t plat_now_ns(void) { return now; }
void plat_sleep_until_ns(uint64_t t) {
    CHECK(t == now + 1000000);
    now = t;
    sleeps++;
    if (ready_after && sleeps == ready_after) ST32(ARC + 0x50, 1);
    CHECK(sleeps <= 10000); // fail closed if the bounded wait regresses
}
void input_get(uint64_t *b, int32_t sticks[4]) {
    *b = buttons;
    memset(sticks, 0, 4 * sizeof *sticks);
}
void fnhook_call_original(Cpu *c, uint32_t a) {
    CHECK(c == &cpu);
    memcpy(last_args, c->r, sizeof last_args);
    switch (a) {
    case 0x5b7fd8:
        event(E_LIST); loads++;
        if (check_reloading) CHECK(g_reloading && !g_list_stale);
        if (expected_load_sleeps != UINT32_MAX) CHECK(sleeps == expected_load_sleeps);
        CHECK(c->r[0] == SEL);
        // List loading must never impersonate the Village area (worker receives the type).
        CHECK(!LD32(0x1a8ca48) || LD8(GC + 0x4c) != 1 || !g_village || !check_reloading);
        clobber(c, 0x12345678);
        break;
    case 0x981e34:
        event(E_UI);
        CHECK(c->r[0] == UI && !memcmp(c->r, initial, sizeof initial));
        if (LD32(0x1a8ca48)) CHECK(LD8(GC + 0x4c) == expected_ui_area);
        c->r[0] = 0xdeadbeef; c->r[1] = 0xfeedface;
        break;
    case 0x5b85d8: event(E_BUILD); goto category;
    case 0x5bb318: event(E_FILL); goto category;
    case 0x5bc96c: event(E_GET); goto category;
    case 0x983074: event(E_ROWS); goto category;
    case 0x981bb0: event(E_DRAW); goto category;
    category:
        CHECK(LD8(GC + 0x4c) == expected_category_area);
        c->r[0] = 0x88888888;
        break;
    case 0x5ba50c:
        event(E_LOOKUP); lookups++;
        CHECK(c->r[0] == SEL || !c->r[0]);
        c->r[0] = lookup_exists ? QUEST : 0;
        if (last_args[0] == SEL && LD32(SEL + 0x28) && LD32(LIST) == QUEST) c->r[0] = QUEST;
        break;
    default: CHECK(0);
    }
}
void guest_call(Cpu *c, uint32_t a) {
    CHECK(c == &cpu);
    if (a == GET) {
        CHECK(c->r[0] == MGR && c->r[2] == PATH && c->r[3] == 2);
        CHECK(memchr(pathbuf.text, 0, 64));
        guards();
        if (c->r[1] == 0x2324df0) {
            event(E_ARCHIVE); gets++;
            CHECK(!strcmp((char *)pathbuf.text, "loc\\arc\\quest\\vq"));
            ST32(ARC + 0x50, arc_ready ? 1 : 0);
            clobber(c, arc_null ? 0 : ARC);
        } else {
            CHECK(c->r[1] == 0x1a8ab98);
            char expected[64];
            snprintf(expected, sizeof expected, "loc\\quest\\questData\\questData_%07u", initial[1]);
            CHECK(!strcmp((char *)pathbuf.text, expected));
            event(E_QUEST);
            clobber(c, quest_null ? 0 : QUEST);
            if (!quest_null) lookup_exists = true;
        }
    } else if (a == 0xa87660) {
        event(E_RELEASE); releases++;
        CHECK(c->r[0] == ARC && !c->r[1] && !c->r[2] && !c->r[3]);
        clobber(c, 0);
    } else if (a == 0x5b7fd8) {
        CHECK(c->r[0] == SEL && !c->r[1] && !c->r[2] && !c->r[3]);
        CHECK(g_reloading && !g_list_stale);
        list_load(c);  // re-enter the real installed hook, not a mock loader
    } else if (a == 0x5b8070) {
        event(E_DONE); dones++;
        CHECK(c->r[0] == SEL && !c->r[1] && !c->r[2] && !c->r[3]);
        CHECK(!g_reloading);
        clobber(c, !done_never && dones >= done_after);
    } else if (a == 0x5ba8fc) {
        event(E_CATEGORIES); cats++;
        CHECK(c->r[0] == SEL && !c->r[1] && !c->r[2] && !c->r[3]);
        CHECK(!g_reloading);
        CHECK(LD8(GC + 0x4c) == 0 || LD8(GC + 0x4c) == 7);
        // The categories' internal hooked builders, not the outer call, impersonate a village.
        category_build(c);
        c->r[0] = SEL;
        category_fill(c);
        c->r[0] = SEL;
        category_get(c);
        clobber(c, 0);
    } else if (a == 0x74af8c) {
        event(E_UNLOCK);
        CHECK(c->r[0] == initial[1] && c->r[1] == 0xff && !c->r[2] && !c->r[3]);
        clobber(c, unlocked ? 1 : 0);
    } else CHECK(0);
}
static HostFn registered[11];
static unsigned nregistered, ninstalled;
static const uint32_t hook_addresses[] = {
    0x5a08e8, 0x5ace14, 0x5b8090, 0x5ba50c, 0x5b7fd8, 0x5b85d8,
    0x5bb318, 0x5bc96c, 0x983074, 0x981e34, 0x981bb0
};
static const char *hook_names[] = {
    "spawn_update", "supply_deliver", "quest_filter", "quest_lookup", "list_load", "category_build",
    "category_fill", "category_get", "ui_rows", "ui_update", "ui_draw"
};
uint32_t hle_alloc(uint32_t n) { CHECK(n == 64); return PATH; }
uint32_t hle_register(const char *name, HostFn fn) {
    CHECK(nregistered < 11);
    char expected[64];
    snprintf(expected, sizeof expected, "villagehub:%s", hook_names[nregistered]);
    CHECK(!strcmp(name, expected));
    registered[nregistered] = fn;
    return 0x3000000 + 16 * nregistered++;
}
bool fnhook_set(uint32_t a, uint32_t detour) {
    CHECK(ninstalled < 11 && a == hook_addresses[ninstalled]);
    CHECK(detour == 0x3000000 + 16 * ninstalled);
    ninstalled++;
    return true;
}
static void reset(void) {
    memset(memory, 0, sizeof memory);
    memset(globals, 0, sizeof globals);
    memset(&pathbuf, 0xa5, sizeof pathbuf);
    ST32(0x1a8ca48, GC); ST32(0x2326a64, MGR); ST32(0x1a8ae38, SEL);
    ST32(MGR, VT); ST32(VT + 0x30, GET);
    ST32(SEL + 0x24, LIST);
    ST8(GC + 0xa5, 7); ST8(GC + 0x4c, 0); ST8(UI + 0x3c, 1);
    g_village = g_reloading = g_list_stale = false;
    g_vq_arc = 0; g_path = PATH; g_trace = 0;
    nevents = gets = releases = loads = dones = cats = lookups = sleeps = logs = 0;
    setting = 1; unlocked = arc_ready = true;
    arc_null = quest_null = done_never = lookup_exists = check_reloading = false;
    ready_after = 0; done_after = 1; expected_load_sleeps = UINT32_MAX; now = 1000; buttons = 0;
    expected_ui_area = expected_category_area = 1;
    regs();
}
static void tick(unsigned state, uint64_t b) {
    cpu.r[0] = UI; memcpy(initial, cpu.r, sizeof initial);
    ST8(UI + 0x3c, state); buttons = b;
    unsigned a = LD32(0x1a8ca48) ? LD8(GC + 0x4c) : 0;
    ui_update(&cpu);
    CHECK(cpu.r[0] == 0xdeadbeef && cpu.r[1] == 0xfeedface);
    CHECK(!memcmp(cpu.r + 2, initial + 2, 14 * sizeof *initial));
    if (LD32(0x1a8ca48)) CHECK(LD8(GC + 0x4c) == a);
    guards();
}
static void release_buttons(void) {
    expected_ui_area = LD8(GC + 0x4c);
    tick(5, 0);
    nevents = 0;
}
static void text_languages(void) {
    for (unsigned l = 0; l <= 9; l++) {
        reset(); ST8(GC + 0xa5, l);
        village_text(&cpu, true);
        CHECK(gets == (l == 7 || l == 8));
        CHECK(g_vq_arc == (gets ? ARC : 0));
        CHECK(!memcmp(cpu.r, initial, sizeof initial));
        village_text(&cpu, true);
        CHECK(gets == (l == 7 || l == 8));
        village_text(&cpu, false);
        CHECK(!g_vq_arc && releases == gets);
        village_text(&cpu, false);
        CHECK(releases == gets && !memcmp(cpu.r, initial, sizeof initial));
        guards();
    }
    reset(); ST8(GC + 0xa5, 255); village_text(&cpu, true); CHECK(!gets);
    reset(); ST32(0x1a8ca48, 0); village_text(&cpu, true); CHECK(!gets);
    reset(); ST32(0x2326a64, 0); village_text(&cpu, true); CHECK(!gets);
    reset(); village_text(&cpu, true);
    ST32(0x2326a64, 0); village_text(&cpu, true);
    CHECK(g_vq_arc == ARC && gets == 1 && !releases);
    ST8(GC + 0xa5, 0);
    village_text(&cpu, true); CHECK(!g_vq_arc && releases == 1);
    CHECK(!memcmp(cpu.r, initial, sizeof initial));
    SEQ(E_ARCHIVE, E_RELEASE);
    puts("text: languages 7/8 versus 0..6/9/255, null control/manager, single reference/release, path64/registers: ok");
}
static void text_waits(void) {
    reset(); arc_ready = false; ready_after = 3;
    village_text(&cpu, true);
    CHECK(sleeps == 3 && now == 3001000 && g_vq_arc == ARC);
    CHECK(strstr(last_log, "loaded") && !memcmp(cpu.r, initial, sizeof initial));
    reset(); arc_null = true;
    village_text(&cpu, true);
    CHECK(!g_vq_arc && !sleeps && strstr(last_log, "not found"));
    village_text(&cpu, false); CHECK(!releases);
    arc_null = false; village_text(&cpu, true); CHECK(gets == 2 && g_vq_arc == ARC);
    reset(); arc_ready = false;
    village_text(&cpu, true);
    CHECK(sleeps == 5000 && now == 5000001000ull && g_vq_arc == ARC);
    CHECK(strstr(last_log, "still loading"));
    village_text(&cpu, true); CHECK(gets == 1 && sleeps == 5000);
    village_text(&cpu, false); CHECK(releases == 1 && !g_vq_arc);
    CHECK(!memcmp(cpu.r, initial, sizeof initial));
    guards();
    puts("text: immediate/delayed/null-retry/5s timeout, timeout holds reference until release: ok");
}
static void menus(void) {
    for (unsigned area = 0; area <= 7; area += 7)
        for (unsigned state = 1; state <= 2; state++)
            for (unsigned bit = 6; bit <= 7; bit++) {
                reset(); ST8(GC + 0x4c, area); release_buttons();
                check_reloading = true; expected_ui_area = expected_category_area = 1;
                tick(state, 1ull << bit);
                CHECK(g_village && !g_list_stale && !g_reloading);
                CHECK(LD8(UI + 0x3c) == 0 && gets == 1 && loads == 1 && cats == 1);
                SEQ(E_ARCHIVE, E_LIST, E_DONE, E_CATEGORIES, E_BUILD, E_FILL, E_GET, E_UI);
                nevents = 0; tick(state, 1ull << bit); // held is not a new edge
                CHECK(g_village && loads == 1); SEQ(E_UI);
                release_buttons();
                expected_ui_area = expected_category_area = area;
                tick(state, 1ull << bit);
                CHECK(!g_village && releases == 1 && loads == 2);
                SEQ(E_RELEASE, E_LIST, E_DONE, E_CATEGORIES, E_BUILD, E_FILL, E_GET, E_UI);
            }
    for (unsigned state = 0; state <= 6; state++) {
        if (state == 1 || state == 2) continue;
        reset(); release_buttons(); expected_ui_area = 0;
        tick(state, 1ull << 6);
        CHECK(!g_village && !loads && !gets); SEQ(E_UI);
    }
    for (unsigned area = 1; area <= 8; area++) {
        if (area == 7) continue;
        reset(); ST8(GC + 0x4c, area); release_buttons(); expected_ui_area = area;
        tick(1, 1ull << 6); CHECK(!g_village && !loads); SEQ(E_UI);
    }
    reset(); release_buttons(); ST32(0x1a8ca48, 0);
    tick(1, 1ull << 6); CHECK(!g_village && !loads); SEQ(E_UI);
    reset(); release_buttons(); expected_ui_area = 0;
    tick(1, 1ull << 0); CHECK(!g_village && !loads); SEQ(E_UI);
    reset(); release_buttons(); setting = 0; expected_ui_area = 0;
    tick(1, 1ull << 6); CHECK(!g_village && !loads);
    reset(); g_village = true; setting = 0; release_buttons();
    CHECK(g_village && !loads); // do not alter an open quest/accept screen
    expected_ui_area = expected_category_area = 0;
    tick(2, 0); CHECK(!g_village && loads == 1 && LD8(UI + 0x3c) == 0);
    puts("menus: Hub/Pub rank/star L/R edge switches; other states/buttons/areas/control/setting gates; off defers: ok");
}
static void returning(void) {
    reset(); release_buttons(); g_village = true;
    cpu.r[0] = SEL; memcpy(initial, cpu.r, sizeof initial);
    list_load(&cpu);
    CHECK(g_list_stale && !g_reloading && g_vq_arc == ARC);
    SEQ(E_ARCHIVE, E_LIST);
    CHECK(cpu.r[0] == 0x12345678);
    nevents = 0; expected_ui_area = 0;
    tick(5, 0); CHECK(g_list_stale && loads == 1); SEQ(E_UI);
    nevents = 0; expected_ui_area = expected_category_area = 1; check_reloading = true;
    tick(1, 0);
    CHECK(!g_list_stale && !g_reloading && g_village && loads == 2 && gets == 1);
    CHECK(LD8(UI + 0x3c) == 0);
    SEQ(E_LIST, E_DONE, E_CATEGORIES, E_BUILD, E_FILL, E_GET, E_UI);
    nevents = 0; tick(2, 0); CHECK(loads == 2); SEQ(E_UI);
    nevents = 0; check_reloading = false; ST8(GC + 0x4c, 2); cpu.r[0] = SEL;
    list_load(&cpu);
    CHECK(g_village && !g_list_stale && !g_vq_arc && releases == 1);
    SEQ(E_RELEASE, E_LIST); // leaving the Hub/Pub does not retain its extra archive reference
    reset(); g_village = true; g_reloading = g_list_stale = true; cpu.r[0] = SEL;
    list_load(&cpu); CHECK(g_reloading && g_list_stale); // nested job doesn't overwrite stale
    reset(); g_list_stale = true; cpu.r[0] = SEL;
    list_load(&cpu); CHECK(!g_list_stale);
    reset(); g_village = g_list_stale = true; ST8(GC + 0x4c, 2); cpu.r[0] = SEL;
    list_load(&cpu); CHECK(!g_list_stale && !gets);
    reset(); g_village = g_list_stale = true; ST32(0x1a8ca48, 0); cpu.r[0] = SEL;
    list_load(&cpu); CHECK(!g_list_stale && !gets);
    reset(); g_list_stale = true; ST32(0x1a8ae38, 0);
    reload_list(&cpu); CHECK(g_list_stale && !loads && !g_reloading); // no selector, no work
    reset(); ST8(GC + 0xa5, 0); g_village = true; check_reloading = true;
    done_after = 3; reload_list(&cpu);
    CHECK(loads == 1 && dones == 3 && sleeps == 2 && cats == 1 && !g_reloading && !g_list_stale);
    CHECK(!memcmp(cpu.r, initial, sizeof initial));
    reset(); ST8(GC + 0xa5, 0); g_village = true; done_never = true;
    reload_list(&cpu);
    CHECK(loads == 1 && dones == 5001 && sleeps == 5000 && cats == 1);
    CHECK(!g_reloading && !g_list_stale && !memcmp(cpu.r, initial, sizeof initial));
    reset(); g_village = true; arc_ready = false; ready_after = expected_load_sleeps = 3;
    cpu.r[0] = SEL; list_load(&cpu);
    CHECK(sleeps == 3 && g_list_stale); SEQ(E_ARCHIVE, E_LIST);
    reset(); g_village = true; arc_ready = false; expected_load_sleeps = 5000;
    cpu.r[0] = SEL; list_load(&cpu);
    CHECK(sleeps == 5000 && g_vq_arc == ARC && g_list_stale); SEQ(E_ARCHIVE, E_LIST);
    reset(); g_village = true; arc_null = true; expected_load_sleeps = 0;
    cpu.r[0] = SEL; list_load(&cpu);
    CHECK(!g_vq_arc && g_list_stale); SEQ(E_ARCHIVE, E_LIST);
    puts("return: area-load stale, menu-only one-time refresh, reentry guard, reset/no-selector, delayed/5s done: ok");
}
static void lookup_selector(uint32_t sel, uint32_t q) {
    regs(); cpu.r[0] = sel; cpu.r[1] = q; memcpy(initial, cpu.r, sizeof initial);
    quest_lookup(&cpu);
    CHECK(!memcmp(cpu.r + 1, initial + 1, 15 * sizeof *initial));
    guards();
}
static void lookup(uint32_t q) { lookup_selector(SEL, q); }
static void posted(void) {
    const unsigned groups[] = {0, 3, 10, 13};
    for (unsigned i = 0; i < 4; i++) {
        reset(); lookup(groups[i] * 10000 + 101);
        CHECK(cpu.r[0] == QUEST && LD32(LIST) == QUEST && LD32(SEL + 0x28) == 1);
        CHECK(g_vq_arc == ARC && gets == 1 && lookups == 2);
        if (groups[i] == 13) SEQ(E_LOOKUP, E_ARCHIVE, E_QUEST, E_LOOKUP);
        else SEQ(E_LOOKUP, E_UNLOCK, E_ARCHIVE, E_QUEST, E_LOOKUP);
        CHECK(last_args[0] == SEL && last_args[1] == groups[i] * 10000 + 101);
        nevents = 0; g_village = false; cpu.r[0] = SEL;
        list_load(&cpu); CHECK(!g_vq_arc && releases == 1); SEQ(E_RELEASE, E_LIST);
    }
    reset(); lookup(10101);
    CHECK(cpu.r[0] == QUEST && !gets); SEQ(E_LOOKUP, E_QUEST, E_LOOKUP);
    reset(); ST8(GC + 0xa5, 0); lookup(102); CHECK(cpu.r[0] == QUEST && !gets);
    reset(); unlocked = false; lookup(103);
    CHECK(!cpu.r[0] && !gets && !LD32(SEL + 0x28)); SEQ(E_LOOKUP, E_UNLOCK);
    reset(); lookup_exists = true; lookup(104); CHECK(cpu.r[0] == QUEST && !gets); SEQ(E_LOOKUP);
    reset(); setting = 0; lookup(105); CHECK(!cpu.r[0] && !gets); SEQ(E_LOOKUP);
    reset(); setting = 0; g_village = true; lookup(106); CHECK(cpu.r[0] == QUEST && gets == 1);
    reset(); ST8(GC + 0x4c, 1); lookup(107); CHECK(!cpu.r[0] && !gets); SEQ(E_LOOKUP);
    reset(); ST32(0x1a8ca48, 0); lookup(108); CHECK(!cpu.r[0] && !gets); SEQ(E_LOOKUP);
    reset(); ST32(SEL + 0x24, 0); lookup(109); CHECK(!cpu.r[0] && !gets);
    reset(); ST32(SEL + 0x28, 0x360); lookup(110); CHECK(!cpu.r[0] && !gets);
    reset(); ST32(0x2326a64, 0); lookup(111); CHECK(!cpu.r[0] && !gets);
    reset(); lookup_selector(0, 112); CHECK(!cpu.r[0] && !gets); SEQ(E_LOOKUP);
    reset(); lookup(0); CHECK(!cpu.r[0] && !gets); SEQ(E_LOOKUP);
    reset(); lookup(9999999); CHECK(cpu.r[0] == QUEST && !gets); SEQ(E_LOOKUP, E_QUEST, E_LOOKUP);
    reset(); lookup(10000000); CHECK(!cpu.r[0] && !gets); SEQ(E_LOOKUP);
    reset(); quest_null = true; lookup(912); CHECK(!cpu.r[0] && gets == 1 && g_vq_arc == ARC);
    CHECK(!LD32(SEL + 0x28)); nevents = 0;
    lookup(912); CHECK(!cpu.r[0] && gets == 1); SEQ(E_LOOKUP); // failed-quest cache
    village_text(&cpu, false); CHECK(releases == 1);
    reset(); arc_null = true; lookup(913);
    CHECK(cpu.r[0] == QUEST && !g_vq_arc); // upstream does not block on null archive
    reset(); arc_ready = false; lookup(914);
    CHECK(cpu.r[0] == QUEST && g_vq_arc == ARC && sleeps == 5000); // nor on archive timeout
    puts("posted: groups 0/3/10/13 text-before-quest/retry-original, other groups/languages/gates, failed cache/null/timeout: ok");
}
static void adapters(void) {
    reset(); g_village = true;
    cpu.r[0] = UI; ui_rows(&cpu); CHECK(LD8(GC + 0x4c) == 0 && cpu.r[0] == 0x88888888);
    for (unsigned state = 0; state <= 5; state++) {
        cpu.r[0] = UI; ST8(UI + 0x3c, state);
        expected_category_area = state <= 2 ? 1 : 0;
        ui_draw(&cpu); CHECK(LD8(GC + 0x4c) == 0);
    }
    puts("adapters: category/row/draw temporary area restore and original result: ok");
}
int main(void) {
    reset(); villagehub_init();
    CHECK(nregistered == 11 && ninstalled == 11 && g_path == PATH);
    CHECK(registered[4] == list_load && registered[0] == spawn_update && registered[1] == supply_deliver);
    text_languages(); text_waits(); menus(); returning(); posted(); adapters();
    puts("test-villagehub-text: ok");
    return 0;
}
