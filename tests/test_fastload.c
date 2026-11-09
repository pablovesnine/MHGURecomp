// Synthetic public regression: includes real production source, no game data or fixed mmap.
// Compile from anywhere with -I/path/to/repo/tests -I/path/to/repo/runtime.
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
// cpu.h is Clang-oriented. GCC 13 lacks this unrelated helper's builtin.
// Neither tested source uses it: fail closed if a future change starts doing so.
#if defined(__GNUC__) && !defined(__clang__)
static uint32_t fixture_unsupported_bitreverse32(uint32_t x) {
    (void)x; fputs("unexpected cpu.h bitreverse helper\n", stderr); abort();
}
#define __builtin_bitreverse32 fixture_unsupported_bitreverse32
#endif
#include "hle.h"
#include "net/net.h"
#if defined(__GNUC__) && !defined(__clang__)
#undef __builtin_bitreverse32
#endif
#ifdef NDEBUG
#error "This regression must not be compiled with NDEBUG"
#endif
#define CHECK(x) do { if (!(x)) { \
    fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #x); exit(1); \
} } while (0)

// Every access must fit a real bounded segment. Eight bytes cover the widest scalar
// used here; no production memcpy operates through this fixture's G2H.
enum { AREA = 0x08001000, SOUND = 0x08001200, SYSTEM = 0x08001400 };
static _Alignas(16) unsigned char mem[0x600], global[8];
static void *guest(uint32_t a) {
    if (a == 0x2326764) return global;
    CHECK(a >= AREA && a - AREA <= sizeof mem - 8);
    return mem + (a - AREA);
}
#undef G2H
#define G2H(a) guest((uint32_t)(a))
#include "../runtime/hle/fastload.c"

static Cpu cpu;
static bool network;
static unsigned net_calls, originals, phase, registrations, hooks;
static uint32_t saved[16], expected_fn, expected_arg3, expected_wait;
static float expected_count, engine_step;
static HostFn entries[3];
static const uint32_t addresses[3] = {0x8bd720, 0x6e3ecc, 0x6dee48};
static const char *const names[3] = {
    "fastload:town_leave", "fastload:stream_stop", "fastload:music_fade"
};

bool ldn_net_up(void) {
    CHECK(phase == 0);
    net_calls++;
    return network;
}
uint32_t hle_register(const char *name, HostFn fn) {
    CHECK(registrations < 3 && hooks == registrations);
    CHECK(!strcmp(name, names[registrations]));
    entries[registrations] = fn;
    return 0xf1000000u + 4 * registrations++;
}
bool fnhook_set(uint32_t addr, uint32_t detour) {
    CHECK(hooks < 3 && registrations == hooks + 1);
    CHECK(addr == addresses[hooks] && detour == 0xf1000000u + 4 * hooks);
    hooks++;
    return true;
}
void fnhook_call_original(Cpu *c, uint32_t addr) {
    CHECK(c == &cpu && addr == expected_fn && phase == 0);
    originals++;
    phase = 1;
    for (unsigned i = 0; i < 16; i++)
        CHECK(c->r[i] == (i == 3 ? expected_arg3 : saved[i]));
    CHECK(LD32(AREA + 0xe4) == expected_wait);
    CHECK(fabsf(LDF(SOUND + 0x1c) - expected_count) < 0.0001f);
    // Emulate only the documented original's extra step, not the hook's logic.
    if (addr == 0x6dee48) STF(SOUND + 0x1c, LDF(SOUND + 0x1c) + engine_step);
    c->r[0] = 0xdecafbad;
    c->r[2] = 0x13579bdf;
}

static void init_checks(void) {
    const char *disabled[] = {"1", "10", "1anything"};
    for (unsigned i = 0; i < sizeof disabled / sizeof *disabled; i++) {
        int rc = setenv("MHGU_NO_FASTLOAD", disabled[i], 1); CHECK(rc == 0);
        fastload_init();
        CHECK(!registrations && !hooks);
    }
    const char *enabled[] = {NULL, "", "0", "true", " 1"};
    for (unsigned i = 0; i < sizeof enabled / sizeof *enabled; i++) {
        int rc = enabled[i] ? setenv("MHGU_NO_FASTLOAD", enabled[i], 1)
                            : unsetenv("MHGU_NO_FASTLOAD");
        CHECK(rc == 0);
        registrations = hooks = 0;
        fastload_init();
        CHECK(registrations == 3 && hooks == 3);
        CHECK(entries[0] == town_leave && entries[1] == stream_stop && entries[2] == music_fade);
    }
    int rc = unsetenv("MHGU_NO_FASTLOAD"); CHECK(rc == 0);
    puts("test-fastload: init and first-character opt-out: ok");
}

static void prepare(unsigned index, bool up, uint32_t from, uint32_t arg3) {
    memset(mem, 0xa5, sizeof mem);
    memset(global, 0, sizeof global);
    memset(&cpu, 0, sizeof cpu);
    for (unsigned i = 0; i < 16; i++) cpu.r[i] = 0xcafe0000u + i;
    cpu.r[0] = index == 0 ? AREA : SOUND;
    cpu.r[3] = arg3;
    cpu.r[14] = from;
    memcpy(saved, cpu.r, sizeof saved);
    network = up;
    originals = phase = net_calls = 0;
    expected_fn = addresses[index];
    expected_arg3 = arg3;
    expected_wait = 150;
    expected_count = 12.25f;
    engine_step = 1.0f;
    ST32(AREA + 0xe4, 150);
    STF(SOUND + 0x1c, 12.25f);
    ST32(0x2326764, SYSTEM);
    STF(SYSTEM + 0x68, engine_step);
}
static void invoke(unsigned index, unsigned queries) {
    unsigned char expected[sizeof mem], prior_global[sizeof global];
    memcpy(expected, mem, sizeof mem);
    memcpy(prior_global, global, sizeof global);
    memcpy(expected + 0xe4, &expected_wait, 4);
    float final_count = expected_count + (index == 2 ? engine_step : 0);
    memcpy(expected + (SOUND - AREA) + 0x1c, &final_count, 4);
    entries[index](&cpu);
    CHECK(originals == 1 && phase == 1 && net_calls == queries);
    CHECK(cpu.r[0] == 0xdecafbad && cpu.r[2] == 0x13579bdf);
    for (unsigned i = 1; i < 16; i++) {
        if (i == 2) continue;
        CHECK(cpu.r[i] == (i == 3 ? expected_arg3 : saved[i]));
    }
    CHECK(!memcmp(expected, mem, sizeof mem));
    CHECK(!memcmp(prior_global, global, sizeof global));
}
static void quest_checks(void) {
    for (unsigned up = 0; up < 2; up++)
        for (unsigned state = 0; state < 256; state++) {
            prepare(0, up, 0x1234, 999);
            ST8(AREA + 5, state);
            if (state == 9 && !up) expected_wait = 0;
            invoke(0, state == 9);
        }
    // Existing behavior: zero/negative waits are dropped to zero too.
    const uint32_t waits[] = {0, UINT32_MAX, 0x80000000};
    for (unsigned i = 0; i < sizeof waits / sizeof *waits; i++) {
        prepare(0, false, 0, 0);
        ST8(AREA + 5, 9); ST32(AREA + 0xe4, waits[i]); expected_wait = 0;
        invoke(0, 1);
    }
    puts("test-fastload: all states, network gate, wait before original, register/memory preservation: ok");
}
static void stream_checks(void) {
    const uint32_t sites[] = {0x6dea34, 0x6de210, 0x6dea30, 0x6dea38, 0x6de20c,
                              0x6de214, 0x8bd90c, 0x89fcc0, 0, UINT32_MAX};
    const uint32_t fades[] = {0, 50, 300, 1000, 1500, UINT32_MAX};
    for (unsigned up = 0; up < 2; up++)
        for (unsigned i = 0; i < sizeof sites / sizeof *sites; i++)
            for (unsigned j = 0; j < sizeof fades / sizeof *fades; j++) {
                prepare(1, up, sites[i], fades[j]);
                if (i < 2 && !up) expected_arg3 = 300;
                invoke(1, i < 2);
            }
    puts("test-fastload: exact stop return sites, offline-only 300ms, before original: ok");
}
static void music_checks(void) {
    const uint32_t sites[] = {0x8bd90c, 0x89fcc0, 0x8bd908, 0x8bd910, 0x89fcbc,
                              0x89fcc4, 0x6dea34, 0x6de210, 0, UINT32_MAX};
    // Fractional steps model multiple frame rates; no frame rate or counter cap is imposed by the hook.
    const float steps[] = {0, 0.4f, 1, 2, 2.5f};
    for (unsigned up = 0; up < 2; up++)
        for (unsigned i = 0; i < sizeof sites / sizeof *sites; i++)
            for (unsigned j = 0; j < sizeof steps / sizeof *steps; j++) {
                prepare(2, up, sites[i], 123);
                engine_step = steps[j]; STF(SYSTEM + 0x68, engine_step);
                if (i < 2 && !up) expected_count = 12.25f + 3.5f * engine_step;
                invoke(2, i < 2);
            }
    puts("test-fastload: counter adds 3.5 steps before original's 1, network/unrelated untouched: ok");
}
int main(void) {
    init_checks(); quest_checks(); stream_checks(); music_checks();
    puts("test-fastload: ok");
    return 0;
}
