/* Test seam only: retain real Cpu/declarations; replace fixed-window memory access.
 * No guest instruction execution, SDL, mmap, files, resources, or network.
 * Calls not explicitly stubbed by each fixture abort. Single-threaded scheduling;
 * pthread mutexes are real, but races / volatile publication are NOT validated. */
#ifndef SYNTHETIC_FIXTURE_H
#define SYNTHETIC_FIXTURE_H
#ifdef NDEBUG
#error "These synthetic regressions require assertions"
#endif
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
/* GCC-only parsing compatibility for cpu.h's unrelated inline rbit32.
 * These fixtures never execute that helper. Clang uses its native builtin. */
#if defined(__GNUC__) && !defined(__clang__)
static inline uint32_t fixture_bitreverse32(uint32_t v) {
    uint32_t out = 0;
    for (unsigned i = 0; i < 32; ++i) { out = (out << 1) | (v & 1u); v >>= 1; }
    return out;
}
#define __builtin_bitreverse32 fixture_bitreverse32
#endif
#include "../runtime/hle.h"

typedef struct { uint32_t base; size_t size; unsigned char *mem; } Region;
static Region regions[8];
static size_t nregions;
static void region(uint32_t base, void *mem, size_t size) {
    assert(nregions < sizeof regions / sizeof *regions);
    regions[nregions++] = (Region){base, size, mem};
}
static void *guest_ptr(uint32_t a, size_t n) {
    for (size_t i = 0; i < nregions; ++i) {
        Region *r = &regions[i];
        if (a >= r->base && (uint64_t)a - r->base <= r->size &&
            n <= r->size - (size_t)(a - r->base))
            return r->mem + (a - r->base);
    }
    fprintf(stderr, "unmapped synthetic guest access: %08x + %zu\n", a, n);
    abort();
}
static uint32_t load(uint32_t a, size_t n) {
    unsigned char *p = guest_ptr(a, n);
    uint32_t v = 0;
    for (size_t i = 0; i < n; ++i) v |= (uint32_t)p[i] << (8 * i);
    return v;
}
static void store(uint32_t a, uint32_t v, size_t n) {
    unsigned char *p = guest_ptr(a, n);
    for (size_t i = 0; i < n; ++i) p[i] = (unsigned char)(v >> (8 * i));
}
#undef G2H
#undef LD8
#undef LD16
#undef LD32
#undef ST8
#undef ST16
#undef ST32
#define G2H(a) guest_ptr((uint32_t)(a), 1)
#define LD8(a) load((uint32_t)(a), 1)
#define LD16(a) load((uint32_t)(a), 2)
#define LD32(a) load((uint32_t)(a), 4)
#define ST8(a,v) store((uint32_t)(a), (uint32_t)(v), 1)
#define ST16(a,v) store((uint32_t)(a), (uint32_t)(v), 2)
#define ST32(a,v) store((uint32_t)(a), (uint32_t)(v), 4)

typedef struct { uint32_t fn, args[4]; } Event;
static Event events[128];
static size_t nevents;
static void record(Cpu *c, uint32_t fn) {
    assert(nevents < sizeof events / sizeof *events);
    Event *e = &events[nevents++];
    e->fn = fn;
    memcpy(e->args, c->r, sizeof e->args);
}
static HostFn registered[8];
static uint32_t hooked[8], detours[8];
static size_t nregistered, nhooked;
uint32_t hle_register(const char *name, HostFn fn) {
    assert(name && fn && nregistered < 8);
    registered[nregistered++] = fn;
    return 0x03000000u + (uint32_t)nregistered * 16;
}
bool fnhook_set(uint32_t addr, uint32_t detour) {
    assert(nhooked < 8);
    hooked[nhooked] = addr;
    detours[nhooked++] = detour;
    return true;
}
static void init_cpu(Cpu *c) {
    memset(c, 0, sizeof *c);
    for (unsigned i = 0; i < 16; ++i) c->r[i] = 0xface0000u + i;
}
#endif
