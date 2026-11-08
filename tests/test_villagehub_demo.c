// Synthetic spawn-demo regression: real hook, bounded guest segments, no game data.
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

// Independent fixture addresses/layout, not aliases of implementation constants.
enum { SQ = 0x1000, NET = 0x3000, PLAYERS = 0x4000, HUNTER = 0x5000 };
static _Alignas(16) unsigned char memory[0xa000], globals[3][8], events[107 * 12 + 8];
static void *guest(uint32_t a) {
    const uint32_t addresses[] = {0x1a843f0, 0x1a85b58, 0x17a06fc};
    for (unsigned i = 0; i < 2; i++)
        if (a == addresses[i]) return globals[i];
    if (a >= addresses[2] && a <= addresses[2] + sizeof events - 8)
        return events + a - addresses[2];
    CHECK(a >= SQ && a <= sizeof memory - 8);
    return memory + a;
}
static unsigned logs;
static void capture(const char *fmt, ...) {
    char buf[512];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    CHECK(n >= 0 && (size_t)n < sizeof buf);
    logs++;
}
#undef G2H
#define G2H(a) guest((uint32_t)(a))
#undef LOG
#define LOG(...) capture(__VA_ARGS__)
#include "../runtime/hle/villagehub.c"

static Cpu cpu;
static unsigned releases, originals, predicates, phase;
static uint32_t saved[16];
static bool from_hub;
int config_live_village_in_hub(void) { CHECK(0); return 0; }
bool hpscale_village_from_hub(uint32_t q) {
    CHECK(phase == 0 && q == 404);
    predicates++;
    return from_hub;
}
void guest_call(Cpu *c, uint32_t a) {
    CHECK(c == &cpu && a == 0x5a3ecc && phase == 0);
    CHECK(c->r[0] == SQ && c->r[1] == 1 && !c->r[2] && !c->r[3]);
    releases++;
    phase = 1;
    // call4 must restore all registers before invoking the original update.
    for (unsigned i = 0; i < 16; i++) c->r[i] = 0xbad00000 + i;
}
void fnhook_call_original(Cpu *c, uint32_t a) {
    CHECK(c == &cpu && a == 0x5a08e8 && phase <= 1);
    CHECK(!memcmp(c->r, saved, sizeof saved));
    originals++;
    phase = 2;
    c->r[0] = 0xdeadbeef;
}

static void reset(void) {
    memset(memory, 0, sizeof memory);
    memset(globals, 0, sizeof globals);
    memset(events, 0, sizeof events);
    ST32(0x1a843f0, NET);
    ST32(0x1a85b58, PLAYERS);
    ST8(NET + 0x63e, 1);
    ST8(SQ + 0x50, 2);
    ST32(SQ + 0xe0, 404);
    ST8(SQ + 0x1514 + 12 * 4, 4);  // last spawn slot, waiting, parameter 0
    ST32(PLAYERS + 0x1c + 4 * 3, HUNTER);
    ST8(HUNTER + 0x1054, 7);  // last hunter
    ST8(0x17a06fc + 12 * 106, 1);  // last event
    ST8(0x17a06fc + 12 * 106 + 3, 7);
    ST32(0x17a06fc + 12 * 106 + 8, 404);
    g_demo_released = g_demo_test = false;
    from_hub = true;
    releases = originals = predicates = logs = 0;
}
static void invoke(uint32_t sq, unsigned expected) {
    unsigned before = originals;
    for (unsigned i = 0; i < 16; i++) cpu.r[i] = 0xcafe0000 + i;
    cpu.r[0] = sq;
    memcpy(saved, cpu.r, sizeof saved);
    unsigned char prior[sizeof memory], table[sizeof events];
    memcpy(prior, memory, sizeof prior);
    memcpy(table, events, sizeof table);
    phase = 0;
    spawn_update(&cpu);
    CHECK(phase == 2 && originals == before + 1 && releases == expected);
    CHECK(cpu.r[0] == 0xdeadbeef);
    CHECK(!memcmp(prior, memory, sizeof prior));
    CHECK(!memcmp(table, events, sizeof table));
}
static void gates(void) {
    reset(); invoke(0, 0); CHECK(!predicates);
    reset(); ST8(SQ + 0x50, 1); invoke(SQ, 0); CHECK(!predicates);
    reset(); ST32(0x1a843f0, 0); invoke(SQ, 0); CHECK(!predicates);
    reset(); ST8(NET + 0x63e, 0); invoke(SQ, 0); CHECK(!predicates);
    reset(); from_hub = false; invoke(SQ, 0); CHECK(predicates == 1);
    reset(); ST8(SQ + 0x1514 + 12 * 4, 3); invoke(SQ, 0);
    reset(); ST8(SQ + 0x1514 + 12 * 4 + 1, 1); invoke(SQ, 0);
    reset(); ST32(SQ + 0x151c + 12 * 4, 1); invoke(SQ, 0);
    reset(); ST32(0x1a85b58, 0); invoke(SQ, 0);
    reset(); ST32(PLAYERS + 0x1c + 4 * 3, 0); invoke(SQ, 0);
    reset(); ST8(HUNTER + 0x1054, 6); invoke(SQ, 0);
    reset(); ST8(0x17a06fc + 12 * 106, 2); invoke(SQ, 0);
    reset(); ST32(0x17a06fc + 12 * 106 + 8, 405); invoke(SQ, 0);
    puts("test-villagehub-demo: session/quest/slot/event/player/area gates: ok");
}
static void once_and_reset(void) {
    reset();
    // Duplicate events and hunters must still release once, before the original.
    memcpy(events, events + 12 * 106, 12);
    ST32(PLAYERS + 0x1c, HUNTER);
    invoke(SQ, 1);
    CHECK(g_demo_released && logs == 1 && predicates == 1);
    invoke(SQ, 1);
    CHECK(logs == 1 && predicates == 1);
    invoke(0, 1);  // a null update is not the between-quests reset
    CHECK(g_demo_released);
    ST8(SQ + 0x50, 0);
    invoke(SQ, 1);
    CHECK(!g_demo_released);
    ST8(SQ + 0x50, 2);
    invoke(SQ, 2);
    CHECK(logs == 2);
    reset();
    g_demo_test = true;
    ST32(0x1a843f0, 0);
    from_hub = false;
    invoke(SQ, 1);
    CHECK(!predicates);  // debug bypass is explicit, never enabled by this fixture's default
    puts("test-villagehub-demo: one-shot/reset, debug gate, register/original ordering: ok");
}
int main(void) {
    gates();
    once_and_reset();
    puts("test-villagehub-demo: ok");
    return 0;
}
