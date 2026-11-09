// Public, synthetic regression for the REAL mousecam implementation.
// No game data, fixed-address host mappings, renderer, or network is used.
// From an external directory add -I<repo>/tests so the relative include resolves.
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "config.h"
#include "hle.h"

#define CHECK(x) do { if (!(x)) { \
    fprintf(stderr, "%s:%d [%s]: %s\n", __FILE__, __LINE__, case_name, #x); \
    exit(1); \
} } while (0)
static const char *case_name = "initialization";
static unsigned cases, calls;

// Fixture layout is independent of the implementation's macros. Only offsets,
// function addresses, and options globals documented in public source are used.
enum {
    CAM = 0x08001000, PLAYER = 0x08004000, OPTIONS = 0x08008000,
    OPTIONS_PTR = 0x01a8ca48,
    STICK_FN = 0x2255cc, AIM_FN = 0x4a1738, PARAM_FN = 0x21eadc,
    CAM_PLAYER = 0x85c, EYE_P = 0x9d8, EYE_Y = 0x9dc,
    NOW_P = 0x9e0, NOW_Y = 0x9e4, TO_P = 0x9e8, TO_Y = 0x9ec,
    AIM_Y = 0x14a0, AIM_P = 0x14b8, AIM_P2 = 0x14bc, LEAN = 0x2714
};
typedef struct {
    _Alignas(16) unsigned char camera[0xb00 + 8];
    _Alignas(16) unsigned char player[0x2800 + 8];
    _Alignas(16) unsigned char options[0x100 + 8];
    _Alignas(16) unsigned char options_ptr[8 + 8];
} Memory;
static Memory mem, wanted, entry_mem;
static void *resolve(Memory *m, uint32_t a) {
    // Leave eight bytes at the end of every segment: any LD/ST width <= 8 fits.
    // All other addresses fail immediately instead of touching host memory.
#define SEG(base, field) \
    if (a >= (uint32_t)(base) && \
        (uint64_t)a - (uint32_t)(base) <= sizeof m->field - 8) \
        return m->field + (a - (uint32_t)(base))
    SEG(CAM, camera);
    SEG(PLAYER, player);
    SEG(OPTIONS, options);
    SEG(OPTIONS_PTR, options_ptr);
#undef SEG
    fprintf(stderr, "[%s] unexpected synthetic guest address: %08x\n", case_name, a);
    exit(1);
}
static void *guest(uint32_t a) { return resolve(&mem, a); }
#undef G2H
#define G2H(a) guest((uint32_t)(a))
#include "../runtime/hle/mousecam.c"

// The expectation image checks EVERY byte, not only fields expected to change.
static void want_begin(void) { wanted = mem; }
static void want32(uint32_t a, uint32_t v) { memcpy(resolve(&wanted, a), &v, 4); }
static void want16(uint32_t a, uint16_t v) { memcpy(resolve(&wanted, a), &v, 2); }
static void wantf(uint32_t a, float v) { memcpy(resolve(&wanted, a), &v, 4); }
static void want_done(void) { CHECK(!memcmp(&mem, &wanted, sizeof mem)); }
static void nearf(float a, float b) { CHECK(fabsf(a - b) < 0.00001f); }

static Cpu cpu, entry_cpu;
static HostFn stick_hook, aim_hook;
static unsigned registrations, hooks, originals, params, sensitivity_reads;
static unsigned event[4], nevent;
static uint32_t expected_fn;
static uint64_t now_ns, entry_seen;
static float sensitivity, up_degrees, down_degrees, entry_dx, entry_dy;
static void (*original_effect)(void);
static unsigned phase;

uint64_t plat_now_ns(void) { return now_ns; }
float config_live_mouse_sensitivity(void) {
    CHECK(phase == 1); // Mouse application must follow the original handler.
    sensitivity_reads++;
    return sensitivity;
}
uint32_t hle_register(const char *name, HostFn fn) {
    CHECK(registrations == hooks && registrations < 2);
    if (!registrations) {
        CHECK(!strcmp(name, "mousecam:camera_stick"));
        CHECK(fn == camera_stick);
        stick_hook = fn;
    } else {
        CHECK(!strcmp(name, "mousecam:aim_turn"));
        CHECK(fn == aim_turn);
        aim_hook = fn;
    }
    return 0x03000000u + 16 * registrations++;
}
bool fnhook_set(uint32_t addr, uint32_t detour) {
    CHECK(registrations == hooks + 1 && hooks < 2);
    CHECK(addr == (hooks ? AIM_FN : STICK_FN));
    CHECK(detour == 0x03000000u + 16 * hooks);
    hooks++;
    return true;
}
static void check_callee_saved(Cpu *c) {
    for (unsigned i = 4; i <= 11; i++) CHECK(c->r[i] == entry_cpu.r[i]);
    CHECK(c->r[13] == entry_cpu.r[13] && c->r[14] == entry_cpu.r[14]);
    for (unsigned i = 16; i < 32; i++) CHECK(c->v.s[i] == entry_cpu.v.s[i]);
}
static void clobber_volatile(Cpu *c, uint32_t salt) {
    // AAPCS caller-saved state, not invented callee-saved corruption.
    for (unsigned i = 0; i < 4; i++) c->r[i] = salt + i;
    c->r[12] = salt + 12;
    c->pc = 0;
    c->nf = 1; c->zf = 0; c->cf = 1; c->vf = 0;
    for (unsigned i = 0; i < 16; i++) c->v.s[i] = salt + i;
    for (unsigned i = 32; i < 64; i++) c->v.s[i] = salt + i;
}
void fnhook_call_original(Cpu *c, uint32_t addr) {
    CHECK(c == &cpu && addr == expected_fn && phase == 0);
    CHECK(!memcmp(c, &entry_cpu, sizeof cpu));
    CHECK(!memcmp(&mem, &entry_mem, sizeof mem));
    CHECK(g_dx == entry_dx && g_dy == entry_dy && g_seen_ns == entry_seen);
    CHECK(nevent == 0);
    event[nevent++] = addr;
    originals++;
    phase = 1;
    if (original_effect) original_effect();
    clobber_volatile(c, 0xbad00000u);
}
void guest_call(Cpu *c, uint32_t addr) {
    CHECK(c == &cpu && addr == PARAM_FN && phase == 1);
    CHECK(c->r[0] == CAM && nevent >= 1 && nevent <= 2);
    CHECK(c->r[1] == (nevent == 1 ? 0x1du : 0x1eu));
    check_callee_saved(c);
    float result = c->r[1] == 0x1du ? up_degrees : down_degrees;
    event[nevent++] = c->r[1];
    params++;
    // dispatch.c:guest_call saves/restores ONLY LR. It does not restore r0-r3,
    // pc, flags, or VFP returns. Model legal volatile clobbers and s0 return.
    uint32_t lr = c->r[14];
    clobber_volatile(c, 0xcafe0000u);
    c->r[14] = lr;
    c->v.f[0] = result;
}
static void invoke(HostFn fn, uint32_t a0, uint32_t a1) {
    memset(&cpu, 0, sizeof cpu);
    for (unsigned i = 0; i < 16; i++) cpu.r[i] = 0xface0000u + i;
    for (unsigned i = 0; i < 64; i++) cpu.v.s[i] = 0xabc00000u + i;
    cpu.r[0] = a0; cpu.r[1] = a1;
    entry_cpu = cpu;
    entry_mem = mem;
    entry_dx = g_dx; entry_dy = g_dy; entry_seen = g_seen_ns;
    expected_fn = fn == stick_hook ? STICK_FN : AIM_FN;
    unsigned before = originals;
    nevent = phase = 0;
    params = sensitivity_reads = 0;
    fn(&cpu);
    CHECK(phase == 1 && originals == before + 1);
    CHECK(event[0] == expected_fn);
    CHECK(nevent == 1 || (nevent == 3 && event[1] == 0x1d && event[2] == 0x1e));
    CHECK(params == (nevent == 3 ? 2u : 0u));
    check_callee_saved(&cpu);
    calls++;
}
static void aim(unsigned mode) { invoke(aim_hook, PLAYER, mode); }
static void stick(unsigned invert) { invoke(stick_hook, CAM, invert); }
static void reset(const char *name) {
    case_name = name;
    cases++;
    memset(&mem, 0, sizeof mem);
    ST32(OPTIONS_PTR, OPTIONS);
    ST32(CAM + CAM_PLAYER, PLAYER);
    now_ns = 1000000000ull;
    sensitivity = 1.0f;
    up_degrees = down_degrees = 45.0f;
    original_effect = NULL;
    g_dx = g_dy = g_rest_yaw = g_rest_pitch = 0;
    g_seen_ns = 0; g_cam = 0; g_stick_runs = 0;
    // aim_turn's function-local last_runs cannot be assigned. Synchronize it
    // through the REAL hook with an invalid player, which must not take input.
    invoke(aim_hook, 0, 0);
    CHECK(!g_seen_ns && !params && !sensitivity_reads);
}
static void prime(void) {
    // Learn the camera through the real stick hook; acknowledge its run once.
    want_begin();
    stick(0);
    CHECK(g_cam == CAM && g_stick_runs == 1 && mousecam_active());
    aim(0);
    CHECK(!params && !sensitivity_reads);
    want_done();
}

static void first_use_and_timeout(void) {
    reset("first use / first aim handoff");
    CHECK(!mousecam_active());
    mousecam_add(4, 5);
    want_begin();
    aim(1); // No learned camera: do not consume or claim active.
    CHECK(g_dx == 4 && g_dy == 5 && !g_seen_ns);
    stick(0); // First actual turn handler discards preexisting motion.
    CHECK(!g_dx && !g_dy && mousecam_active() && !sensitivity_reads);
    mousecam_add(1, 1);
    aim(1); // Stick ran: aim must not take even newly queued motion.
    CHECK(g_dx == 1 && g_dy == 1 && !sensitivity_reads);
    want_done();
    want_begin();
    want32(PLAYER + AIM_Y, 65522); want32(CAM + EYE_Y, 65522);
    want16(PLAYER + LEAN, (uint16_t)-14);
    aim(1);
    want_done();
    CHECK(!g_dx && !g_dy && g_rest_yaw < 0 && g_rest_pitch < 0);

    reset("active deadline / stale aim discard / empty refresh");
    prime();
    mousecam_add(0.01f, 0.01f);
    aim(1);
    CHECK(g_rest_yaw != 0 && g_rest_pitch != 0);
    uint64_t seen = g_seen_ns;
    now_ns = seen + 199999999ull; CHECK(mousecam_active());
    now_ns = seen + 200000000ull; CHECK(!mousecam_active());
    mousecam_add(10, 10);
    want_begin();
    aim(1);
    want_done();
    CHECK(!g_dx && !g_dy && !g_rest_yaw && !g_rest_pitch);
    CHECK(mousecam_active() && g_seen_ns == now_ns && !sensitivity_reads);
    now_ns += 199999999ull;
    want_begin(); aim(1); want_done(); // Empty calls still keep ownership alive.
    CHECK(mousecam_active() && g_seen_ns == now_ns && !sensitivity_reads);
    now_ns += 200000001ull; CHECK(!mousecam_active());

    reset("stale camera discard");
    prime();
    now_ns += 200000000ull;
    mousecam_add(100, -100);
    want_begin(); stick(0); want_done();
    CHECK(!g_dx && !g_dy && !sensitivity_reads && mousecam_active());
}
static void gates(void) {
    const uint32_t invalid[] = {0, 0x07fffffc, 0x08004001, 0xf0000000, 0xfffffffc};
    for (unsigned i = 0; i < sizeof invalid / sizeof *invalid; i++) {
        reset("invalid player gate");
        prime();
        ST32(OPTIONS_PTR, 0); // A late options read would fail bounded mapping.
        mousecam_add(1, 1);
        uint64_t seen = g_seen_ns;
        now_ns += 200000000ull;
        want_begin(); invoke(aim_hook, invalid[i], 0); want_done();
        CHECK(g_dx == 1 && g_dy == 1 && g_seen_ns == seen);
        CHECK(!mousecam_active() && !params && !sensitivity_reads);

        reset("invalid learned camera gate");
        // Learn an invalid camera through production, not a fabricated pointer.
        want_begin(); invoke(stick_hook, invalid[i], 0); want_done();
        aim(0); // Acknowledge the stick run.
        ST32(OPTIONS_PTR, 0);
        mousecam_add(1, 1);
        seen = g_seen_ns;
        want_begin(); aim(0); want_done();
        CHECK(g_dx == 1 && g_dy == 1 && g_seen_ns == seen);
        CHECK(!params && !sensitivity_reads);
    }
    reset("camera/player mismatch and recovery");
    prime();
    ST32(CAM + CAM_PLAYER, PLAYER + 4);
    ST32(OPTIONS_PTR, 0);
    mousecam_add(1, 1);
    want_begin(); aim(1); want_done();
    CHECK(g_dx == 1 && g_dy == 1 && !params && !sensitivity_reads);
    ST32(CAM + CAM_PLAYER, PLAYER); ST32(OPTIONS_PTR, OPTIONS);
    want_begin();
    want32(PLAYER + AIM_Y, 65522); want32(CAM + EYE_Y, 65522);
    want16(PLAYER + LEAN, (uint16_t)-14);
    aim(1); want_done();
    CHECK(!g_dx && !g_dy);

    reset("invalid camera stick consumes but never dereferences camera");
    prime();
    mousecam_add(1, 1);
    want_begin(); invoke(stick_hook, 0, 0); want_done();
    CHECK(!g_dx && !g_dy && g_cam == 0 && sensitivity_reads == 1);
}
static void no_double_consume(void) {
    reset("camera then aim: no double consume, new motion stays queued");
    prime();
    mousecam_add(1, 1);
    want_begin();
    want32(CAM + TO_Y, 65522); want32(CAM + NOW_Y, 65522);
    want32(CAM + TO_P, 65522); want32(CAM + NOW_P, 65522);
    stick(0); want_done();
    mousecam_add(2, 0);
    uint64_t seen = g_seen_ns;
    now_ns++;
    want_begin(); aim(1); want_done();
    CHECK(g_dx == 2 && !g_dy && g_seen_ns == seen && !sensitivity_reads);
    want_begin();
    // -29 whole units, including the prior stick's fractional yaw remainder.
    want32(PLAYER + AIM_Y, 65507); want32(CAM + EYE_Y, 65507);
    aim(1); want_done();
    CHECK(!g_dx && !g_dy && sensitivity_reads == 1 && !params);
}
static void yaw_invert_and_lean(void) {
    for (unsigned invert = 0; invert < 4; invert++) {
        reset("aim yaw wrap / independent aim invert bits / mode 1");
        prime();
        ST8(OPTIONS + 0x66, invert);
        ST8(OPTIONS + 0x64, invert ^ 3); // Must NOT use the normal camera option.
        ST32(PLAYER + AIM_Y, 5); ST32(CAM + EYE_Y, 65530);
        ST32(CAM + EYE_P, 123);
        STF(PLAYER + AIM_P, 12); STF(PLAYER + AIM_P2, -12);
        int iy = invert & 2 ? 14 : -14;
        int ip = invert & 1 ? 14 : -14;
        want_begin();
        want32(PLAYER + AIM_Y, (5 + iy) & 65535);
        want32(CAM + EYE_Y, (65530 + iy) & 65535);
        want16(PLAYER + LEAN, (uint16_t)ip);
        mousecam_add(1, 1); aim(1); want_done();
        CHECK(!params && sensitivity_reads == 1);
        // In mode 1, current production changes lean, NOT eye pitch or floats.
        CHECK(LD32(CAM + EYE_P) == 123);
    }
    for (int sign = -1; sign <= 1; sign += 2) {
        reset("mode 1 signed lean and both clamps");
        prime();
        ST16(PLAYER + LEAN, sign * 8190);
        ST32(CAM + EYE_P, 777);
        want_begin(); want16(PLAYER + LEAN, (uint16_t)(sign * 8192));
        mousecam_add(0, (float)-sign); aim(1); want_done();
        CHECK(!params);
        want_begin();
        mousecam_add(0, (float)-sign); aim(1); want_done(); // At limit.
        CHECK(!params);
    }
    reset("mode 1 signed 16-bit lean read");
    prime();
    ST16(PLAYER + LEAN, (uint16_t)-2);
    want_begin(); want16(PLAYER + LEAN, (uint16_t)-16);
    mousecam_add(0, 1); aim(1); want_done();
}
static void pitch_mapping(void) {
    // Exact rounded ranges: 16384, 8192, 8192, 16384 guest angle units.
    const float ups[] = {45, 45, 0, 22.5f};
    const float downs[] = {45, 0, 45, 67.5f};
    const float expected[] = {0.1708984375f, 0.341796875f, 0.341796875f, 0.1708984375f};
    const unsigned modes[] = {0, 2, 3, 0xffffffffu};
    for (unsigned i = 0; i < 4; i++) {
        for (int sign = -1; sign <= 1; sign += 2) {
            reset("non-mode-1: up/down/asymmetric camparams and pitch copies");
            prime();
            up_degrees = ups[i]; down_degrees = downs[i];
            ST32(CAM + EYE_P, sign > 0 ? 65530 : 5);
            STF(PLAYER + AIM_P2, -37); // The copy must be overwritten.
            want_begin();
            wantf(PLAYER + AIM_P, sign * expected[i]);
            wantf(PLAYER + AIM_P2, sign * expected[i]);
            want32(CAM + EYE_P, ((sign > 0 ? 65530 : 5) + sign * 14) & 65535);
            mousecam_add(0, (float)-sign); aim(modes[i]); want_done();
            CHECK(params == 2 && sensitivity_reads == 1);
            // Volatile register changes from both parameter calls are legal.
            CHECK(cpu.r[0] == 0xcafe0000u && cpu.r[1] == 0xcafe0001u);
            nearf(cpu.v.f[0], down_degrees);
        }
    }
    for (unsigned i = 0; i < 3; i++) {
        reset("zero or wrapped parameter range: no pitch stores, yaw still works");
        prime();
        up_degrees = down_degrees = i == 0 ? 0 : i == 1 ? 0.001f : 180;
        STF(PLAYER + AIM_P, 12); STF(PLAYER + AIM_P2, -37);
        ST32(CAM + EYE_P, 4321);
        want_begin();
        want32(PLAYER + AIM_Y, 65522); want32(CAM + EYE_Y, 65522);
        mousecam_add(1, -1); aim(0); want_done();
        CHECK(params == 2);
    }
    reset("small rounded nonzero range: clamped aim, zero whole-unit eye step");
    prime();
    up_degrees = 0.004f; down_degrees = 0;
    want_begin(); wantf(PLAYER + AIM_P, 100); wantf(PLAYER + AIM_P2, 100);
    mousecam_add(0, -1); aim(0); want_done();
    CHECK(params == 2 && !g_rest_pitch);

    for (int sign = -1; sign <= 1; sign += 2) {
        reset("float aim clamp / eye actual travel / remainder reset");
        prime();
        STF(PLAYER + AIM_P, sign * 99.9f);
        STF(PLAYER + AIM_P2, -37);
        ST32(CAM + EYE_P, sign > 0 ? 65530 : 5);
        want_begin();
        wantf(PLAYER + AIM_P, sign * 100.0f);
        wantf(PLAYER + AIM_P2, sign * 100.0f);
        want32(CAM + EYE_P, ((sign > 0 ? 65530 : 5) + sign * 8) & 65535);
        mousecam_add(0, (float)-sign); aim(0); want_done();
        CHECK(params == 2 && !g_rest_pitch);
        want_begin();
        mousecam_add(0, (float)-sign); aim(0); want_done(); // Already clamped.
        CHECK(params == 2 && !g_rest_pitch);
    }
    reset("subunit pitch does not call guest parameters or touch pitch copy");
    prime();
    STF(PLAYER + AIM_P2, -37);
    want_begin(); mousecam_add(0, -0.01f); aim(0); want_done();
    CHECK(!params && g_rest_pitch > 0 && sensitivity_reads == 1);
}
static void camera_regressions(void) {
    for (unsigned invert = 0; invert < 4; invert++) {
        reset("normal camera yaw/pitch wrap and invert");
        prime();
        ST32(CAM + TO_Y, 5); ST32(CAM + NOW_Y, 65530);
        int iy = invert & 2 ? 14 : -14;
        int ip = invert & 1 ? 14 : -14;
        want_begin();
        want32(CAM + TO_Y, (5 + iy) & 65535);
        want32(CAM + NOW_Y, (65530 + iy) & 65535);
        want32(CAM + TO_P, ip & 65535); want32(CAM + NOW_P, ip & 65535);
        mousecam_add(1, 1); stick(invert); want_done();
        CHECK(!params && sensitivity_reads == 1);
    }
    for (int sign = -1; sign <= 1; sign += 2) {
        reset("normal camera clamp moves smoothed pitch by actual travel");
        prime();
        ST32(CAM + TO_P, (sign * 16126) & 65535);
        ST32(CAM + NOW_P, (sign * 16100) & 65535);
        want_begin();
        want32(CAM + TO_P, (sign * 16128) & 65535);
        want32(CAM + NOW_P, (sign * 16102) & 65535);
        mousecam_add(0, (float)-sign); stick(0); want_done();
        CHECK(!g_rest_pitch);
    }
}
static void fractions_and_sensitivity(void) {
    const float sensitivities[] = {0, 0.5f, 1, 2};
    const int turns[] = {0, -7, -14, -29};
    for (unsigned i = 0; i < 4; i++) {
        reset("live sensitivity and 100 fractional synthetic input batches");
        prime();
        sensitivity = sensitivities[i];
        ST32(PLAYER + AIM_Y, 1000); ST32(CAM + EYE_Y, 2000);
        want_begin();
        want32(PLAYER + AIM_Y, (uint32_t)(1000 + turns[i]));
        want32(CAM + EYE_Y, (uint32_t)(2000 + turns[i]));
        want16(PLAYER + LEAN, (uint16_t)turns[i]);
        for (unsigned j = 0; j < 100; j++) {
            // Two producers' additions are accumulated before consumption.
            mousecam_add(0.004f, 0.004f);
            mousecam_add(0.006f, 0.006f);
            aim(1);
            CHECK(!params && sensitivity_reads == 1 && !g_dx && !g_dy);
        }
        want_done();
        CHECK(LD32(PLAYER + AIM_Y) == (uint32_t)(1000 + turns[i]));
        CHECK(LD32(CAM + EYE_Y) == (uint32_t)(2000 + turns[i]));
        CHECK((int16_t)LD16(PLAYER + LEAN) == turns[i]);
        CHECK(fabsf(g_rest_yaw) < 1 && fabsf(g_rest_pitch) < 1);
        // No input must not leak a saved subunit into a whole-unit movement.
        want_begin(); aim(1); want_done();
        CHECK(!sensitivity_reads && !params);
    }
    reset("sensitivity is read at consume time, not input time");
    prime();
    mousecam_add(1, 0);
    sensitivity = 2;
    want_begin();
    want32(PLAYER + AIM_Y, 65507); want32(CAM + EYE_Y, 65507);
    aim(1); want_done();
    CHECK(sensitivity_reads == 1);
}
static void original_aim_writes(void) {
    ST32(PLAYER + AIM_Y, 2); ST32(CAM + EYE_Y, 7);
    ST16(PLAYER + LEAN, 9);
}
static void original_camera_writes(void) {
    ST32(CAM + TO_Y, 2); ST32(CAM + NOW_Y, 7);
    ST32(CAM + TO_P, 9); ST32(CAM + NOW_P, 10);
}
static void original_float_writes(void) {
    STF(PLAYER + AIM_P, 50); STF(PLAYER + AIM_P2, -37);
    ST32(CAM + EYE_P, 100);
}
static void original_breaks_link(void) { ST32(CAM + CAM_PLAYER, PLAYER + 4); }
static void original_ordering(void) {
    reset("original aim writes precede mouse writes, saved player/mode survive clobber");
    prime();
    original_effect = original_aim_writes;
    want_begin();
    want32(PLAYER + AIM_Y, 65524); want32(CAM + EYE_Y, 65529);
    want16(PLAYER + LEAN, (uint16_t)-5);
    mousecam_add(1, 1); aim(1); want_done();
    CHECK(!params && cpu.r[0] == 0xbad00000u);

    reset("original camera writes precede mouse writes, saved camera/invert survive");
    prime();
    original_effect = original_camera_writes;
    want_begin();
    want32(CAM + TO_Y, 65524); want32(CAM + NOW_Y, 65529);
    want32(CAM + TO_P, 23); want32(CAM + NOW_P, 24);
    mousecam_add(1, 1); stick(1); want_done();

    reset("original float aim baseline precedes camera-parameter callbacks");
    prime();
    original_effect = original_float_writes;
    want_begin();
    wantf(PLAYER + AIM_P, 50.1708984375f);
    wantf(PLAYER + AIM_P2, 50.1708984375f);
    want32(CAM + EYE_P, 114);
    mousecam_add(0, -1); aim(0); want_done();
    CHECK(params == 2);

    reset("player-link gate evaluated AFTER original");
    prime();
    original_effect = original_breaks_link;
    want_begin(); want32(CAM + CAM_PLAYER, PLAYER + 4);
    mousecam_add(1, 1); aim(0); want_done();
    CHECK(g_dx == 1 && g_dy == 1 && !params && !sensitivity_reads);
}
int main(void) {
    mousecam_init();
    CHECK(registrations == 2 && hooks == 2 && stick_hook && aim_hook);
    first_use_and_timeout();
    gates();
    no_double_consume();
    yaw_invert_and_lean();
    pitch_mapping();
    camera_regressions();
    fractions_and_sensitivity();
    original_ordering();
    printf("test-mousecam: %u synthetic scenarios, %u real-hook invocations: ok\n", cases, calls);
    return 0;
}
