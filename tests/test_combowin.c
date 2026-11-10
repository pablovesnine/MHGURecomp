// Real input-window hooks with bounded synthetic memory, no game or host map.
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "hle.h"
#include "config.h"
#ifdef NDEBUG
#error "This regression requires assertions"
#endif
#define CHECK(x) do { if (!(x)) { \
    fprintf(stderr, "%s:%d: check failed: %s\n", __FILE__, __LINE__, #x); exit(1); \
} } while (0)
enum { PLAYER = 0x08000000, OTHER = 0x08002000,
       OPTIONS = 0x08005000, SYSTEM = 0x0800a000 };
static _Alignas(16) unsigned char players[0x4000], options[0x4500], system_mem[0x100];
static _Alignas(16) unsigned char sys_ptr[8], opt_ptr[8];
static void *guest(uint32_t addr) {
    if (addr == 0x2326764u) return sys_ptr;
    if (addr == 0x1a97f78u) return opt_ptr;
    if (addr >= PLAYER && addr - PLAYER <= sizeof players - 8)
        return players + (addr - PLAYER);
    if (addr >= OPTIONS && addr - OPTIONS <= sizeof options - 8)
        return options + (addr - OPTIONS);
    CHECK(addr >= SYSTEM && addr - SYSTEM <= sizeof system_mem - 8);
    return system_mem + (addr - SYSTEM);
}
#undef G2H
#define G2H(a) guest((uint32_t)(a))
#ifndef MHGU_COMBOWIN_SOURCE
#define MHGU_COMBOWIN_SOURCE "../runtime/hle/combowin.c"
#endif
#include MHGU_COMBOWIN_SOURCE

static int mode = COMBO_LENIENT;
int config_live_combo_window(void) { return mode; }

static void frame(uint16_t held, uint16_t word, uint32_t flags,
                  uint16_t expected, float tick) {
    ST16(PLAYER + PL_HELD, held);
    ST16(PLAYER + PL_NEW, word);
    ST32(PLAYER + PL_FLAGS, flags);
    combowin_begin(PLAYER);
    CHECK(LD16(PLAYER + PL_NEW) == expected);
    CHECK(combowin_tick() == tick);
    CHECK(LD16(PLAYER + PL_HELD) == held && LD32(PLAYER + PL_FLAGS) == flags);
    combowin_end(PLAYER);
    CHECK(LD16(PLAYER + PL_NEW) == word);
    CHECK(!g_pl && !g_stop);
}
static void reset(float step, bool zr) {
    memset(players, 0, sizeof players);
    memset(options, 0, sizeof options);
    memset(system_mem, 0, sizeof system_mem);
    ST32(G_SYSTEM, SYSTEM);
    ST32(G_OPTIONS, OPTIONS);
    STF(SYSTEM + 0x68, step);
    ST8(OPTIONS + 0x446e, zr);
    ST8(OTHER + PL_LOCAL, 1);
    ST8(PLAYER + PL_LOCAL, 1);
    mode = COMBO_LENIENT;
    // A different local player resets the production function's private state.
    combowin_begin(OTHER);
    combowin_end(OTHER);
    frame(0, 0, 0, 0, step > 0 && step < 2 ? step * .5f : 1.0f);
}
int main(void) {
    const uint16_t x = 0x100, a = 0x20, b = 0x10, pass = 0x400;
    const float steps[] = {0, -1, NAN, INFINITY, 2, 3};
    for (unsigned i = 0; i < sizeof steps / sizeof *steps; i++) {
        reset(steps[i], false);
        frame(PAD_R | x, PAD_R | x | pass, 0, PAD_R | x | pass, 1);
    }
    reset(.5f, false);
    ST32(G_SYSTEM, 0);
    frame(x, x, 0, x, 1);
    ST32(G_SYSTEM, SYSTEM);
    mode = COMBO_STRICT;
    frame(PAD_R | x, PAD_R | x, 0, PAD_R | x, 1);
    mode = COMBO_LENIENT;
    ST8(PLAYER + PL_LOCAL, 0);
    frame(x, x | pass, 0, x | pass, .25f);
    ST8(PLAYER + PL_LOCAL, 1);
    puts("test-combowin: local, strict, missing-system and step gates: ok");

    reset(.5f, false);
    frame(x, x | pass, 0, x | pass, .25f);  // Lone press is not delayed.
    frame(x, x, 1 | ((uint32_t)x << 13), 0, .25f);  // Held repeat in a window.
    frame(0, 0, 0, 0, .25f);
    frame(PAD_R, PAD_R, 0, PAD_R, .25f);
    frame(PAD_R, PAD_R, 0, 0, .25f);  // A held modifier is not new.
    frame(PAD_R | x, PAD_R | x, 0, x, .25f);
    puts("test-combowin: real presses and held modifier filtering: ok");

    reset(.5f, false);
    frame(PAD_R | x, PAD_R | x | pass, 0, pass, 0);
    frame(PAD_R | x, PAD_R | x, 0, 0, 0);
    frame(PAD_R | x | a, PAD_R | x | a, 0, PAD_R | x | a, .25f);
    // The original new-press word is restored after every synthetic update.
    reset(.5f, false);
    frame(x, x, 0, x, .25f);
    frame(x | a, a, 1 | ((uint32_t)x << 13), 0, 0);
    frame(x | a | PAD_R, PAD_R, 1 | ((uint32_t)x << 13), a | PAD_R, .25f);
    puts("test-combowin: pair delay, saved presses and third-button release: ok");

    reset(.5f, false);
    frame(PAD_R | x, PAD_R | x, 0, 0, 0);
    for (int i = 0; i < 3; i++) frame(PAD_R | x, PAD_R | x, 0, 0, 0);
    frame(PAD_R | x, PAD_R | x, 0, PAD_R | x, .25f);
    reset(.5f, false);
    frame(PAD_R | x, PAD_R | x, 0, 0, 0);
    frame(x, x, 0, PAD_R | x, .25f);  // Release flushes the waiting presses.
    reset(.5f, false);
    frame(PAD_R | x, PAD_R | x, 0, 0, 0);
    frame(PAD_R | x | b, b, 0, PAD_R | x | b, .25f);
    puts("test-combowin: bounded timeout, release and other-face flush: ok");

    reset(.5f, false);
    ST32(G_OPTIONS, 0);  // Missing options use R.
    frame(x | a | PAD_R, x | a | PAD_R, 0, x | a | PAD_R, .25f);
    frame(x | PAD_R, x | PAD_R, 0, 0, .25f);  // Leftover X cannot repeat.
    frame(PAD_R, PAD_R, 0, 0, .25f);
    frame(x | PAD_R, x | PAD_R, 0, x, .25f);  // X went up, then down.
    reset(.5f, true);
    frame(PAD_ZR | x, PAD_ZR | x, 0, 0, 0);
    frame(PAD_ZR | x | a, PAD_ZR | x | a, 0, PAD_ZR | x | a, .25f);
    puts("test-combowin: leftover suppression, options fallback and ZR: ok");
    return 0;
}
