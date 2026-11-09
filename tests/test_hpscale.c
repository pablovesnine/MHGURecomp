// Synthetic public regression of the REAL row hook, frame cache and aux protocol.
// No game bytes, fixed guest mapping, generated code, network, renderer or GPU.
#define _POSIX_C_SOURCE 200809L
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
// Header-only GCC compatibility; not a replacement for either tested algorithm.
// Clang has this builtin. Fail closed if GCC ever executes the unrelated helper.
#if defined(__GNUC__) && !defined(__clang__)
static uint32_t fixture_unsupported_bitreverse32(uint32_t x) {
    (void)x; fputs("unexpected cpu.h bitreverse helper\n", stderr); abort();
}
#define __builtin_bitreverse32 fixture_unsupported_bitreverse32
#endif
#include "config.h"
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

// Independent addresses, deliberately satisfying the production sane() gate.
enum { BASE = 0x08000000, SEN = BASE, TABLE = BASE + 0x3000,
       SQ = BASE + 0x4000, QD = BASE + 0x5000, SELECTOR = BASE + 0x6000,
       PLAYERS = BASE + 0x14000, CONTROL = BASE + 0x15000, MONSTER = BASE + 0x16000,
       INFO = BASE + 0x18000, ROWS = BASE + 0x19000, COPIES = BASE + 0x1a000 };
static _Alignas(16) unsigned char mem[0x1b000], globals[5][8];
static const uint32_t global_addresses[5] = {
    0x1a51fe0, 0x1a8ad90, 0x1a8ae38, 0x1a85b58, 0x1a8ca48
};
static void *guest(uint32_t a) {
    for (unsigned i = 0; i < 5; i++) if (a == global_addresses[i]) return globals[i];
    CHECK(a >= BASE && a - BASE <= sizeof mem - 8);
    return mem + (a - BASE);
}
static unsigned logs;
static void capture(const char *fmt, ...) {
    char buf[1024];
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
#include "../runtime/hle/hpscale.c"

static Cpu cpu;
static HpScale own;
static bool network, hosting, invoking;
static uint64_t clock_ns = 3000000000ull;
static unsigned originals, phase, config_reads, village_reads, allocs, registrations, hooks, sends;
static uint32_t saved[16], original_row, sent_len;
static unsigned char sent[24 + 20 * HP_QUESTS_MAX];
static HostFn registered;

bool ldn_net_up(void) { return network; }
bool ldn_hosting(void) { return hosting; }
void ldn_send_aux(const void *data, uint32_t len) {
    CHECK(network && hosting && len <= sizeof sent);
    memcpy(sent, data, len); sent_len = len; sends++;
}
uint64_t plat_now_ns(void) { return clock_ns; }
void config_live_hp(HpScale *out) {
    CHECK(!invoking || phase == 1);
    *out = own; config_reads++;
}
float config_live_hp_village(void) {
    CHECK(!invoking || phase == 1);
    village_reads++; return own.village;
}
uint32_t hle_alloc(uint32_t n) {
    CHECK(n == 32 * 64 && allocs == 0);
    CHECK(COPIES >= BASE && COPIES - BASE + n <= sizeof mem);
    allocs++; return COPIES;
}
uint32_t hle_register(const char *name, HostFn fn) {
    CHECK(allocs == 1 && registrations == 0 && !strcmp(name, "hpscale:nando_row"));
    registered = fn; registrations++; return 0xf1000000;
}
bool fnhook_set(uint32_t addr, uint32_t detour) {
    CHECK(registrations == 1 && hooks == 0 && addr == 0x2baaac && detour == 0xf1000000);
    hooks++; return true;
}
void fnhook_call_original(Cpu *c, uint32_t addr) {
    CHECK(invoking && c == &cpu && addr == 0x2baaac && phase == 0);
    CHECK(!memcmp(saved, c->r, sizeof saved));
    originals++; phase = 1;
    c->r[0] = original_row;
    c->r[1] = 0xdeadbeef;  // hook must capture column BEFORE the original
    c->r[2] = 0x12345678;
}
static void tick(void) { clock_ns += 3000000000ull; hpscale_tick(); }
static void set_quest(uint32_t q) { ST32(QD + 8, q); }
static void town(unsigned t) { ST8(CONTROL + 0x4c, t); tick(); }
static void reset(void) {
    // Drain the function-local was_up state through its public leave path.
    network = hosting = false; invoking = false;
    tick();
    memset(mem, 0, sizeof mem); memset(globals, 0, sizeof globals);
    memset(&own, 0, sizeof own);
    own.scale[0] = 0.5f; own.scale[1] = 0.75f; own.scale[2] = 1.0f; own.scale[3] = 1.25f;
    own.village = 2.0f;
    ST32(0x1a51fe0, SEN); ST32(SEN + 0x257c, TABLE);
    ST32(TABLE + 0x64, ROWS); ST32(TABLE + 0x68, 3);
    ST32(0x1a8ad90, SQ); ST32(SQ + 0xa4, QD); set_quest(10101);
    ST32(0x1a8ae38, SELECTOR); ST32(SELECTOR + 0xd750, 1);
    ST32(0x1a85b58, PLAYERS); ST32(0x1a8ca48, CONTROL);
    ST32(MONSTER + 0x1428, INFO); ST16(INFO + 0x1b6, 42);
    for (unsigned r = 0; r < 3; r++)
        for (unsigned k = 0; k < 8; k++) STF(ROWS + 32 * r + 4 * k, k == 0 ? 1.25f : k == 3 ? 3.0f : 10.0f + k);
    // All production row memcpy spans have full 32-byte backing, independently checked here.
    CHECK(ROWS - BASE + 3 * 32 <= sizeof mem);
    CHECK(COPIES - BASE + 64 * 32 <= sizeof mem);
    original_row = ROWS;
    g_have_host = false; memset(&g_host, 0, sizeof g_host);
    g_ring_next = 0; g_town = -1; g_watch = 0; g_watch_at = 0;
    g_tick = g_part_tick = g_part_quest = 0; g_part_hunters = 0; g_part_factor = 0;
    config_reads = village_reads = sends = sent_len = logs = 0;
    originals = phase = 0;
}
static float read_float(uint32_t a) { float f; uint32_t u = LD32(a); memcpy(&f, &u, 4); return f; }
static uint32_t invoke(uint32_t column, bool copy, unsigned changed_offset, float expected_value) {
    unsigned char before[sizeof mem], prior_globals[sizeof globals], expected[32];
    memcpy(before, mem, sizeof mem); memcpy(prior_globals, globals, sizeof globals);
    if (copy) {
        CHECK(original_row >= BASE && original_row - BASE + 32 <= sizeof mem);
        memcpy(expected, G2H(original_row), 32);
        memcpy(expected + changed_offset, &expected_value, 4);
    }
    memset(&cpu, 0, sizeof cpu);
    for (unsigned i = 0; i < 16; i++) cpu.r[i] = 0xcafe0000u + i;
    cpu.r[0] = MONSTER; cpu.r[1] = column; memcpy(saved, cpu.r, sizeof saved);
    unsigned calls = originals, next = g_ring_next;
    invoking = true; phase = 0; registered(&cpu); invoking = false;
    CHECK(originals == calls + 1 && phase == 1);
    CHECK(cpu.r[1] == 0xdeadbeef && cpu.r[2] == 0x12345678);
    for (unsigned i = 3; i < 16; i++) CHECK(cpu.r[i] == saved[i]);
    CHECK(!memcmp(prior_globals, globals, sizeof globals));
    if (copy) {
        CHECK(cpu.r[0] == COPIES + 32 * (next % 64));
        CHECK(cpu.r[0] - BASE + 32 <= sizeof mem);
        CHECK(g_ring_next == next + 1 && !memcmp(G2H(cpu.r[0]), expected, 32));
        // Exactly this destination row may change. Source/table/state bytes never change.
        memcpy(before + (cpu.r[0] - BASE), expected, 32);
    } else CHECK(cpu.r[0] == original_row && g_ring_next == next);
    CHECK(!memcmp(before, mem, sizeof mem));
    return cpu.r[0];
}
static void hp(float f) { invoke(0, f != 1.0f, 0, 1.25f * f); }
static void parts(float f) { invoke(2, f != 1.0f, 12, f * 3.0f > 16 ? 16 : f * 3.0f); }

static void gates(void) {
    reset();
    invoke(1, false, 0, 0); invoke(3, false, 0, 0); invoke(UINT32_MAX, false, 0, 0);
    CHECK(config_reads == 0);
    original_row = ROWS - 32; invoke(0, false, 0, 0);
    original_row = ROWS + 96; invoke(0, false, 0, 0);
    original_row = 0; invoke(2, false, 0, 0);
    original_row = ROWS; ST32(TABLE + 0x68, 0); invoke(0, false, 0, 0);
    ST32(TABLE + 0x68, 3); original_row = ROWS + 64; hp(0.5f); parts(0.5f);
    reset(); ST32(0x1a51fe0, 0); invoke(0, false, 0, 0);
    reset(); ST32(SEN + 0x257c, 0x08000001); invoke(0, false, 0, 0);
    reset(); ST32(0x1a8ad90, 0); invoke(0, false, 0, 0);
    reset(); ST32(SQ + 0xa4, 0xf0000000); invoke(0, false, 0, 0);
    reset(); set_quest(0); invoke(0, false, 0, 0); invoke(2, false, 0, 0);
    CHECK(config_reads == 0);
    puts("test-hpscale: original-first, columns, first/last/outside rows, empty table, invalid pointers/quest: ok");
}
static void origins(void) {
    const uint32_t village[] = {1, 9999, 100000, 109999};
    for (unsigned i = 0; i < sizeof village / sizeof *village; i++)
        for (unsigned t = 0; t <= 8; t++) {
            reset(); set_quest(village[i]);
            if (t < 8) town(t); // t=8: no town observed yet
            bool hub = t == 0 || t == 7;
            CHECK(hpscale_village_from_hub(village[i]) == hub);
            // 2.0 Village HubHP * 0.5 one-hunter factor = identity.
            hp(1); parts(1);
            CHECK(config_reads == (hub ? 2u : 0u));
            if (hub) {
                own.village = 3; tick(); hp(1.5f); parts(1.5f);
                ST8(CONTROL + 0x4c, 255); tick();
                CHECK(hpscale_village_from_hub(village[i])); hp(1.5f);
            }
        }
    const uint32_t hub_quests[] = {10000, 99999, 110000, 1010001, 1110001};
    for (unsigned i = 0; i < sizeof hub_quests / sizeof *hub_quests; i++) {
        reset(); town(2); set_quest(hub_quests[i]);
        CHECK(!hpscale_village_from_hub(hub_quests[i]));
        hp(0.5f); parts(0.5f); CHECK(village_reads == 0);
    }
    reset(); CHECK(!hpscale_village_from_hub(0));
    puts("test-hpscale: Village/Prowler ranges, Hub/Pub vs village/unknown origins, remembered town, Hub types: ok");
}
static void own_and_hunters(void) {
    reset();
    const float expected[] = {0.5f, 0.75f, 1, 1.25f};
    for (unsigned n = 1; n <= 4; n++) {
        ST32(SELECTOR + 0xd750, n); hp(expected[n - 1]); parts(expected[n - 1]);
    }
    // Per-quest override replaces default, applies identically to both columns.
    own.quests = 2;
    own.quest[0].quest = 10101; own.quest[1].quest = 20202;
    for (unsigned i = 0; i < 4; i++) {
        own.quest[0].scale[i] = 0.25f * (i + 1); own.quest[1].scale[i] = 2;
    }
    for (unsigned n = 1; n <= 4; n++) {
        ST32(SELECTOR + 0xd750, n); tick(); hp(0.25f * n); parts(0.25f * n);
    }
    set_quest(20202); hp(2); parts(2); // changed quest invalidates part cache within the frame
    set_quest(30303); hp(1.25f); parts(1.25f);
    // Existing behavior: if duplicate overrides exist, the last matching row wins.
    own.quest[1].quest = 10101; set_quest(10101); hp(2); parts(2);
    const uint32_t invalid_counts[] = {0, 5, UINT32_MAX};
    for (unsigned k = 0; k < sizeof invalid_counts / sizeof *invalid_counts; k++)
        for (unsigned n = 0; n <= 4; n++) {
            reset(); ST32(SELECTOR + 0xd750, invalid_counts[k]);
            // Sparse slots; sane/aligned pointers count, not dereferenced player objects.
            const unsigned order[] = {3, 0, 2, 1};
            for (unsigned i = 0; i < n; i++) ST32(PLAYERS + 0x1c + 4 * order[i], MONSTER);
            hp(expected[n ? n - 1 : 0]); parts(expected[n ? n - 1 : 0]);
        }
    reset(); ST32(0x1a8ae38, 0); ST32(0x1a85b58, 0); hp(0.5f); parts(0.5f);
    reset(); ST32(SELECTOR + 0xd750, 0);
    ST32(PLAYERS + 0x1c, 0x08000001); ST32(PLAYERS + 0x20, 0xf0000000); hp(0.5f);
    reset(); town(0); set_quest(101); own.quests = 1; own.quest[0].quest = 101;
    for (unsigned i = 0; i < 4; i++) own.quest[0].scale[i] = 0.4f;
    hp(0.8f); parts(0.8f); // Village HubHP multiplies, rather than replaces, own quest override
    puts("test-hpscale: own/quest overrides, last duplicate wins, 1-4 hunters and sparse/invalid fallback: ok");
}
static void cache_and_ring(void) {
    reset(); parts(0.5f); unsigned reads = config_reads;
    own.scale[0] = 0.25f;
    parts(0.5f); CHECK(config_reads == reads); // explicitly a per-frame parts cache
    hp(0.25f); tick(); parts(0.25f);
    own.scale[1] = 0.8f; ST32(SELECTOR + 0xd750, 2); parts(0.8f);
    own.quests = 1; own.quest[0].quest = 20202;
    for (unsigned k = 0; k < 4; k++) own.quest[0].scale[k] = 1.5f;
    set_quest(20202); parts(1.5f);
    reset(); own.scale[0] = 20;
    hp(20); parts(20); // parts capped to 16, HP deliberately not capped
    own.scale[0] = 16.0f / 3.0f; tick(); parts(16.0f / 3.0f);
    reset();
    hp(0.5f);
    // Ring slots 0..63 then 0 again; each call checks exactly one destination and immutable sources.
    for (unsigned i = 1; i <= 130; i++) {
        if (i & 1) parts(0.5f); else hp(0.5f);
    }
    CHECK(g_ring_next == 131);
    CHECK(read_float(ROWS) == 1.25f && read_float(ROWS + 12) == 3);
    puts("test-hpscale: frame/quest/hunter cache keys, live HP vs cached parts, cap16, ring wrap/source immutability: ok");
}

static uint32_t message(unsigned char *m, const HpScale *s) {
    CHECK(s->quests >= 0 && s->quests <= HP_QUESTS_MAX);
    unsigned nq = (unsigned)s->quests;
    m[0] = 0xe6; m[1] = 0; m[2] = nq; m[3] = nq >> 8;
    memcpy(m + 4, s->scale, 16);
    for (unsigned i = 0; i < nq; i++) {
        memcpy(m + 20 + 20 * i, &s->quest[i].quest, 4);
        memcpy(m + 24 + 20 * i, s->quest[i].scale, 16);
    }
    memcpy(m + 20 + 20 * nq, &s->village, 4);
    return 24 + 20 * nq;
}
static HpScale host_settings(void) {
    HpScale s; memset(&s, 0, sizeof s);
    s.scale[0] = 0.6f; s.scale[1] = 0.9f; s.scale[2] = 1.2f; s.scale[3] = 1.5f;
    s.village = 3; s.quests = 1; s.quest[0].quest = 20202;
    for (unsigned k = 0; k < 4; k++) s.quest[0].scale[k] = 0.2f * (k + 1);
    return s;
}
static void rejected(const unsigned char *m, uint32_t len) {
    HpScale before = g_host; bool had = g_have_host;
    hpscale_aux_received(m, len);
    CHECK(g_have_host == had && !memcmp(&before, &g_host, sizeof before));
}
static void host_and_aux(void) {
    unsigned char m[sizeof sent], valid[sizeof sent];
    reset(); network = true; tick(); // client in a hub; public transition state is up
    HpScale s = host_settings();
    uint32_t len = message(valid, &s);
    hpscale_aux_received(valid, len); CHECK(g_have_host);
    const float expected[] = {0.6f, 0.9f, 1.2f, 1.5f};
    for (unsigned n = 1; n <= 4; n++) {
        ST32(SELECTOR + 0xd750, n); hp(expected[n - 1]); parts(expected[n - 1]);
    }
    set_quest(20202); hp(0.8f); parts(0.8f);
    town(7); set_quest(101); hp(4.5f); parts(4.5f); // host Village x3 times host four-hunter x1.5
    s.quest[0].quest = 101; len = message(valid, &s); hpscale_aux_received(valid, len);
    tick(); hp(2.4f); parts(2.4f); // Village HubHP also multiplies a host's per-quest override
    s.quest[0].quest = 20202;
    set_quest(10101); ST32(SELECTOR + 0xd750, 1); tick(); parts(0.6f);
    s.scale[0] = 0.7f; len = message(valid, &s);
    hpscale_aux_received(valid, len); hp(0.7f); parts(0.6f);
    tick(); parts(0.7f); // accepted settings become visible to parts on the next frame
    network = false; tick(); CHECK(!g_have_host); hp(0.5f); parts(0.5f);
    // Every truncation, wrong magic, count overflow and non-finite/out-of-range float is rejected.
    hpscale_aux_received(NULL, 0); CHECK(!g_have_host);
    for (uint32_t n = 0; n < len; n++) rejected(valid, n);
    memcpy(m, valid, len); m[0] = 0xe5; rejected(m, len);
    memcpy(m, valid, len); m[2] = 1; m[3] = 1; rejected(m, len); // 257 > 256
    const float bad[] = {0, -1, 0.049f, 20.01f, NAN, INFINITY, -INFINITY};
    const unsigned offsets[] = {4, 8, 12, 16, 24, 28, 32, 36, 40};
    for (unsigned i = 0; i < sizeof offsets / sizeof *offsets; i++)
        for (unsigned k = 0; k < sizeof bad / sizeof *bad; k++) {
            memcpy(m, valid, len); memcpy(m + offsets[i], &bad[k], 4); rejected(m, len);
        }
    hosting = true; rejected(valid, len); hosting = false;
    // Smallest valid packet has zero overrides and still requires its trailing Village float.
    network = true; tick(); s.quests = 0;
    uint32_t short_len = message(m, &s); CHECK(short_len == 24);
    for (uint32_t n = 20; n < short_len; n++) rejected(m, n);
    hpscale_aux_received(m, short_len); CHECK(g_have_host && g_host.quests == 0);
    set_quest(20202); tick(); hp(0.7f); parts(0.7f);
    // Inclusive min/max accepted, and full 256-entry packet fits and scales last override.
    s.quests = HP_QUESTS_MAX;
    for (unsigned i = 0; i < HP_QUESTS_MAX; i++) {
        s.quest[i].quest = 30000 + i;
        for (unsigned k = 0; k < 4; k++) s.quest[i].scale[k] = k & 1 ? 20 : 0.05f;
    }
    s.village = 0.05f; s.scale[0] = 0.05f; s.scale[3] = 20;
    len = message(m, &s); CHECK(len == sizeof m);
    hpscale_aux_received(m, len); CHECK(g_have_host && g_host.quests == 256);
    set_quest(30255); tick(); hp(0.05f); parts(0.05f);
    ST32(SELECTOR + 0xd750, 4); hp(20); parts(20);
    // Invalid aux after a valid one must not clear or partially replace host settings.
    m[0] = 0; rejected(m, len);
    network = true; tick(); network = false; tick(); CHECK(!g_have_host);
    puts("test-hpscale: host/quest/Village overrides, next-frame parts, leave/reset, hostile aux bounds/ranges: ok");
}
static void sending(void) {
    reset(); own = host_settings();
    tick(); CHECK(sends == 0);
    network = true; tick(); CHECK(sends == 0);
    hosting = true; tick(); CHECK(sends == 1);
    unsigned char expected[sizeof sent]; uint32_t n = message(expected, &own);
    CHECK(sent_len == n && !memcmp(expected, sent, n));
    hpscale_tick(); CHECK(sends == 1); // same timestamp throttled
    clock_ns += 1999999999ull; hpscale_tick(); CHECK(sends == 1);
    clock_ns++; hpscale_tick(); CHECK(sends == 2);
    hosting = false; tick(); CHECK(sends == 2);
    network = false; tick();
    puts("test-hpscale: host-only exact aux layout, 2s throttle, no offline/client sends: ok");
}
int main(void) {
    int rc = unsetenv("MHGU_LOG_HPSCALE"); CHECK(rc == 0);
    hpscale_init(); CHECK(g_ring == COPIES && hooks == 1 && registered == nando_row);
    gates(); origins(); own_and_hunters(); cache_and_ring(); host_and_aux(); sending();
    puts("test-hpscale: ok");
    return 0;
}
