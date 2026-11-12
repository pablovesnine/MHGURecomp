/* Actual title hook, bounded synthetic guest memory; no fixed host mappings.
 * Boundary doubles do not run game code or validate SDL concurrency. */
#include "test_0160_fixture.h"
#ifndef MHGU_TITLE_EXIT_SOURCE
#define MHGU_TITLE_EXIT_SOURCE "../runtime/hle/title_exit.c"
#endif

static Cpu cpu, returned;
static unsigned phase, originals, requests, state_reads;
static bool opened, read_permitted, change_state;
static uint64_t buttons;
static uint32_t incoming_title, state_address;
static unsigned char low_heap[32], high_heap[32];

static uint32_t title_load(uint32_t a) {
    assert(phase == 3);
    assert(read_permitted);
    assert(a == state_address);
    ++state_reads;
    return load(a, 1);
}
#undef LD8
#define LD8(a) title_load((uint32_t)(a))
#include MHGU_TITLE_EXIT_SOURCE /* production leaf, not a reimplementation */

void fnhook_call_original(Cpu *c, uint32_t fn) {
    assert(phase == 0 && fn == 0x87b544u);
    assert(c == &cpu && c->r[0] == incoming_title);
    ++originals;
    phase = 1;
    if (change_state) ST8(incoming_title + 4u, 0x11);
    /* Deliberately destroy r0 (and every other register / flag / vector).
     * The hook must save the incoming title, yet retain ALL original results. */
    memset(c, 0xa5, sizeof *c);
    for (unsigned i = 0; i < 16; ++i) c->r[i] = 0xcafe0000u + i;
    memcpy(&returned, c, sizeof returned);
}
void input_get(uint64_t *out, int32_t sticks[4]) {
    assert(phase == 1);
    phase = 2;
    *out = buttons;
    for (unsigned i = 0; i < 4; ++i) sticks[i] = (int32_t)i - 2;
}
bool overlay_menu_open(void) {
    assert(phase == 2);
    phase = 3;
    return opened;
}
void ui_request_exit_menu(void) {
    assert(phase == 3 && state_reads == 1);
    assert(memcmp(&returned, &cpu, sizeof cpu) == 0);
    ++requests;
    phase = 4;
}

/* expected_reads is an explicit test oracle, not copied production gating. */
static void invoke(uint32_t title, uint64_t pad, bool overlay,
                   unsigned expected_reads, unsigned wanted) {
    unsigned before = requests, calls = originals;
    phase = state_reads = 0;
    incoming_title = title;
    state_address = title + 4u;
    buttons = pad;
    opened = overlay;
    read_permitted = expected_reads != 0;
    init_cpu(&cpu);
    cpu.r[0] = title;
    assert(nregistered == 1);
    registered[0](&cpu); /* use the real init's captured callback */
    assert(originals == calls + 1);
    assert(state_reads == expected_reads);
    assert(requests == before + wanted);
    assert(phase == (wanted ? 4u : 3u));
    assert(memcmp(&returned, &cpu, sizeof cpu) == 0);
}
#define TITLE 0x08000000u
#define HIGH_TITLE 0xeffffffcu
#define B (UINT64_C(1) << BTN_B)

static void fresh(void) {
    /* Exercise the real statics, including the first release swallowed after a
     * cancellation; never expose or reset private production state. */
    invoke(TITLE, 0, true, 0, 0);
    invoke(TITLE, 0, false, 0, 0);
    ST8(TITLE + 4, 0x11);
}
static void edges_and_states(void) {
    fresh();
    invoke(TITLE, 0, false, 1, 0);
    invoke(TITLE, UINT64_C(1) << BTN_A, false, 1, 0);
    invoke(TITLE, B, false, 1, 1);
    for (unsigned i = 0; i < 16; ++i) invoke(TITLE, B, false, 1, 0);
    invoke(TITLE, 0, false, 1, 0);
    invoke(TITLE, B | (UINT64_C(1) << BTN_X), false, 1, 1);
    const unsigned char states[] = {0, 0x10, 0x12, 0xff};
    for (size_t i = 0; i < sizeof states; ++i) {
        fresh();
        ST8(TITLE + 4, states[i]);
        invoke(TITLE, B, false, 1, 0);
        ST8(TITLE + 4, 0x11);
        invoke(TITLE, B, false, 1, 0); /* held across state transition */
        invoke(TITLE, 0, false, 1, 0);
        invoke(TITLE, B, false, 1, 1);
    }
    fresh();
    ST8(TITLE + 4, 0x10);
    change_state = true;
    invoke(TITLE, B, false, 1, 1); /* state read AFTER original update */
    change_state = false;
}
static void pointer_boundaries(void) {
    const uint32_t invalid[] = {
        0, 4, 0x07fffffcu, 0x08000001u, 0x08000002u, 0x08000003u,
        0xeffffffdu, 0xf0000000u, 0xfffffffcu, 0xffffffffu
    };
    for (size_t i = 0; i < sizeof invalid / sizeof *invalid; ++i) {
        fresh();
        invoke(invalid[i], B, false, 0, 0); /* no guest dereference */
        invoke(TITLE, B, false, 1, 0); /* invalid-state B still refreshes edge */
        invoke(TITLE, 0, false, 1, 0);
        invoke(TITLE, B, false, 1, 1);
    }
    fresh();
    ST8(HIGH_TITLE + 4u, 0x11);
    invoke(HIGH_TITLE, B, false, 1, 1); /* highest aligned title below limit */
}
static void cancellation_and_overlay(void) {
    fresh();
    invoke(TITLE, B, false, 1, 1);
    invoke(TITLE, 0, true, 0, 0);
    invoke(TITLE, B, true, 0, 0); /* B cancels the open confirmation */
    invoke(TITLE, B, false, 0, 0);
    invoke(TITLE, B, false, 0, 0);
    invoke(TITLE, 0, false, 0, 0); /* release clears swallow, still returns */
    invoke(TITLE, 0, false, 1, 0);
    invoke(TITLE, B, false, 1, 1);
    /* Even when no B was down during overlay, suppress a B arriving on close
     * until a release has been observed by the title update. */
    invoke(0, 0, true, 0, 0); /* open overlay wins before pointer validation */
    invoke(TITLE, B, false, 0, 0);
    invoke(TITLE, 0, false, 0, 0);
    invoke(TITLE, B, false, 1, 1);
    invoke(TITLE, B, true, 0, 0);
    invoke(TITLE, 0, true, 0, 0);
    invoke(TITLE, 0, false, 0, 0);
    invoke(TITLE, B, false, 1, 1);
}
int main(void) {
    (void)record; /* Shared seam helper unused by this hook's custom original. */
    region(TITLE, low_heap, sizeof low_heap);
    region(0xeffffff0u, high_heap, sizeof high_heap);
    title_exit_init();
    assert(nregistered == 1 && nhooked == 1);
    assert(registered[0] == title_update);
    assert(hooked[0] == 0x87b544u && detours[0] == 0x03000010u);
    edges_and_states();
    pointer_boundaries();
    cancellation_and_overlay();
    puts("title exit: actual hook, registers, pointer/state edges and cancellation OK");
    return 0;
}
