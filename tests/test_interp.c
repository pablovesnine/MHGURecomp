/*
 * Public synthetic A32 interpreter regression: no game files / generated code.
 * Requires >=0.15 interp_exec_op and interp_code_changed; build must be pin-gated.
 * clang -fuse-ld=lld -fsigned-char -std=gnu11 -O1 -fno-strict-aliasing \
 *   -ffp-contract=off -Iruntime tests/test_interp.c runtime/interp.c \
 *   runtime/neon.c runtime/simd_int.c -lm -pthread -o test_interp
 * Linux AArch64/x86_64: nonclobbering synthetic G2H pages only. No private cache
 * structures, ASan address-layout dependency, timing or target speed assertions.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/wait.h>
#include <unistd.h>
#include "interp.h"
#include "rt.h"

/* Debug entry points are exported by interp.c but lack public declarations. */
extern void interp_watch(uint32_t addr, int n);
extern void interp_read_watch(uint32_t lo, uint32_t hi);

#define CODE 0x03210000u
#define LOW 0x00210000u
#define DATA 0x10010000u
#define BIG 0x05000000u
#define RET 0x08000000u
#define CALLOUT (CODE + 0x200000u)
#define BX_LR 0xe12fff1eu
#define MEM_N 256u
#define BIG_BLOCKS 4096u
static unsigned checks, steps;
static const char *phase = "startup";
static unsigned char mem_before[MEM_N], mem_want[MEM_N];
static struct { uint32_t a, n; } mappings[8];
static unsigned nmappings;
static void fail(const char *what, uint32_t got, uint32_t want) {
    fprintf(stderr, "FAIL [%s] %s: got %08x, expected %08x\n", phase, what, got, want);
    exit(1);
}
static void eq(const char *what, uint32_t got, uint32_t want) {
    checks++;
    if (got != want) fail(what, got, want);
}
static void unexpected(const char *service) __attribute__((noreturn));
static void unexpected(const char *service) {
    fprintf(stderr, "UNEXPECTED [%s] runtime service: %s\n", phase, service);
    _Exit(90);
}

/* Only explicitly controlled callbacks may succeed. */
uint8_t g_fnhook[0x03000000u >> 5];
static uint32_t kept_pc, kept[2];
static int keep_on, diagnostic, callback_mode, callbacks;
bool fnhook_entry_word(uint32_t pc, uint32_t *w) {
    if (keep_on && (pc == kept_pc || pc == kept_pc + 4)) {
        *w = kept[(pc - kept_pc) / 4]; return true;
    }
    unexpected("unrequested kept word");
}
bool kernel_mapped(uint64_t a, uint32_t size) {
    for (unsigned i = 0; i < nmappings; i++)
        if (a >= mappings[i].a && a + size >= a &&
            a + size <= (uint64_t)mappings[i].a + mappings[i].n) return true;
    unexpected("kernel_mapped outside synthetic mappings");
}
uint32_t kernel_heap_size(void) { unexpected("kernel_heap_size"); }
void forge_guest_fault(uint32_t pc, uint32_t a, int n, int wr, const char *why) {
    (void)pc; (void)a; (void)n; (void)wr; (void)why; unexpected("forge_guest_fault");
}
uint64_t rt_ticks(void) { unexpected("rt_ticks"); }
uint64_t plat_now_ns(void) { unexpected("plat_now_ns (disable MHGU_INTERP_STATS)"); }
void rt_fatal_trace(void) { if (diagnostic == 73) _Exit(73); unexpected("fatal"); }
void rt_bkpt(Cpu *c, uint32_t imm, uint32_t pc) {
    (void)c; (void)imm; (void)pc; unexpected("bkpt");
}
void rt_udf(Cpu *c, uint32_t pc) { (void)c; (void)pc; unexpected("udf"); }
void rt_thumb(Cpu *c, uint32_t pc) {
    (void)c; (void)pc; if (diagnostic == 71) _Exit(71); unexpected("thumb");
}
static Cpu fresh(void) {
    Cpu c = {0};
    c.excl_addr = ~0u; c.r[13] = DATA + 0xf000; c.r[14] = RET;
    c.tpidruro = 0x12345678; c.tpidrurw = 0x76543210; return c;
}
static void arch_eq(const Cpu *a, const Cpu *b) {
    /* No Cpu memcmp: padding, host thread pointers and unused r15 are not ISA. */
    for (unsigned i = 0; i < 15; i++) eq("register", a->r[i], b->r[i]);
#define FIELD(f) eq(#f, a->f, b->f)
    FIELD(pc); FIELD(nf); FIELD(zf); FIELD(cf); FIELD(vf);
    FIELD(qf); FIELD(ge); FIELD(fpscr); FIELD(tpidruro); FIELD(tpidrurw); FIELD(excl_addr);
#undef FIELD
    eq("exclusive low", (uint32_t)a->excl_val, (uint32_t)b->excl_val);
    eq("exclusive high", a->excl_val >> 32, b->excl_val >> 32);
    for (unsigned i = 0; i < sizeof a->v.b; i++) eq("vector byte", a->v.b[i], b->v.b[i]);
}
static void map_guest(uint32_t a, uint32_t n) {
    int flags = MAP_PRIVATE | MAP_ANONYMOUS;
#ifdef MAP_FIXED_NOREPLACE
    flags |= MAP_FIXED_NOREPLACE;
#endif
    void *p = mmap(G2H(a), n, PROT_READ | PROT_WRITE, flags, -1, 0);
    if (p == MAP_FAILED || p != G2H(a)) {
        int error = errno;
        if (p != MAP_FAILED) munmap(p, n);
        fprintf(stderr, "INFRA: nonclobber-map G2H(%08x), %u bytes failed: %s\n",
                a, n, p == MAP_FAILED ? strerror(error) : "kernel chose a different address");
        exit(2);
    }
    mappings[nmappings].a = a; mappings[nmappings++].n = n;
}
static void pattern(void) {
    for (unsigned i = 0; i < MEM_N; i++) mem_before[i] = (unsigned char)(i * 29 + 7);
    memcpy(mem_want, mem_before, MEM_N);
}
static void bytes_at(unsigned off, uint32_t value, unsigned size) {
    for (unsigned i = 0; i < size; i++) mem_before[off + i] = value >> (8 * i);
    memcpy(mem_want, mem_before, MEM_N);
}
static void step_at(uint32_t pc, uint32_t w, Cpu in, Cpu want, uint32_t next, int link) {
    Cpu a = in, b = in;
    int la = -1, lb = -1;
    unsigned char out[MEM_N];
    memcpy(G2H(DATA), mem_before, MEM_N);
    uint32_t na = interp_exec(&a, pc, w, &la);
    memcpy(out, G2H(DATA), MEM_N);
    memcpy(G2H(DATA), mem_before, MEM_N);
    uint32_t nb = interp_exec_op(&b, pc, w, &lb);
    eq("semantic next PC", na, next); eq("op next PC", nb, next);
    eq("semantic link", la, link); eq("op link", lb, link);
    arch_eq(&a, &want); arch_eq(&b, &want); arch_eq(&a, &b);
    for (unsigned i = 0; i < MEM_N; i++) {
        eq("semantic memory", out[i], mem_want[i]); eq("op memory", LD8(DATA + i), mem_want[i]);
    }
    steps++;
}
static void step(uint32_t w, Cpu in, Cpu want) { step_at(CODE, w, in, want, CODE + 4, 0); }
static uint32_t branch(uint32_t from, uint32_t to, int link) {
    int64_t delta = (int64_t)to - from - 8;
    if ((delta & 3) || delta < -33554432 || delta > 33554428)
        unexpected("synthetic B/BL target outside A32 range");
    return (link ? 0xeb000000u : 0xea000000u) | (((to - from - 8) >> 2) & 0xffffffu);
}
static uint32_t dp(unsigned op, int flags, int imm, unsigned operand) {
    return 0xe0000000u | ((unsigned)imm << 25) | (op << 21) |
           ((unsigned)flags << 20) | (1u << 16) | operand;
}
static uint32_t alu(unsigned op, uint32_t a, uint32_t b) {
    switch (op) {
    case 0: return a & b; case 1: return a ^ b;
    case 2: return a - b; case 3: return b - a; case 4: return a + b;
    case 12: return a | b; case 13: return b; case 14: return a & ~b; case 15: return ~b;
    default: unexpected("test ALU opcode");
    }
}
static void arithmetic_flags(Cpu *c, uint32_t a, uint32_t b, int sub) {
    uint64_t wide = sub ? (uint64_t)a + (uint64_t)(~b) + 1 : (uint64_t)a + b;
    int64_t signed_result = sub ? (int64_t)(int32_t)a - (int64_t)(int32_t)b :
                                 (int64_t)(int32_t)a + (int64_t)(int32_t)b;
    uint32_t r = (uint32_t)wide;
    c->nf = r >> 31; c->zf = r == 0; c->cf = wide > UINT32_MAX;
    c->vf = signed_result < INT32_MIN || signed_result > INT32_MAX;
}
static int predicate(unsigned cond, unsigned bits) {
    int n = (bits >> 3) & 1, z = (bits >> 2) & 1, c = (bits >> 1) & 1, v = bits & 1;
    switch (cond) {
    case 0: return z; case 1: return !z; case 2: return c; case 3: return !c;
    case 4: return n; case 5: return !n; case 6: return v; case 7: return !v;
    case 8: return c && !z; case 9: return !c || z;
    case 10: return n == v; case 11: return n != v;
    case 12: return !z && n == v; case 13: return z || n != v; case 14: return 1;
    default: unexpected("test condition");
    }
}
static void flags_set(Cpu *c, unsigned bits) {
    c->nf = (bits >> 3) & 1; c->zf = (bits >> 2) & 1; c->cf = (bits >> 1) & 1; c->vf = bits & 1;
}
static void test_integer(void) {
    phase = "integer / independent ISA + semantic-op parity"; pattern();
    const unsigned ops[] = {0, 1, 2, 3, 4, 12, 13, 14, 15}, shifts[] = {0, 1, 31};
    const uint32_t values[] = {0, 1, 0x7fffffff, 0x80000000, 0xffffffff, 0x55555555, 0xaaaaaaaa};
    const struct { unsigned enc; uint32_t value; } imms[] = {{0, 0}, {0xff, 0xff}, {0x480, 0x80000000}};
    for (unsigned k = 0; k < sizeof ops / sizeof *ops; k++)
        for (unsigned a = 0; a < sizeof values / sizeof *values; a++) {
            for (unsigned j = 0; j < 3; j++) {
                Cpu in = fresh(); in.r[1] = values[a]; flags_set(&in, 15);
                Cpu want = in; want.r[0] = alu(ops[k], in.r[1], imms[j].value);
                step(dp(ops[k], 0, 1, imms[j].enc), in, want);
            }
            for (unsigned j = 0; j < 3; j++)
                for (unsigned b = 0; b < sizeof values / sizeof *values; b++) {
                    Cpu in = fresh(); in.r[1] = values[a]; in.r[2] = values[b]; flags_set(&in, 15);
                    Cpu want = in; want.r[0] = alu(ops[k], in.r[1], in.r[2] << shifts[j]);
                    step(dp(ops[k], 0, 0, 2 | (shifts[j] << 7)), in, want);
                }
        }
    const unsigned flagops[] = {2, 4, 10, 11};
    for (unsigned k = 0; k < 4; k++)
        for (unsigned a = 0; a < sizeof values / sizeof *values; a++)
            for (unsigned b = 0; b < sizeof values / sizeof *values; b++)
                for (unsigned j = 0; j < 3; j++) {
                    Cpu in = fresh(); in.r[0] = 0x12345; in.r[1] = values[a]; in.r[2] = values[b];
                    Cpu want = in; int sub = flagops[k] == 2 || flagops[k] == 10;
                    uint32_t operand = in.r[2] << shifts[j];
                    arithmetic_flags(&want, in.r[1], operand, sub);
                    if (flagops[k] < 8) want.r[0] = sub ? in.r[1] - operand : in.r[1] + operand;
                    step(dp(flagops[k], 1, 0, 2 | (shifts[j] << 7)), in, want);
                    want = in; arithmetic_flags(&want, in.r[1], imms[j].value, sub);
                    if (flagops[k] < 8) want.r[0] = sub ? in.r[1] - imms[j].value : in.r[1] + imms[j].value;
                    step(dp(flagops[k], 1, 1, imms[j].enc), in, want);
                }
    for (unsigned carry = 0; carry < 2; carry++)
        for (unsigned j = 0; j < 3; j++) {
            Cpu in = fresh(); in.r[1] = in.r[2] = 0x80000001; in.cf = carry; in.vf = 1;
            Cpu want = in; uint32_t result = in.r[1] & imms[j].value;
            want.nf = result >> 31; want.zf = result == 0; want.cf = j == 2 ? 1 : carry;
            step(dp(8, 1, 1, imms[j].enc), in, want);
            want = in; want.nf = 1; want.zf = 0; step(dp(8, 1, 0, 2), in, want);
        }
    for (unsigned carry = 0; carry < 2; carry++) {
        Cpu in = fresh(); in.r[1] = 0x80000001; in.cf = carry; in.vf = 1;
        Cpu want = in; want.nf = want.zf = want.cf = 0;
        step(dp(8, 1, 1, 0x104), in, want); /* TST #ROR(4,2)=1, rotated carry=0 */
    }
    Cpu in = fresh(), want = in;
    want.r[0] = 0x1234; step(0xe3010234, in, want);
    in.r[0] = 0x98761234; want = in; want.r[0] = 0xabcd1234; step(0xe34a0bcd, in, want);
}
static Cpu run_from(uint32_t entry, Cpu c) {
    c.pc = entry; interp_run(&c); eq("run fault PC clear", g_ip_pc, 0); return c;
}
static void test_predication(void) {
    phase = "all 15 conditions x all 16 NZCV / actual cached run";
    uint32_t p = CODE + 0x1000; ST32(p + 4, BX_LR); interp_add_range(p, p + 8);
    for (unsigned bits = 0; bits < 16; bits++)
        for (unsigned cond = 0; cond < 15; cond++) {
            Cpu in = fresh(); flags_set(&in, bits); in.r[0] = 17;
            Cpu want = in; want.r[0] += predicate(cond, bits);
            uint32_t word = (cond << 28) | 0x02800001;
            step(word, in, want); ST32(p, word);
            Cpu got = run_from(p, in); want.pc = p; arch_eq(&got, &want);
            if (!predicate(cond, bits)) {
                in.r[1] = 0x20000000; /* deliberately unmapped */
                step((cond << 28) | 0x05b10004, in, in); /* LDR pre writeback */
                step((cond << 28) | 0x04810004, in, in); /* STR post writeback */
                ST32(p, (cond << 28) | 0x05b10004);
                got = run_from(p, in); want = in; want.pc = p; arch_eq(&got, &want);
                ST32(p, (cond << 28) | 0x04810004);
                got = run_from(p, in); arch_eq(&got, &want);
            }
        }
}
static void test_memory(void) {
    phase = "loads / stores / addressing / independent byte expectations";
    const struct { uint32_t word, value; unsigned size; } loads[] = {
        {0xe5910000, 0x80fedc01, 4}, {0xe5d10000, 0x80, 1},
        {0xe1d100b0, 0x8001, 2}, {0xe1d100d0, 0xffffff80, 1}, {0xe1d100f0, 0xffff8001, 2}
    };
    for (unsigned k = 0; k < sizeof loads / sizeof *loads; k++)
        for (unsigned misalign = 0; misalign < 2; misalign++) {
            pattern(); unsigned off = 32 + misalign; bytes_at(off, loads[k].value, loads[k].size);
            Cpu in = fresh(); in.r[1] = DATA + off;
            Cpu want = in; want.r[0] = loads[k].value; step(loads[k].word, in, want);
            in.r[1] -= 4; want = in; want.r[0] = loads[k].value; step(loads[k].word | 4, in, want);
            in.r[1] += 8; want = in; want.r[0] = loads[k].value;
            step((loads[k].word & ~(1u << 23)) | 4, in, want);
            in.r[1] = DATA + off - 4; in.r[2] = 4; want = in; want.r[0] = loads[k].value;
            uint32_t reg = loads[k].size == 4 || k == 1 ?
                (loads[k].word | (1u << 25) | 2) : ((loads[k].word & ~(1u << 22)) | 2);
            step(reg, in, want);
        }
    const uint32_t stores[] = {0xe5810000, 0xe5c10000, 0xe1c100b0};
    const unsigned sizes[] = {4, 1, 2};
    for (unsigned k = 0; k < 3; k++)
        for (unsigned misalign = 0; misalign < 2; misalign++) {
            pattern(); Cpu in = fresh(); in.r[0] = 0x89abcdef; in.r[1] = DATA + 32 + misalign;
            for (unsigned i = 0; i < sizes[k]; i++) mem_want[32 + misalign + i] = in.r[0] >> (8 * i);
            step(stores[k], in, in);
            in.r[1] -= 4; step(stores[k] | 4, in, in);
            in.r[1] += 8; step((stores[k] & ~(1u << 23)) | 4, in, in);
            in.r[1] = DATA + 28 + misalign; in.r[2] = 4;
            uint32_t reg = k < 2 ? (stores[k] | (1u << 25) | 2) : ((stores[k] & ~(1u << 22)) | 2);
            step(reg, in, in);
        }
    for (unsigned byte = 0; byte < 2; byte++)
        for (unsigned pre = 0; pre < 2; pre++)
            for (unsigned up = 0; up < 2; up++)
                for (unsigned load = 0; load < 2; load++) {
                    pattern(); bytes_at(32, 0x87654321, 4);
                    Cpu in = fresh(); in.r[0] = 0x11223344; int delta = up ? 4 : -4;
                    in.r[1] = DATA + 32 - (pre ? delta : 0); Cpu want = in; want.r[1] += delta;
                    if (load) want.r[0] = byte ? 0x21 : 0x87654321;
                    else for (unsigned i = 0; i < (byte ? 1u : 4u); i++) mem_want[32 + i] = in.r[0] >> (8 * i);
                    uint32_t word = 0xe4000004 | (pre << 24) | (up << 23) |
                        (byte << 22) | (pre << 21) | (load << 20) | (1u << 16);
                    step(word, in, want);
                }
    pattern(); bytes_at(32, 0x1234abcd, 4);
    Cpu in = fresh(); in.r[1] = DATA + 24; in.r[2] = 2;
    Cpu want = in; want.r[0] = 0x1234abcd; step(0xe7910102, in, want);
    /* Shifted register word/byte stores and byte loads, and negative register fallback. */
    want.r[0] = 0xcd; step(0xe7d10102, in, want);
    for (unsigned byte = 0; byte < 2; byte++) {
        pattern(); in = fresh(); in.r[1] = DATA + 24; in.r[2] = 2; in.r[0] = 0x10203040;
        for (unsigned i = 0; i < (byte ? 1u : 4u); i++) mem_want[32 + i] = in.r[0] >> (8 * i);
        step(0xe7810102 | (byte << 22), in, in);
    }
    pattern(); bytes_at(32, 0x1234abcd, 4);
    in = fresh(); in.r[1] = DATA + 36; in.r[2] = 4; want = in; want.r[0] = 0x1234abcd;
    step(0xe7110002, in, want); /* LDR r0,[r1,-r2] */
    want.r[0] = 0xabcd; step(0xe11100b2, in, want); /* LDRH r0,[r1,-r2] */
    in.r[1] = 0xfffffff0; in.r[2] = DATA + 48; want = in; want.r[0] = 0x1234abcd;
    step(0xe7910002, in, want); /* effective address wraps to DATA+32 */
    in = fresh(); in.r[1] = DATA + 28; want = in; want.r[1] = 0x1234abcd;
    step(0xe5b11004, in, want); /* aliasing rn==rt pre-index fallback */
    in = fresh(); in.r[1] = DATA + 32; want = in; want.r[1] = 0x1234abcd; step(0xe4911004, in, want);
    in = fresh(); in.r[1] = DATA + 28; want = in; want.r[1] += 4;
    for (unsigned i = 0; i < 4; i++) mem_want[32 + i] = in.r[1] >> (8 * i);
    step(0xe5a11004, in, want); /* STR r1,[r1,#4]! stores old base before writeback */
    pattern(); bytes_at(32, 0x1234abcd, 4);
    ST32(CODE + 8, 0xaabbccdd);
    in = fresh(); want = in; want.r[0] = 0xaabbccdd; step(0xe59f0000, in, want);
    in.r[1] = DATA + 32 - (CODE + 8); want = in; want.r[0] = 0x1234abcd;
    step(0xe791000f, in, want); /* rm==PC fallback */
    in = fresh(); in.r[1] = DATA + 32; bytes_at(32, CODE + 0x80, 4);
    step_at(CODE, 0xe591f000, in, in, CODE + 0x80, 0); /* rt==PC */
}
static void test_branches_fallback(void) {
    phase = "branches / slow fallback representatives"; pattern();
    for (unsigned link = 0; link < 2; link++)
        for (unsigned back = 0; back < 2; back++) {
            Cpu in = fresh(), want = in; uint32_t target = back ? CODE - 16 : CODE + 64;
            if (link) want.r[14] = CODE + 4;
            step_at(CODE, branch(CODE, target, link), in, want, target, link);
            in.zf = 0;
            step_at(CODE, branch(CODE, target, link) & 0x0fffffff, in, in, CODE + 4, 0);
        }
    Cpu in = fresh(); in.r[2] = CODE + 128;
    step_at(CODE, 0xe12fff12, in, in, CODE + 128, 0);
    Cpu want = in; want.r[14] = CODE + 4;
    step_at(CODE, 0xe12fff32, in, want, CODE + 128, 1);
    in = fresh(); in.r[1] = 0x80000002; in.r[2] = 0x80000000;
    want = in; want.r[0] = 0x40000000; step(0xe1a000a2, in, want); /* LSR #1 */
    want.r[0] = 0xc0000000; step(0xe1a000c2, in, want); /* ASR #1 */
    want.r[0] = 0x40000000; step(0xe1a000e2, in, want); /* ROR #1 */
    in.cf = 1; want = in; want.r[0] = 3; step(0xe0a10002, in, want); /* ADC */
    want.r[0] = 2; step(0xe0c10002, in, want); /* SBC */
    pattern(); bytes_at(32, 0x12345678, 4); bytes_at(36, 0x87654321, 4);
    in = fresh(); in.r[2] = DATA + 32;
    want = in; want.r[0] = 0x12345678; want.r[1] = 0x87654321; want.r[2] += 8;
    step(0xe8b20003, in, want);
    in = fresh(); in.v.s[1] = 0x3f800000; want = in; want.v.s[0] = 0x3f800000;
    step(0xeeb00a60, in, want); /* VMOV.F32 s0,s1 */
    in.v.d[0] = UINT64_MAX; in.v.d[1] = 0x123456789abcdef0;
    want = in; want.v.d[0] = want.v.d[1] = 0; step(0xf3000150, in, want); /* VEOR q0,q0,q0 */
    in = fresh(); want = in; want.r[0] = in.tpidruro; step(0xee1d0f70, in, want);
}
static void test_cache_edits(void) {
    phase = "warm raw first/middle/last edits / linked target / branch before literal";
    uint32_t p = CODE + 0x2000, target = p + 0x100; interp_add_range(p, p + 0x200);
    for (unsigned pos = 0; pos < 3; pos++) {
        for (unsigned i = 0; i < 3; i++) ST32(p + i * 4, 0xe2800001);
        ST32(p + 12, BX_LR);
        for (unsigned warm = 0; warm < 2; warm++) eq("warm", run_from(p, fresh()).r[0], 3);
        ST32(p + pos * 4, 0xe2800007);
        eq("raw edit without generation bump", run_from(p, fresh()).r[0], 9);
    }
    for (unsigned i = 0; i < 3; i++) ST32(p + i * 4, 0xe2800001);
    ST32(target, 0xe2800002); ST32(target + 4, BX_LR);
    eq("warm actual final branch", run_from(p, fresh()).r[0], 3);
    eq("warm actual final branch again", run_from(p, fresh()).r[0], 3);
    ST32(p + 12, branch(p + 12, target, 0));
    eq("raw edit actual last op", run_from(p, fresh()).r[0], 5);
    ST32(p, branch(p, target, 0)); ST32(p + 4, 0xffffffff);
    ST32(target, 0xe2800002); ST32(target + 4, BX_LR);
    for (unsigned i = 0; i < 3; i++) eq("linked warm", run_from(p, fresh()).r[0], 2);
    ST32(target, 0xe2800009); eq("linked target raw edit", run_from(p, fresh()).r[0], 9);
    ST32(p, branch(p, target, 0) & 0x0fffffff);
    ST32(p + 4, 0xe2800003); ST32(p + 8, BX_LR);
    for (unsigned i = 0; i < 6; i++) {
        Cpu c = fresh(); c.zf = i & 1; eq("two linked successors", run_from(p, c).r[0], c.zf ? 9 : 3);
    }
    phase = "in-block self modification / both end-shape transitions";
    p = CODE + 0x3000; interp_add_range(p, p + 0x100);
    ST32(p, 0xe5812000); ST32(p + 4, 0xe2800001);
    ST32(p + 8, 0xe2800002); ST32(p + 12, BX_LR);
    Cpu c = fresh(); c.r[1] = p + 4; c.r[2] = branch(p + 4, p + 12, 0);
    eq("nonbranch replaced by branch", run_from(p, c).r[0], 0);
    /* Force a fresh entry block containing the current branch before replacing it. */
    interp_code_changed();
    c.r[2] = 0xe2800007; eq("branch replaced by nonbranch", run_from(p, c).r[0], 9);
    phase = "metadata-only kept words / generation / hook disable";
    p = LOW; interp_add_range(p, p + 12); kept_pc = p; keep_on = 1;
    kept[0] = 0xe2800001; kept[1] = 0xe2800002;
    ST32(p, 0xe51ff004); ST32(p + 4, RET); ST32(p + 8, BX_LR);
    g_fnhook[p >> 5] |= 1u << ((p >> 2) & 7); interp_code_changed();
    eq("kept warm", run_from(p, fresh()).r[0], 3);
    eq("kept warm again", run_from(p, fresh()).r[0], 3);
    kept[0] = 0xe2800004; interp_code_changed();
    eq("first kept word only", run_from(p, fresh()).r[0], 6);
    kept[1] = 0xe2800008; interp_code_changed();
    eq("second kept word only", run_from(p, fresh()).r[0], 12);
    eq("raw first preserved", LD32(p), 0xe51ff004); eq("raw second preserved", LD32(p + 4), RET);
    g_fnhook[p >> 5] = 0; keep_on = 0; interp_code_changed();
    eq("disabled hook raw jump", run_from(p, fresh()).r[0], 0);
}
static void build_big(void) {
    /* 4096 * 32 decoded ops exceeds upstream's 2 MiB arena, no private ABI. */
    for (unsigned k = 0; k < BIG_BLOCKS; k++) {
        uint32_t p = BIG + k * 128;
        for (unsigned i = 0; i < 31; i++) ST32(p + i * 4, 0xe2800001);
        ST32(p + 124, k + 1 == BIG_BLOCKS ? BX_LR : branch(p + 124, p + 128, 0));
    }
    interp_add_range(BIG, BIG + BIG_BLOCKS * 128);
}
void rt_svc(Cpu *c, uint32_t imm, uint32_t pc) {
    (void)pc; if (callback_mode != 1 || imm != 0x42) unexpected("svc");
    callbacks++; Cpu nested = run_from(BIG, fresh());
    eq("recursive arena traversal", nested.r[0], BIG_BLOCKS * 31);
    c->r[3] = nested.r[0]; interp_code_changed();
}
void rt_dispatch(Cpu *c) {
    if (callback_mode != 2 || c->pc != CALLOUT) unexpected("dispatch");
    callbacks++; Cpu nested = run_from(BIG, fresh());
    eq("dispatch recursive arena traversal", nested.r[0], BIG_BLOCKS * 31);
    c->r[3] = nested.r[0]; interp_code_changed();
}
static void test_cache_structure(void) {
    phase = ">32 instructions / direct-map collision / arena rollover";
    uint32_t p = CODE + 0x6000;
    for (unsigned i = 0; i < 80; i++) ST32(p + 4 * i, 0xe2800001);
    ST32(p + 320, BX_LR); interp_add_range(p, p + 324);
    for (unsigned i = 0; i < 3; i++) eq("80 instructions", run_from(p, fresh()).r[0], 80);
    uint32_t a = CODE + 0x8000, b = a + 0x4000;
    ST32(a, 0xe2800003); ST32(a + 4, BX_LR); ST32(b, 0xe2800007); ST32(b + 4, BX_LR);
    interp_add_range(a, a + 8); interp_add_range(b, b + 8);
    for (unsigned i = 0; i < 10; i++) {
        eq("collision A", run_from(a, fresh()).r[0], 3); eq("collision B", run_from(b, fresh()).r[0], 7);
    }
    build_big();
    for (unsigned i = 0; i < 2; i++) eq("arena traversal", run_from(BIG, fresh()).r[0], BIG_BLOCKS * 31);
    phase = "reentrant SVC / dispatch / arena reset / generation";
    p = CODE + 0xe000;
    ST32(p, 0xe2800001); ST32(p + 4, 0xef000042); ST32(p + 8, 0xe2800007); ST32(p + 12, BX_LR);
    interp_add_range(p, p + 32); callback_mode = 1;
    Cpu got = run_from(p, fresh());
    eq("outer SVC resume", got.r[0], 8); eq("nested result", got.r[3], BIG_BLOCKS * 31);
    eq("SVC count", callbacks, 1);
    callback_mode = 2; callbacks = 0;
    ST32(p, 0xe1a0400e); ST32(p + 4, branch(p + 4, CALLOUT, 1));
    ST32(p + 8, 0xe2800007); ST32(p + 12, 0xe12fff14);
    got = run_from(p, fresh());
    eq("outer dispatch resume", got.r[0], 7); eq("dispatch count", callbacks, 1);
    eq("dispatch nested result", got.r[3], BIG_BLOCKS * 31); callback_mode = 0;
}
static pthread_barrier_t barrier;
static uint32_t thread_entry;
static void sync_threads(void) {
    int r = pthread_barrier_wait(&barrier);
    if (r && r != PTHREAD_BARRIER_SERIAL_THREAD) unexpected("pthread barrier");
}
static void *thread_run(void *unused) {
    (void)unused; /* Do not touch shared assertion counters in worker threads. */
    Cpu a = fresh(); a.pc = thread_entry; interp_run(&a);
    if (a.r[0] != 1) unexpected("thread warm answer");
    sync_threads(); sync_threads();
    a = fresh(); a.pc = thread_entry; interp_run(&a);
    if (a.r[0] != 9) unexpected("thread post-generation answer");
    return NULL;
}
static void test_threads_watch_diagnostics(void) {
    phase = "two thread-local caches / metadata-only serialized publication";
    thread_entry = LOW + 0x100;
    kept_pc = thread_entry; keep_on = 1;
    kept[0] = 0xe2800001; kept[1] = BX_LR;
    ST32(thread_entry, 0xe51ff004); ST32(thread_entry + 4, RET);
    g_fnhook[thread_entry >> 5] = 1u << ((thread_entry >> 2) & 7);
    interp_code_changed();
    interp_add_range(thread_entry, thread_entry + 8);
    /* Prime the upstream shared owns_last hint before workers use this one range. */
    eq("thread range owns entry", interp_owns(thread_entry), 1);
    pthread_t threads[2];
    if (pthread_barrier_init(&barrier, NULL, 3)) unexpected("barrier init");
    for (unsigned i = 0; i < 2; i++)
        if (pthread_create(&threads[i], NULL, thread_run, NULL)) unexpected("pthread_create");
    sync_threads(); kept[0] = 0xe2800009; interp_code_changed(); sync_threads();
    for (unsigned i = 0; i < 2; i++)
        if (pthread_join(threads[i], NULL)) unexpected("pthread_join");
    pthread_barrier_destroy(&barrier);
    eq("thread metadata left raw patch fixed", LD32(thread_entry), 0xe51ff004);
    g_fnhook[thread_entry >> 5] = 0; keep_on = 0; interp_code_changed();
    phase = "benign mapped write/read watched fallback";
    uint32_t p = CODE + 0x10000;
    ST32(p, 0xe5910000); ST32(p + 4, 0xe2800001); ST32(p + 8, 0xe5810000); ST32(p + 12, BX_LR);
    interp_add_range(p, p + 16); Cpu in = fresh(); in.r[1] = DATA + 64;
    ST32(DATA + 64, 41); Cpu normal = run_from(p, in); eq("normal store", LD32(DATA + 64), 42);
    ST32(DATA + 64, 41); interp_watch(DATA + 64, 1); interp_read_watch(DATA + 64, DATA + 68);
    Cpu watched = run_from(p, in); interp_watch(0, 0); interp_read_watch(0, 0);
    arch_eq(&normal, &watched); eq("watched store", LD32(DATA + 64), 42);
    phase = "fail-fast Thumb / unsupported instruction diagnostics";
    fprintf(stderr, "[fixture] expecting two unsupported-coprocessor diagnostics below\n");
    for (unsigned path = 0; path < 2; path++)
        for (unsigned op = 0; op < 2; op++) {
            pid_t child = fork(); if (child < 0) unexpected("fork");
            if (!child) {
                diagnostic = path ? 73 : 71; Cpu c = fresh(); c.r[2] = CODE | 1; int link;
                uint32_t word = path ? 0xee000010 : 0xe12fff12;
                if (op) interp_exec_op(&c, CODE, word, &link); else interp_exec(&c, CODE, word, &link);
                _Exit(99);
            }
            int status; if (waitpid(child, &status, 0) != child) unexpected("waitpid");
            eq("diagnostic exited", WIFEXITED(status), 1);
            eq("diagnostic selected", WEXITSTATUS(status), path ? 73 : 71);
        }
}
int main(void) {
    unsetenv("MHGU_INTERP_STATS");
    map_guest(CODE, 0x20000); map_guest(LOW, 0x10000); map_guest(DATA, 0x10000); map_guest(BIG, 0x100000);
    test_integer(); test_predication(); test_memory(); test_branches_fallback();
    test_cache_edits(); test_cache_structure(); test_threads_watch_diagnostics();
    printf("public synthetic interpreter: PASS (%u single-op cases, %u architectural/memory checks)\n", steps, checks);
    return 0;
}
