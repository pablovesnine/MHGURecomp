// Synthetic host regression of the ACTUAL production translation unit.
// No sockets, threads, fixed mappings, ROM, emulator, or game-derived data.
// --red-active-drain demonstrates the documented pending-report activation gap.
#define _POSIX_C_SOURCE 200809L
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../runtime/hle.h"

static unsigned checks, groups;
#define CHECK(x) do { ++checks; if (!(x)) { \
    fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #x); exit(1); \
} } while (0)

// Include the real runtime headers first, then replace only guest translation.
// The integer subtraction happens BEFORE adding an offset to either byte array.
enum { HEAP = 0x08000000u, LOW = 0x01a85000u };
static uint8_t heap[0x40000], low[0x8000];
static void *memory(uint32_t a, size_t n) {
    if (a >= HEAP && (uint64_t)(a - HEAP) + n <= sizeof heap)
        return heap + (a - HEAP);
    if (a >= LOW && (uint64_t)(a - LOW) + n <= sizeof low)
        return low + (a - LOW);
    fprintf(stderr, "unmapped synthetic address %08x size %zu\n", a, n);
    exit(2);
}
static uint8_t rd8(uint32_t a) { uint8_t x; memcpy(&x, memory(a, 1), 1); return x; }
static uint16_t rd16(uint32_t a) { uint16_t x; memcpy(&x, memory(a, 2), 2); return x; }
static uint32_t rd32(uint32_t a) { uint32_t x; memcpy(&x, memory(a, 4), 4); return x; }
static void wr8(uint32_t a, uint8_t x) { memcpy(memory(a, 1), &x, 1); }
static void wr16(uint32_t a, uint16_t x) { memcpy(memory(a, 2), &x, 2); }
static void wr32(uint32_t a, uint32_t x) { memcpy(memory(a, 4), &x, 4); }
#undef G2H
#undef LD8
#undef LD16
#undef LD32
#undef ST8
#undef ST16
#undef ST32
#define G2H(a) memory((uint32_t)(a), 1)
#define LD8(a) rd8((uint32_t)(a))
#define LD16(a) rd16((uint32_t)(a))
#define LD32(a) rd32((uint32_t)(a))
#define ST8(a,x) wr8((uint32_t)(a), (uint8_t)(x))
#define ST16(a,x) wr16((uint32_t)(a), (uint16_t)(x))
#define ST32(a,x) wr32((uint32_t)(a), (uint32_t)(x))

#include "../runtime/net/hitsync.c"

_Static_assert(sizeof(Hello) == 5, "actual native Hello ABI");
_Static_assert(sizeof(Report) == 136, "actual native Report ABI");
_Static_assert(offsetof(Report, parts) == 8, "parts offset");
_Static_assert(offsetof(Report, more) == 84, "more offset");
_Static_assert(offsetof(Report, flags) == 92, "flags offset");
_Static_assert(offsetof(Report, pos) == 120, "position offset");

enum { EN = HEAP, IN = HEAP + 0x10000, SP = HEAP + 0x20000,
       MEMBER = HEAP + 0x21000, AT = HEAP + 0x22000,
       SHELL = HEAP + 0x23000, STACK = HEAP + 0x30000,
       PLAYER0 = HEAP + 0x24000, PLAYER1 = HEAP + 0x25000 };
static uint64_t clock_ns = 10000000000ull;
static bool enabled, net_up, crossplay;
static Cpu cpu;
static uint8_t sent[512][256];
static uint32_t lengths[512];
static unsigned nsent, orig_hit, orig_apply, orig_aggro, replay_aggro;
static int sum_aggro, last_aggro_flag, last_aggro_slot;
static int mutation; // 0 none, 1 full, 2 EN_REACT only, 3 aggro only, 4 multiple aggro
static int observed_damage, observed_ko, observed_more;
static uint32_t observed_hp;
static HostFn hooks[3], registered[8];
static unsigned nregistered, nset;
static uint32_t hook_addresses[8];

int config_live_lag_compensation(void) { return enabled; }
bool ldn_net_up(void) { return net_up; }
bool ldn_crossplay(void) { return crossplay; }
uint64_t plat_now_ns(void) { return clock_ns; }
void ldn_send_aux(const void *data, uint32_t len) {
    CHECK(nsent < 512 && len <= sizeof sent[0]);
    lengths[nsent] = len;
    memcpy(sent[nsent++], data, len);
}
uint32_t hle_register(const char *name, HostFn fn) {
    CHECK(name && nregistered < 8);
    registered[nregistered++] = fn;
    return nregistered;
}
bool fnhook_set(uint32_t addr, uint32_t detour) {
    CHECK(nset < 8 && detour && detour <= nregistered);
    hook_addresses[nset++] = addr;
    if (addr == FN_HIT) hooks[0] = registered[detour - 1];
    else if (addr == FN_AGGRO) hooks[1] = registered[detour - 1];
    else if (addr == FN_EN_APPLY) hooks[2] = registered[detour - 1];
    else CHECK(false);
    return true;
}

static void add16(uint32_t addr, int n) { ST16(addr, (uint16_t)((int16_t)LD16(addr) + n)); }
static void synthetic_aggro(Cpu *c, int kind, int amount, int flag) {
    Cpu ac = *c;
    ac.r[0] = EN; ac.r[1] = (uint32_t)kind; ac.r[2] = 1; ac.r[3] = (uint32_t)amount;
    ST32(ac.r[13], flag);
    hooks[1](&ac);
}
void fnhook_call_original(Cpu *c, uint32_t addr) {
    if (addr == FN_AGGRO) { ++orig_aggro; return; }
    if (addr == FN_EN_APPLY) {
        ++orig_apply;
        observed_damage = (int16_t)LD16(IN + P_PARTS);
        observed_ko = (int16_t)LD16(IN + 0x4d2);
        observed_more = (int16_t)LD16(IN + P_MORE);
        observed_hp = LD32(IN + INFO_HP);
        return; // Observation boundary, NOT an implementation of the game's damage logic.
    }
    CHECK(addr == FN_HIT);
    ++orig_hit;
    if (mutation == 1) {
        for (int i = 0; i < N_PARTS; ++i) add16(IN + P_PARTS + 2u * (unsigned)i, i + 1);
        for (int i = 0; i < N_MORE; ++i) add16(IN + P_MORE + 2u * (unsigned)i, i + 5);
        ST32(IN + P_FLAGS, LD32(IN + P_FLAGS) | 0x120u);
        ST16(IN + I_FLAGS, LD16(IN + I_FLAGS) | 0x42u);
        ST8(IN + I_HIT, 1); ST8(IN + P_KIND, 7); ST8(IN + P_KIND + 1, 9);
        ST16(IN + P_DIR, (uint16_t)-123); ST8(IN + P_SLOT, 1); ST8(IN + P_MOUNT, 1);
        ST8(IN + P_F6, LD8(IN + P_F6) | 4); ST8(IN + P_F7, LD8(IN + P_F7) | 8);
        float pos[4] = {1.25f, -2.5f, 3.75f, 1.0f};
        memcpy(memory(IN + P_POS, sizeof pos), pos, sizeof pos);
        ST32(EN + EN_REACT, 0x3fc00000u);
        ST8(EN + EN_REACT + 4, 6); ST8(EN + EN_REACT + 5, 7);
        ST8(EN + EN_REACT + 6, 8); ST8(EN + EN_REACT + 7, 9);
        ST8(IN + 0x448, LD8(IN + 0x448) + 1); // Deliberately untracked field.
        synthetic_aggro(c, 0, 23, 17);
    } else if (mutation == 2) {
        ST32(EN + EN_REACT, 0x40000000u);
    } else if (mutation == 3) {
        synthetic_aggro(c, 0, 23, 17);
    } else if (mutation == 4) {
        synthetic_aggro(c, 0, 12, 6);
        synthetic_aggro(c, 0, 13, 7);
        synthetic_aggro(c, 1, 99, 8); // Not hunter aggro: original runs, not in report sum.
    }
}
// Match dispatch.c's guest_call LR save/restore contract; no game execution.
void guest_call(Cpu *c, uint32_t addr) {
    uint32_t lr = c->r[14];
    c->r[14] = 0; c->pc = addr;
    rt_dispatch(c);
    c->r[14] = lr;
}
void rt_dispatch(Cpu *c) {
    if (c->pc == FN_RANK) {
        c->r[0] = c->r[1]; // Synthetic monotonic rank table.
        c->v.f[0] = -444;
    } else {
        CHECK(c->pc == FN_AGGRO && c->r[0] == EN && c->r[1] == 0);
        ++replay_aggro;
        sum_aggro += (int32_t)c->r[3];
        last_aggro_flag = (int32_t)LD32(c->r[13]);
        last_aggro_slot = (int)c->r[2];
        c->r[0] = 0xdeadbeef; c->v.f[0] = -333;
    }
}

static void begin(const char *name) { ++groups; printf("ok group %u: %s\n", groups, name); }
static void initialize_hooks(void) {
    nregistered = nset = 0;
    memset(hooks, 0, sizeof hooks);
    hitsync_init();
    CHECK(nset == 3 && hooks[0] == hit && hooks[1] == aggro && hooks[2] == en_apply);
}
static void reset_fixture(void) {
    // Only this helper resets TU globals, as test isolation; runtime has NO such reset API.
    net_up = false; clock_ns += 10000000000ull; hitsync_tick();
    memset(heap, 0, sizeof heap); memset(low, 0, sizeof low);
    memset((void *)g_hello, 0, sizeof g_hello); memset((void *)g_caps, 0, sizeof g_caps);
    memset(g_q, 0, sizeof g_q); memset(g_st, 0, sizeof g_st);
    g_nq = 0; g_seq = 0; t_aggro = t_aggro_sum = t_aggro_flag = 0; g_log = false;
    enabled = net_up = true; crossplay = false; nsent = 0;
    orig_hit = orig_apply = orig_aggro = replay_aggro = 0;
    sum_aggro = last_aggro_flag = last_aggro_slot = 0; mutation = 1;
    memset(&cpu, 0, sizeof cpu); cpu.r[13] = STACK; cpu.v.f[0] = 12.5f;
    ST32(G_SPLAYER, SP); ST32(G_MEMBER, MEMBER); ST32(MEMBER + 0x30, 1);
    ST32(SP + 0x1c, PLAYER0); ST32(SP + 0x20, PLAYER1);
    ST32(SP + 0x24, PLAYER1 + 0x100); ST32(SP + 0x28, PLAYER1 + 0x200);
    ST32(EN + EN_INFO, IN); ST16(IN + INFO_ID, 42); ST32(IN + INFO_HP, 12345);
    ST8(IN + P_MOUNT, 0xff);
    ST8(AT + AT_KIND, KIND_HUNTER); ST32(AT + AT_OWNER, PLAYER1);
    ST32(AT + AT_SHOOTER, PLAYER1); ST32(SHELL, SHOT_VT[0]);
}
static void run_hit(void) { cpu.r[1] = AT; cpu.r[2] = EN; hooks[0](&cpu); }
static void run_apply(void) { cpu.r[0] = EN; hooks[2](&cpu); }
static void owner(void) { ST32(MEMBER + 0x30, 0); ST8(EN + EN_RUNS, 1); }
static void hello(unsigned slot, bool on, bool shots, bool old) {
    Hello h = {MAGIC, M_HELLO, (uint8_t)slot, on, shots ? HELLO_SHOTS : 0};
    hitsync_aux_received(&h, old ? 4 : sizeof h);
}
static Report basic_report(void) {
    Report r; memset(&r, 0, sizeof r);
    r.magic = MAGIC; r.kind = M_REPORT; r.slot = 1; r.id = 42; r.mount = 0xff;
    r.parts[0] = 7; return r;
}
static void receive(Report r) { hitsync_aux_received(&r, sizeof r); }
static void check_queue(Report r, bool accepted) {
    g_nq = 0; receive(r); CHECK(g_nq == (accepted ? 1 : 0));
}

static void test_tick_and_hello(void) {
    reset_fixture(); enabled = false; hitsync_tick(); CHECK(nsent == 0);
    enabled = true; hitsync_tick();
    CHECK(nsent == 1 && lengths[0] == 5);
    const uint8_t expected[] = {MAGIC, M_HELLO, 1, 1, HELLO_SHOTS};
    CHECK(memcmp(sent[0], expected, 5) == 0);
    hitsync_tick(); CHECK(nsent == 1);
    clock_ns += HELLO_NS - 1; hitsync_tick(); CHECK(nsent == 1);
    ++clock_ns; hitsync_tick(); CHECK(nsent == 2);
    enabled = false; hitsync_tick(); CHECK(nsent == 3 && sent[2][3] == 0);
    clock_ns += HELLO_NS * 2; hitsync_tick(); CHECK(nsent == 3);
    enabled = true; crossplay = true; hitsync_tick(); CHECK(nsent == 3 && !active());
    crossplay = false; hitsync_tick(); CHECK(nsent == 4);
    crossplay = true; hitsync_tick(); CHECK(nsent == 5 && sent[4][3] == 0);
    crossplay = false; net_up = false; hitsync_tick(); CHECK(nsent == 5);
    net_up = true; hitsync_tick(); CHECK(nsent == 6);
    ST32(MEMBER + 0x30, 4); hitsync_tick(); CHECK(nsent == 6);
    ST32(G_MEMBER, 0); hitsync_tick(); CHECK(nsent == 6);

    reset_fixture();
    uint8_t bytes[8] = {MAGIC, M_HELLO, 1, 1, HELLO_SHOTS, 99, 98, 97};
    for (unsigned len = 0; len < 4; ++len) {
        hitsync_aux_received(bytes, len); CHECK(g_hello[1] == 0);
    }
    hitsync_aux_received(bytes, 4); CHECK(reports(1, clock_ns) && !reports_shots(1, clock_ns));
    hitsync_aux_received(bytes, 8); CHECK(reports_shots(1, clock_ns));
    CHECK(reports(1, clock_ns + HELLO_STALE - 1));
    CHECK(!reports(1, clock_ns + HELLO_STALE));
    bytes[2] = 4; hitsync_aux_received(bytes, 5); CHECK(g_hello[0] == 0);
    hello(1, false, true, false); CHECK(!reports(1, clock_ns));
    bytes[2] = 1; bytes[0] ^= 1; hitsync_aux_received(bytes, 5); CHECK(!g_hello[1]);
    bytes[0] = MAGIC; bytes[1] = 99; hitsync_aux_received(bytes, 8); CHECK(!g_hello[1]);
    hello(3, true, true, false); CHECK(reports_shots(3, clock_ns));
    hello(0, true, false, false); CHECK(reports(0, clock_ns));
    begin("Hello wire lengths, capabilities, enable/disable, interval, crossplay and expiry");
}

static void test_negotiation(void) {
    for (int local = 0; local < 2; ++local)
    for (int remote = 0; remote < 2; ++remote)
    for (int old = 0; old < 2; ++old)
    for (int shot = 0; shot < 2; ++shot) {
        reset_fixture(); owner(); enabled = local;
        hello(1, remote, true, old);
        if (shot) { ST8(AT + AT_VIA, 1); ST32(AT + AT_OWNER, SHELL); }
        run_hit();
        bool suppress = local && remote && (!shot || !old);
        CHECK(orig_hit == 1 && nsent == 0);
        CHECK(LD16(IN + P_PARTS) == (suppress ? 0 : 1));
        CHECK(orig_aggro == (suppress ? 0u : 1u));
        CHECK(LD8(IN + 0x448) == 1); // Original attack-number side effect is NOT rolled back.
    }
    reset_fixture(); owner(); run_hit(); CHECK(LD16(IN + P_PARTS) == 1); // No Hello/old peer.
    reset_fixture(); owner(); hello(1, true, true, false); clock_ns += HELLO_STALE;
    run_hit(); CHECK(LD16(IN + P_PARTS) == 1);
    for (int gate = 0; gate < 3; ++gate) {
        reset_fixture();
        if (gate == 0) enabled = false;
        if (gate == 1) net_up = false;
        if (gate == 2) crossplay = true;
        run_hit(); CHECK(nsent == 0 && orig_hit == 1 && LD16(IN + P_PARTS) == 1);
    }
    // Reporter does NOT wait for the owner's Hello. Disabled/old owners keep native hits.
    reset_fixture(); run_hit(); CHECK(nsent == 1);
    Report r; memcpy(&r, sent[0], sizeof r);
    reset_fixture(); owner(); enabled = false; hello(1, true, true, false);
    receive(r); run_apply(); CHECK(observed_damage == 0 && g_nq == 0);
    reset_fixture(); ST8(EN + EN_RUNS, 1); run_hit(); CHECK(nsent == 0); // Local owner.
    reset_fixture(); ST32(MEMBER + 0x30, 0); run_hit(); CHECK(nsent == 0); // Another client's copy.
    begin("both-end enable matrix, old melee-only Hello, absent peers and side selection");
}

static void test_attack_filters(void) {
    for (unsigned vt = 0; vt < sizeof SHOT_VT / sizeof SHOT_VT[0]; ++vt) {
        reset_fixture(); ST8(AT + AT_VIA, 1); ST32(AT + AT_OWNER, SHELL); ST32(SHELL, SHOT_VT[vt]);
        run_hit(); CHECK(nsent == 1 && sent[0][1] == M_SHOT);
    }
    for (int filter = 0; filter < 16; ++filter) {
        reset_fixture();
        switch (filter) {
        case 0: ST8(AT + AT_KIND, 2); break;
        case 1: ST16(IN + INFO_ID, 10000); break;
        case 2: ST32(EN + EN_INFO, 0); break;
        case 3: ST32(AT + AT_OWNER, PLAYER1 + 0x300); break;
        case 4: ST32(MEMBER + 0x30, 4); break;
        case 5: ST8(AT + AT_TYPE, 8); break;
        case 6: ST8(AT + AT_TYPE, 9); break;
        case 7: ST8(AT + AT_TYPE, 0x45); break;
        case 8: ST8(AT + AT_VIA, 1); ST8(AT + AT_NO_PLAYER, 1); break;
        case 9: ST8(AT + AT_VIA, 1); ST32(AT + AT_OWNER, 0); break;
        case 10: ST8(AT + AT_VIA, 1); ST32(AT + AT_OWNER, SHELL); ST32(SHELL, 0x12345678); break;
        case 11: ST8(AT + AT_VIA, 1); ST32(AT + AT_OWNER, SHELL); ST32(AT + AT_SHOOTER, 0); break;
        case 12: ST32(G_SPLAYER, 0); break;
        case 13: ST32(AT + AT_OWNER, PLAYER1 + 1); break;
        case 14: ST32(G_MEMBER, 0xf0000000); break;
        case 15: ST32(EN + EN_INFO, IN + 1); break;
        }
        run_hit(); CHECK(nsent == 0 && orig_hit == 1);
    }
    reset_fixture(); cpu.r[1] = AT; cpu.r[2] = 0; mutation = 0;
    hooks[0](&cpu); CHECK(nsent == 0 && orig_hit == 1);
    CHECK(!sane(0x07fffffc) && sane(HEAP) && !sane(HEAP + 1) && !sane(0xf0000000));
    begin("supported shot classes, unsupported weapons, monster/player/address filters");
}

static void test_encoding_and_roundtrip(void) {
    reset_fixture(); hitsync_tick(); CHECK(nsent == 1);
    uint8_t advert[5]; memcpy(advert, sent[0], 5);
    ST32(IN + P_FLAGS, 0x20); ST16(IN + I_FLAGS, 2);
    ST8(IN + P_F6, 1); ST8(IN + P_F7, 2);
    run_hit(); CHECK(nsent == 2 && lengths[1] == sizeof(Report));
    Report r; memcpy(&r, sent[1], sizeof r);
    CHECK(r.magic == MAGIC && r.kind == M_REPORT && r.slot == 1 && r.id == 42 && r.seq == 1);
    CHECK(r.has_kind == 3 && r.flags == 0x100 && r.info_flags == 0x40 && r.mount == 1);
    CHECK(r.f6 == 4 && r.f7 == 8 && r.react_kind == 7 && r.react_b == 9 && r.dir == -123 && r.att == 1);
    CHECK(r.react_f == 0x3fc00000u && r.react_b0 == 6 && r.react_b1 == 7);
    CHECK(r.aggro == 23 && r.aggro_flag == 17 && r.pos[0] == 1.25f && r.pos[1] == -2.5f);
    for (int i = 0; i < N_PARTS; ++i) CHECK(r.parts[i] == i + 1);
    for (int i = 0; i < N_MORE; ++i) CHECK(r.more[i] == i + 5);
    CHECK(damage_of(r.parts) == 36 && r.parts[(0x4d2 - P_PARTS) / 2] == 38);
    // Independent raw byte expectations: no alternate serializer is substituted.
    CHECK(sent[1][0] == 0xe7 && sent[1][1] == 1 && sent[1][2] == 1 && sent[1][3] == 3);
    CHECK(sent[1][4] == 42 && sent[1][5] == 0 && sent[1][6] == 1 && sent[1][7] == 0);
    for (int i = 0; i < N_PARTS; ++i) CHECK(sent[1][8 + i * 2] == i + 1 && sent[1][9 + i * 2] == 0);

    reset_fixture(); owner(); hitsync_aux_received(advert, 5);
    Snap before, after; snap_take(&before, EN, IN);
    run_hit(); snap_take(&after, EN, IN);
    CHECK(memcmp(&before.p, &after.p, P_SIZE) == 0);
    CHECK(memcmp(before.react, after.react, EN_REACT_SIZE) == 0);
    CHECK(before.hit == after.hit && before.info_flags == after.info_flags);
    CHECK(orig_aggro == 0 && LD8(IN + 0x448) == 1);
    receive(r);
    for (unsigned i = 0; i < 16; ++i) cpu.r[i] = i * 111 + 7;
    cpu.r[13] = STACK; cpu.r[0] = EN; cpu.v.f[0] = 12.5f;
    uint32_t regs[16]; memcpy(regs, cpu.r, sizeof regs);
    run_apply();
    CHECK(memcmp(regs, cpu.r, sizeof regs) == 0 && cpu.v.f[0] == 12.5f);
    CHECK(orig_apply == 1 && observed_damage == 1 && observed_ko == 38 && observed_more == 5);
    CHECK(observed_hp == 12345 && LD32(IN + INFO_HP) == 12345);
    CHECK(LD8(IN + I_HIT) == 1 && LD32(IN + P_FLAGS) == 0x100 && LD16(IN + I_FLAGS) == 0x40);
    CHECK(LD8(IN + P_KIND) == 7 && (int16_t)LD16(IN + P_DIR) == -123 && LD8(IN + P_SLOT) == 1);
    CHECK(LD8(IN + P_MOUNT) == 1 && LD8(IN + P_F6) == 4 && LD8(IN + P_F7) == 8);
    CHECK(LD32(EN + EN_REACT) == 0x3fc00000 && LD8(EN + EN_REACT + 4) == 6);
    CHECK(LD8(EN + EN_REACT + 6) == 0 && LD8(EN + EN_REACT + 7) == 0); // Only six of eight encoded.
    CHECK(replay_aggro == 1 && sum_aggro == 23 && last_aggro_flag == 17 && last_aggro_slot == 1);
    CHECK(g_nq == 0 && g_st[1].sent == 0 && g_st[1].copy == 1 && g_st[1].applied == 1);

    // End-to-end shot uses the distinct message kind and requires recipient capability.
    reset_fixture(); ST8(AT + AT_VIA, 1); ST32(AT + AT_OWNER, SHELL); run_hit();
    memcpy(&r, sent[0], sizeof r); CHECK(r.kind == M_SHOT);
    reset_fixture(); owner(); hello(1, true, true, false); receive(r); run_apply(); CHECK(observed_damage == 1);
    reset_fixture(); owner(); hello(1, true, true, true); receive(r); run_apply(); CHECK(observed_damage == 0 && g_nq == 0);

    reset_fixture(); mutation = 0; run_hit(); CHECK(nsent == 0 && g_seq == 1);
    mutation = 2; run_hit(); CHECK(nsent == 0 && g_seq == 2); // EN_REACT-only is not sufficient to send.
    mutation = 3; run_hit(); CHECK(nsent == 1); memcpy(&r, sent[0], sizeof r);
    CHECK(r.aggro == 23 && r.parts[0] == 0 && r.has_kind == 0);
    reset_fixture(); mutation = 4; run_hit(); memcpy(&r, sent[0], sizeof r);
    CHECK(r.aggro == 25 && r.aggro_flag == 7 && orig_aggro == 3);
    reset_fixture(); mutation = 0; t_aggro = 2; synthetic_aggro(&cpu, 1, 99, 1);
    CHECK(orig_aggro == 1); t_aggro = 0;
    reset_fixture(); g_seq = UINT16_MAX; run_hit(); memcpy(&r, sent[0], sizeof r); CHECK(r.seq == 0);
    begin("real hit->wire->receive->owner apply; field deltas, KO, aggro, snapshot and ABI");
}

static void test_delta_edges(void) {
    reset_fixture();
    for (int i = 0; i < N_PARTS; ++i) ST16(IN + P_PARTS + 2u * (unsigned)i, 100 + i);
    for (int i = 0; i < N_MORE; ++i) ST16(IN + P_MORE + 2u * (unsigned)i, 200 + i);
    ST32(IN + P_FLAGS, 0x30); ST16(IN + I_FLAGS, 0x12);
    ST8(IN + P_F6, 3); ST8(IN + P_F7, 3);
    Snap s; snap_take(&s, EN, IN);
    for (int i = 0; i < N_PARTS; ++i) add16(IN + P_PARTS + 2u * (unsigned)i, -20);
    for (int i = 0; i < N_MORE; ++i) add16(IN + P_MORE + 2u * (unsigned)i, -30);
    ST32(IN + P_FLAGS, 0x20); ST16(IN + I_FLAGS, 2);
    ST8(IN + P_F6, 1); ST8(IN + P_F7, 1);
    report_send(&s, EN, IN, 1, false);
    CHECK(nsent == 1);
    Report r; memcpy(&r, sent[0], sizeof r);
    for (int i = 0; i < N_PARTS; ++i) CHECK(r.parts[i] == -20);
    for (int i = 0; i < N_MORE; ++i) CHECK(r.more[i] == -30);
    CHECK(r.flags == 0 && r.info_flags == 0 && r.f6 == 0 && r.f7 == 0 && r.mount == 0xff);
    CHECK(r.has_kind == 0);
    // Signed field wrap is encoded modulo 16 bits, not clamped.
    reset_fixture(); ST16(IN + P_PARTS, 32760); snap_take(&s, EN, IN);
    ST16(IN + P_PARTS, (uint16_t)-32760); report_send(&s, EN, IN, 1, false);
    memcpy(&r, sent[0], sizeof r); CHECK(r.parts[0] == 16);
    reset_fixture(); snap_take(&s, EN, IN);
    ST16(IN + P_PARTS, MAX_ADD + 1); report_send(&s, EN, IN, 1, false);
    memcpy(&r, sent[0], sizeof r); CHECK(r.parts[0] == MAX_ADD + 1);
    check_queue(r, false); // Sender does not enforce receiver's per-field cap.
    reset_fixture(); snap_take(&s, EN, IN); ST8(IN + I_HIT, 1);
    report_send(&s, EN, IN, 1, false); CHECK(nsent == 0); // Hit byte alone not encoded.
    ST8(IN + P_MOUNT, 2); report_send(&s, EN, IN, 1, false);
    memcpy(&r, sent[0], sizeof r); CHECK(nsent == 1 && r.mount == 2 && r.has_kind == 0);
    reset_fixture(); owner(); hello(1, true, true, false);
    ST32(IN + P_FLAGS, 0x40); ST16(IN + I_FLAGS, 0x80); ST8(IN + P_F6, 0x10); ST8(IN + P_F7, 0x20);
    r = basic_report(); r.flags = 2; r.info_flags = 4; r.f6 = 1; r.f7 = 8;
    receive(r); run_apply();
    CHECK(LD32(IN + P_FLAGS) == 0x42 && LD16(IN + I_FLAGS) == 0x84);
    CHECK(LD8(IN + P_F6) == 0x11 && LD8(IN + P_F7) == 0x28);
    begin("nonzero snapshots, negative/wrapped deltas, additive-only flags and asymmetric cap");
}

static void test_decoder(void) {
    reset_fixture(); Report r = basic_report();
    for (unsigned len = 0; len < sizeof r; ++len) {
        hitsync_aux_received(&r, len); CHECK(g_nq == 0);
    }
    uint8_t extra[sizeof r + 9]; memset(extra, 0xa5, sizeof extra); memcpy(extra, &r, sizeof r);
    hitsync_aux_received(extra, sizeof extra); CHECK(g_nq == 1);
    for (int field = 0; field < N_PARTS + N_MORE; ++field) {
        for (int sign = -1; sign <= 1; sign += 2) {
            r = basic_report();
            if (field < N_PARTS) r.parts[field] = (int16_t)(sign * MAX_ADD);
            else r.more[field - N_PARTS] = (int16_t)(sign * MAX_ADD);
            check_queue(r, true);
            if (field < N_PARTS) r.parts[field] = (int16_t)(sign * (MAX_ADD + 1));
            else r.more[field - N_PARTS] = (int16_t)(sign * (MAX_ADD + 1));
            check_queue(r, false);
        }
    }
    int ag[] = {-1, 0, MAX_ADD, MAX_ADD + 1};
    for (unsigned i = 0; i < 4; ++i) { r = basic_report(); r.aggro = ag[i]; check_queue(r, i == 1 || i == 2); }
    r = basic_report(); r.slot = 3; check_queue(r, true); r.slot = 4; check_queue(r, false);
    r = basic_report(); r.id = 9999; check_queue(r, true); r.id = 10000; check_queue(r, false);
    r.id = 0; check_queue(r, true);
    r = basic_report(); r.magic ^= 1; check_queue(r, false);
    r = basic_report(); r.kind = 99; check_queue(r, false);
    r.kind = M_SHOT; check_queue(r, true);
    // No validation of reaction ranks, attacker/mount, coordinates, flags, seq, or aggro flag.
    r = basic_report(); r.has_kind = 0xff; r.react_kind = 255; r.att = 255; r.mount = 254;
    r.flags = UINT32_MAX; r.info_flags = UINT16_MAX; r.aggro_flag = INT32_MIN;
    uint32_t nan = 0x7fc00000; memcpy(&r.pos[0], &nan, 4); check_queue(r, true);
    reset_fixture(); owner(); hello(1, true, true, false);
    r = basic_report(); r.parts[0] = -MAX_ADD; receive(r); run_apply(); CHECK(observed_damage == -MAX_ADD);
    reset_fixture(); owner(); hello(1, true, true, false);
    ST16(IN + P_PARTS, 32760); r = basic_report(); r.parts[0] = 10; receive(r); run_apply();
    CHECK(observed_damage == -32766); // Stored u16 wrap, not saturation.
    begin("decoder lengths, extensions, all 42 signed bounds, aggro, IDs and unconstrained fields");
}

static void test_queues_and_order(void) {
    reset_fixture(); owner(); hello(1, true, true, false);
    Report r = basic_report(); r.seq = 65535; receive(r); receive(r); run_apply();
    CHECK(observed_damage == 14 && g_st[1].applied == 2); // seq is diagnostic, not dedup/replay protection.
    reset_fixture(); owner(); hello(1, true, true, false);
    r = basic_report(); r.has_kind = 1; r.react_kind = 5; r.pos[0] = 2; r.seq = 2;
    receive(r); r.seq = 1; r.pos[0] = 1; receive(r); run_apply();
    float f; memcpy(&f, memory(IN + P_POS, 4), 4);
    CHECK(f == 1 && observed_damage == 14); // Arrival order, equal rank last wins, NOT seq order.
    reset_fixture(); owner(); hello(1, true, true, false);
    ST8(IN + P_KIND, 9); ST8(IN + P_MOUNT, 2);
    r = basic_report(); r.has_kind = 3; r.react_kind = 8; r.mount = 1; r.react_f = 0x40000000;
    receive(r); run_apply(); CHECK(LD8(IN + P_KIND) == 9 && LD8(IN + P_MOUNT) == 2);
    CHECK(LD32(EN + EN_REACT) == 0x40000000); // EN_REACT independent of reaction rank.
    reset_fixture(); owner(); hello(1, true, true, false);
    r = basic_report(); g_seq = 10;
    for (int i = 0; i < QUEUE; ++i) { r.seq = (uint16_t)i; receive(r); }
    r.parts[0] = 99; receive(r); CHECK(g_nq == QUEUE && g_q[QUEUE - 1].r.parts[0] == 7);
    run_apply(); CHECK(observed_damage == QUEUE * 7 && g_nq == 0);
    for (int extra = 0; extra < 2; ++extra) {
        reset_fixture(); owner(); hello(1, true, true, false); r = basic_report(); receive(r);
        clock_ns += QUEUE_STALE + (unsigned)extra;
        run_apply(); CHECK(observed_damage == (extra ? 0 : 7) && g_nq == 0);
    }
    reset_fixture(); owner(); hello(1, true, true, false); r = basic_report(); receive(r);
    clock_ns += HELLO_STALE; receive(r); run_apply(); CHECK(observed_damage == 0 && g_nq == 0);
    for (int gate = 0; gate < 3; ++gate) {
        reset_fixture(); owner(); hello(1, true, true, false); r = basic_report(); receive(r);
        if (gate == 0) ST8(EN + EN_RUNS, 0);
        if (gate == 1) enabled = false;
        if (gate == 2) hello(1, false, false, false);
        run_apply(); CHECK(observed_damage == 0 && g_nq == 0); // Consumed, not retried.
    }
    reset_fixture(); owner(); hello(1, true, true, false); r = basic_report(); r.id = 43; receive(r);
    run_apply(); CHECK(g_nq == 1 && observed_damage == 0);
    ST16(IN + INFO_ID, 43); run_apply(); CHECK(g_nq == 0 && observed_damage == 7);
    reset_fixture(); owner(); r = basic_report(); receive(r);
    CHECK(g_nq == 1); hello(1, true, true, false); run_apply();
    CHECK(observed_damage == 7); // Eligibility checked at drain, not arrival.
    reset_fixture(); owner(); r = basic_report(); r.id = 43; receive(r); clock_ns += QUEUE_STALE + 1;
    run_apply(); CHECK(g_nq == 0);
    reset_fixture(); owner(); receive(basic_report()); ST16(IN + INFO_ID, ZAKO_FIRST);
    clock_ns += QUEUE_STALE + 1; run_apply(); CHECK(g_nq == 1); // No large-monster update => no pruning.
    begin("duplicates, reversed seq, rank tie/priority, overflow, stale boundaries and consume rules");
}

static void test_lifecycle_and_trust(bool red) {
    reset_fixture(); owner();
    // Payload slot is trusted; API does not carry transport sender identity.
    hello(1, true, true, false); receive(basic_report()); net_up = false;
    g_seq = 77; g_st[1].copy = 9;
    uint64_t seen = g_hello[1]; uint16_t seq = g_seq;
    hitsync_tick(); hitsync_init();
    CHECK(g_nq == 1 && g_hello[1] == seen && g_caps[1] == HELLO_SHOTS && g_seq == seq && g_st[1].copy == 9);
    run_apply();
    if (red) CHECK(observed_damage == 0); // Deliberate RED: active() is false, but pending report applies.
    else CHECK(observed_damage == 7 && !active());
    reset_fixture(); owner(); hello(1, true, true, false); receive(basic_report());
    crossplay = true; run_apply(); CHECK(observed_damage == 7 && !active());
    reset_fixture(); owner(); net_up = false;
    hello(1, true, true, false); receive(basic_report()); run_apply();
    CHECK(observed_damage == 7); // Receive handler itself is not active-gated either.
    reset_fixture(); owner(); ST32(MEMBER + 0x30, 1);
    hello(1, true, true, false); receive(basic_report()); run_apply(); CHECK(observed_damage == 7);
    // Local slot reports also accepted; receipt does not enforce slot != local.
    begin("characterize no reset, payload-slot trust and pending-report active-gate gap");
}

static void test_init(void) {
    reset_fixture();
    setenv("MHGU_HITSYNC_DIFF", "1", 1); nregistered = nset = 0;
    hitsync_init(); CHECK(nset == 1 && hook_addresses[0] == FN_HIT && registered[0] == hit_trace);
    unsetenv("MHGU_HITSYNC_DIFF"); setenv("MHGU_LOG_HITSYNC", "1", 1);
    nregistered = nset = 0; hitsync_init(); CHECK(nset == 3 && g_log);
    unsetenv("MHGU_LOG_HITSYNC"); initialize_hooks(); CHECK(!g_log);
    begin("normal hook registration and debug trace-only mode");
}

int main(int argc, char **argv) {
    unsetenv("MHGU_HITSYNC_DIFF"); unsetenv("MHGU_LOG_HITSYNC");
    initialize_hooks();
    if (argc == 2 && strcmp(argv[1], "--red-active-drain") == 0) {
        test_lifecycle_and_trust(true);
        fprintf(stderr, "unexpected RED proof pass\n"); return 3;
    }
    CHECK(argc == 1);
    test_tick_and_hello();
    test_negotiation();
    test_attack_filters();
    test_encoding_and_roundtrip();
    test_delta_edges();
    test_decoder();
    test_queues_and_order();
    test_lifecycle_and_trust(false);
    test_init();
    printf("test-hitsync: PASS (%u groups, %u fail-closed CHECKs; production Report=%zu)\n",
           groups, checks, sizeof(Report));
    return 0;
}
