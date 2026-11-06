// Public, synthetic supply-box regression. Includes the real hook to test its private entry/trace state.
// No game data, fixed guest mappings, renderer, or generated guest code is needed.
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
    fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #x); exit(1); \
} } while (0)

static _Noreturn void unexpected(const char *name) {
    fprintf(stderr, "test-villagehub: unexpected service: %s\n", name);
    exit(1);
}

// Override only after the real headers: ordinary LD/ST macros still exercise real slot/bitmap accesses.
// A small byte buffer avoids host fixed-address/ASan shadow-map conflicts, including under AArch64/QEMU.
static _Alignas(16) unsigned char memory[1024];
static void *synthetic_guest(uint32_t a) {
    CHECK(a >= 0x100 && a <= sizeof memory - 8);
    return memory + a;
}
static char last_log[1024];
static unsigned log_calls;
static void capture_log(const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(last_log, sizeof last_log, fmt, ap);
    va_end(ap);
    CHECK(n >= 0 && (size_t)n < sizeof last_log);
    log_calls++;
}
#undef G2H
#define G2H(a) synthetic_guest((uint32_t)(a))
#undef LOG
#define LOG(...) capture_log(__VA_ARGS__)
#include "../runtime/hle/villagehub.c"

// Independent fixture addresses/constants; expected answers must not follow a mistaken production layout.
enum { BOX = 0x100, QUEST = 0x300, SLOTS = BOX + 0xc, PRESENT = BOX + 0xc0, MAP = 0x6b3 };
static Cpu cpu;
static int setting;
static bool from_hub, reserve_in_original;
static unsigned original_calls, predicate_calls;
static uint32_t expected_box, expected_quest;

int config_live_village_in_hub(void) {
    CHECK(original_calls > 0);
    return setting;
}
bool hpscale_village_from_hub(uint32_t quest) {
    CHECK(original_calls > 0 && quest == expected_quest);
    predicate_calls++;
    return from_hub;
}
void fnhook_call_original(Cpu *c, uint32_t addr) {
    CHECK(c == &cpu && addr == 0x5ace14 && c->r[0] == expected_box);
    original_calls++;
    if (reserve_in_original) {
        ST16(SLOTS + 39 * 4, 0x1234);
        ST16(SLOTS + 39 * 4 + 2, 7);
    }
    c->r[0] = 0xdeadbeef;  // original return register isn't the supply-box address
}

// Unused paths are normally removed by --gc-sections; accidental execution must fail, not silently succeed.
void guest_call(Cpu *c, uint32_t a) { (void)c; (void)a; unexpected("guest_call"); }
uint32_t hle_alloc(uint32_t n) { (void)n; unexpected("hle_alloc"); }
uint32_t hle_register(const char *name, HostFn fn) {
    (void)name; (void)fn; unexpected("hle_register");
}
bool fnhook_set(uint32_t a, uint32_t detour) { (void)a; (void)detour; unexpected("fnhook_set"); }
uint64_t plat_now_ns(void) { unexpected("plat_now_ns"); }
void plat_sleep_until_ns(uint64_t t) { (void)t; unexpected("plat_sleep_until_ns"); }
void input_get(uint64_t *buttons, int32_t sticks[4]) {
    (void)buttons; (void)sticks; unexpected("input_get");
}

static void reset(uint32_t quest) {
    memset(memory, 0xa5, sizeof memory);
    memset(memory + BOX, 0, 0xc8);
    memset(&cpu, 0, sizeof cpu);
    ST32(BOX + 4, QUEST);
    ST32(QUEST + 8, quest);
    expected_box = BOX;
    expected_quest = quest;
    setting = 1;
    from_hub = true;
    reserve_in_original = false;
    original_calls = predicate_calls = log_calls = 0;
    last_log[0] = '\0';
    g_village = false;
    g_trace = 0;
}
static void filled(void) {
    for (unsigned i = 0; i < 40; i++) {
        ST16(SLOTS + 4 * i, 0x100 + i);
        ST16(SLOTS + 4 * i + 2, i + 2);
    }
}
static void invoke(void) {
    unsigned before = original_calls;
    cpu.r[0] = expected_box;
    supply_deliver(&cpu);
    CHECK(original_calls == before + 1);
    CHECK(cpu.r[0] == 0xdeadbeef);
}
static void unchanged(void) {
    unsigned char before[sizeof memory];
    memcpy(before, memory, sizeof before);
    invoke();
    CHECK(memcmp(before, memory, sizeof memory) == 0);
}
static void expect_maps(const unsigned *indices, unsigned n, const unsigned char *before) {
    unsigned char expected[sizeof memory];
    memcpy(expected, before, sizeof expected);
    for (unsigned j = 0; j < n; j++) {
        unsigned i = indices[j];
        CHECK(i < 40);
        uint16_t item = MAP, count = 1;
        uint32_t bits;
        memcpy(expected + SLOTS + 4 * i, &item, sizeof item);
        memcpy(expected + SLOTS + 4 * i + 2, &count, sizeof count);
        memcpy(&bits, expected + PRESENT + 4 * (i / 32), sizeof bits);
        bits |= UINT32_C(1) << (i % 32);
        memcpy(expected + PRESENT + 4 * (i / 32), &bits, sizeof bits);
    }
    CHECK(memcmp(expected, memory, sizeof memory) == 0);
}

static void gates(void) {
    reset(101);
    expected_box = 0;
    unchanged();  // no box still calls the original, with no synthetic memory access
    CHECK(predicate_calls == 0);

    reset(101);
    ST32(BOX + 4, 0);
    unchanged();  // no quest-data pointer
    CHECK(predicate_calls == 0);
    reset(0);
    unchanged();  // no quest number
    CHECK(predicate_calls == 0);

    reset(101);
    setting = 0;
    unchanged();  // setting off and counter not in Village mode
    CHECK(predicate_calls == 0);

    reset(10101);
    from_hub = false;
    unchanged();  // controlled predicate rejects a non-Village quest
    CHECK(predicate_calls == 1);

    reset(101);
    from_hub = false;
    unchanged();  // same Village quest, but village origin instead of Hub/Pub
    CHECK(predicate_calls == 1);
    puts("test-villagehub: no box/quest, off, non-Village, village-origin gates: ok");
}

static void empty_slots(void) {
    // 0/1/2/3/4 empty slots, including descending 39 -> 32 -> 31 across the bitmap boundary.
    const unsigned holes[] = {39, 32, 31, 5};
    for (unsigned n = 0; n <= 4; n++) {
        reset(101);
        filled();
        ST32(PRESENT, 0x15);
        ST32(PRESENT + 4, 0xa5000001);  // preserve unrelated bits, even unused bits above slot 39
        for (unsigned i = 0; i < n; i++) {
            ST16(SLOTS + 4 * holes[i], 0);
            ST16(SLOTS + 4 * holes[i] + 2, 0xffff);  // item, not stale count, defines emptiness
        }
        unsigned char before[sizeof memory];
        memcpy(before, memory, sizeof before);
        invoke();
        expect_maps(holes, n < 3 ? n : 3, before);
        CHECK(predicate_calls == 1);
        if (n >= 3) {
            CHECK(LD32(PRESENT) == 0x80000015);
            CHECK(LD32(PRESENT + 4) == 0xa5000081);
        }
    }
    puts("test-villagehub: 0/1/2/3/4 empty slots, descending 39/32/31, exact contents/presence: ok");
}

static void reserved_and_repeat(void) {
    reset(101);
    filled();
    const unsigned holes[] = {38, 36, 35};
    for (unsigned i = 0; i < 3; i++) ST16(SLOTS + 4 * holes[i], 0);
    ST16(SLOTS + 37 * 4 + 2, 0);  // nonempty delayed item with zero count must still be reserved
    unsigned char before[sizeof memory];
    memcpy(before, memory, sizeof before);
    invoke();
    expect_maps(holes, 3, before);
    CHECK(LD32(PRESENT + 4) == 0x58);  // slot 39/37 are nonempty delayed slots, still absent
    unchanged();  // now full; a further call has nowhere to put maps

    reset(101);
    reserve_in_original = true;
    invoke();  // original fills delayed slot 39 first; hook must skip it
    CHECK(LD16(SLOTS + 39 * 4) == 0x1234 && LD16(SLOTS + 39 * 4 + 2) == 7);
    CHECK(LD16(SLOTS + 38 * 4) == MAP && LD16(SLOTS + 37 * 4) == MAP && LD16(SLOTS + 36 * 4) == MAP);
    CHECK(LD32(PRESENT + 4) == 0x70);

    reset(101);
    setting = 0;
    g_village = true;  // live Village counter remains active while the setting switches off
    invoke();
    CHECK(predicate_calls == 1 && LD32(PRESENT + 4) == 0xe0);
    for (unsigned i = 37; i < 40; i++) CHECK(LD16(SLOTS + 4 * i) == MAP);
    invoke();
    CHECK(predicate_calls == 2 && LD32(PRESENT + 4) == 0xfc);
    for (unsigned i = 34; i < 40; i++) CHECK(LD16(SLOTS + 4 * i) == MAP);
    CHECK(LD16(SLOTS + 4 * 33) == 0);
    puts("test-villagehub: delayed slots/original ordering, active counter, adds 3 each call (not idempotent): ok");
}

static void trace_full(void) {
    reset(101);
    setting = 0;  // trace independently of map eligibility
    g_trace = 1;
    for (unsigned i = 0; i < 40; i++) {
        ST16(SLOTS + 4 * i, UINT16_MAX);
        ST16(SLOTS + 4 * i + 2, UINT16_MAX);
    }
    CHECK(LD32(PRESENT) == 0 && LD32(PRESENT + 4) == 0);
    unchanged();
    CHECK(log_calls == 1 && predicate_calls == 0);
    const char *trace = strstr(last_log, " supply box:");
    CHECK(trace && strstr(trace, " 0:ffff x65535(later)"));
    trace += strlen(" supply box:");
    size_t n = strlen(trace);
    CHECK(n > 1 && trace[n - 1] == '\n');
    CHECK(n - 1 <= 40 * 16 - 1);  // local slot string is bounded, with room for its terminator
    puts("test-villagehub: all 40 slots UINT16_MAX, clear presence, bounded trace: ok");
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--trace-full") == 0) {
        trace_full();
    } else {
        CHECK(argc == 1);
        gates();
        empty_slots();
        reserved_and_repeat();
        fflush(stdout);  // preserve completed semantic checks if ASan catches the trace regression
        trace_full();
    }
    puts("test-villagehub: ok");
    return 0;
}
