#include "test_0160_fixture.h"
#include "../runtime/hle/itembar.c" /* ACTUAL, byte-exact upstream production source */

enum { PLAYER = 0x08000000u, VTABLE = 0x00200000u, CAN_SELECT = 0x00400000u };
static unsigned char heap[0x4000], vtable[0x1000];
static Cpu cpu;
static uint64_t now;
static uint32_t is_local, is_busy, selectable;
static bool prowler_mode, original_changes_slot;
static unsigned originals, next_calls;
static uint32_t last_dir, last_slot, last_next;
static uint32_t original_regs[16];
uint64_t plat_now_ns(void) { return now; }
void fnhook_call_original(Cpu *c, uint32_t fn) {
    assert(fn == FN_ITEM_BAR || fn == FN_PROWLER_BAR);
    assert(nevents == 0); /* original FIRST, even when all wheel work is gated */
    record(c, fn); ++originals;
    if (original_changes_slot) ST16(PLAYER + (prowler_mode ? OT_ITEM_SLOT : PL_ITEM_SLOT), 17);
    /* Hook must use pre-original player but preserve post-original registers. */
    for (unsigned i = 0; i < 16; ++i) c->r[i] = 0xcafe0000u + i;
    memcpy(original_regs, c->r, sizeof original_regs);
}
void guest_call(Cpu *c, uint32_t fn) {
    assert(originals > 0 && nevents > 0);
    assert(c->r[0] == PLAYER);
    record(c, fn);
    uint32_t result;
    switch (fn) {
    case FN_PL_IS_LOCAL: result = is_local; break;
    case FN_PL_BUSY: assert(!prowler_mode); result = is_busy; break;
    case CAN_SELECT:
        assert(c->r[1] == (prowler_mode ? 0x10u : 1u)); result = selectable; break;
    case FN_ITEM_NEXT: case FN_PROWLER_NEXT:
        assert(fn == (prowler_mode ? FN_PROWLER_NEXT : FN_ITEM_NEXT));
        last_dir = c->r[2]; last_slot = c->r[1]; last_next = fn;
        assert(last_dir <= 1); ++next_calls;
        /* Synthetic selection result: NOT validation of game pouch skipping /
         * Prowler 0..8 wrapping. Host's forwarding and writeback are real. */
        result = last_dir ? 0x28 : 7;
        break;
    default: abort();
    }
    for (unsigned i = 0; i < 16; ++i) c->r[i] = 0xbad00000u + i;
    c->r[0] = result;
}
static void reset(bool prowler) {
    memset(heap, 0, sizeof heap); memset(vtable, 0, sizeof vtable);
    g_steps = 0; g_seen_ns = 0; now = 1000000000ull;
    is_local = selectable = 1; is_busy = 0; prowler_mode = prowler;
    original_changes_slot = false; originals = next_calls = 0; nevents = 0;
    ST32(PLAYER, VTABLE); ST32(VTABLE + VF_CAN_SELECT, CAN_SELECT);
    ST32(VTABLE + VF_PROWLER_BAR, prowler ? FN_PROWLER_BAR : 0);
    ST16(PLAYER + PL_ITEM_SLOT, 3); ST32(PLAYER + PL_ITEM_FLAGS, 0x80);
    ST16(PLAYER + OT_ITEM_SLOT, 5); ST32(PLAYER + OT_ITEM_FLAGS, 0x100);
    init_cpu(&cpu); cpu.r[0] = PLAYER;
}
static void invoke(bool prowler, uint32_t player) {
    nevents = 0; cpu.r[0] = player;
    (prowler ? prowler_bar : item_bar)(&cpu);
    assert(memcmp(original_regs, cpu.r, sizeof original_regs) == 0);
}
static void prime(bool prowler) {
    invoke(prowler, PLAYER); assert(next_calls == 0 && g_seen_ns == now);
}
static void queue_and_clamp(void) {
    reset(false); itembar_scroll(2); assert(g_steps == 0);
    prime(false); itembar_scroll(0); assert(g_steps == 0);
    itembar_scroll(3); itembar_scroll(3); assert(g_steps == 4);
    itembar_scroll(-2); assert(g_steps == 2);
    itembar_scroll(-100); assert(g_steps == -4);
    itembar_scroll(100); assert(g_steps == 4);
    /* Boundary: equality expires; one ns younger is accepted. */
    now += ACTIVE_NS - 1; itembar_scroll(-1); assert(g_steps == 3);
    now += 1; itembar_scroll(-2); assert(g_steps == 3);
    invoke(false, PLAYER); assert(g_steps == 0 && next_calls == 0);
    itembar_scroll(1); invoke(false, PLAYER); assert(next_calls == 1 && g_steps == 0);
    now += ACTIVE_NS + 1; itembar_scroll(1); invoke(false, PLAYER);
    assert(next_calls == 1 && g_steps == 0);
}
static void turns(bool prowler, int sign) {
    reset(prowler); prime(prowler); itembar_scroll(sign * 20); assert(g_steps == sign * 4);
    original_changes_slot = true;
    for (unsigned i = 0; i < 4; ++i) {
        ++now; invoke(prowler, PLAYER);
        assert(next_calls == i + 1 && g_steps == sign * (3 - (int)i));
        assert(last_slot == 17 && last_dir == (sign > 0 ? 0u : 1u));
        uint32_t offset = prowler ? OT_ITEM_SLOT : PL_ITEM_SLOT;
        uint32_t flags = prowler ? OT_ITEM_FLAGS : PL_ITEM_FLAGS;
        assert(LD16(PLAYER + offset) == (sign > 0 ? 7u : 0x28u));
        assert(LD32(PLAYER + flags) == ((prowler ? 0x100u : 0x80u) | (sign > 0 ? 2u : 4u)));
        assert(LD16(PLAYER + (prowler ? PL_ITEM_SLOT : OT_ITEM_SLOT)) == (prowler ? 3u : 5u));
        assert(LD32(PLAYER + (prowler ? PL_ITEM_FLAGS : OT_ITEM_FLAGS)) == (prowler ? 0x80u : 0x100u));
        assert(nevents == (prowler ? 4u : 5u));
        assert(events[0].fn == (prowler ? FN_PROWLER_BAR : FN_ITEM_BAR));
        assert(events[1].fn == FN_PL_IS_LOCAL);
        if (!prowler) assert(events[2].fn == FN_PL_BUSY);
        assert(events[nevents - 2].fn == CAN_SELECT && events[nevents - 1].fn == last_next);
    }
    invoke(prowler, PLAYER); assert(next_calls == 4 && nevents == 1);
}
static void modes_and_gates(void) {
    for (unsigned prowler = 0; prowler < 2; ++prowler) {
        for (unsigned gate = 0; gate < 5; ++gate) {
            reset(prowler); prime(prowler); itembar_scroll(3);
            switch (gate) {
            case 0: selectable = 0; break;
            case 1: selectable = 2; break; /* exactly 1 required */
            case 2: ST32(VTABLE + VF_CAN_SELECT, 0); break;
            case 3: ST32(PLAYER, 0); break;
            case 4: is_busy = 1; break;
            }
            invoke(prowler, PLAYER);
            if (gate == 4 && prowler) { assert(next_calls == 1 && g_steps == 2); }
            else {
                assert(next_calls == 0 && g_steps == 0);
                selectable = 1; is_busy = 0; ST32(PLAYER, VTABLE);
                ST32(VTABLE + VF_CAN_SELECT, CAN_SELECT);
                invoke(prowler, PLAYER); assert(next_calls == 0); /* queue was dropped */
            }
        }
        reset(prowler); prime(prowler); itembar_scroll(2);
        is_local = 0; invoke(prowler, PLAYER);
        assert(next_calls == 0 && g_steps == 2); /* remote handler retains queue */
        is_local = 2; invoke(prowler, PLAYER); assert(next_calls == 0 && g_steps == 2);
        is_local = 1; invoke(prowler, PLAYER); assert(next_calls == 1 && g_steps == 1);
    }
    /* Hunter's hook on Prowler: original runs, but no queue consumption or
     * liveness refresh. Prowler's following hook owns that notch. */
    reset(true); prime(true); itembar_scroll(2); uint64_t seen = g_seen_ns;
    ++now; invoke(false, PLAYER);
    assert(nevents == 1 && g_steps == 2 && g_seen_ns == seen && next_calls == 0);
    invoke(true, PLAYER); assert(next_calls == 1 && g_steps == 1);
}
static void validity(void) {
    uint32_t invalid[] = {0, 0x07fffffcu, PLAYER + 1, 0xf0000000u, 0xfffffffcu};
    for (unsigned prowler = 0; prowler < 2; ++prowler)
        for (size_t i = 0; i < sizeof invalid / sizeof *invalid; ++i) {
            reset(prowler); prime(prowler); itembar_scroll(1);
            invoke(prowler, invalid[i]);
            assert(next_calls == 0 && g_steps == 1 && nevents == 1);
            invoke(prowler, PLAYER); assert(next_calls == 1 && g_steps == 0);
        }
    assert(sane(PLAYER) && sane(0xeffffffcu) && !sane(0xf0000000u));
    /* Numeric sane is deliberately not a mapped-memory predicate. No attempt
     * to pretend all aligned 0x08..0xef guest addresses are backed. */
}
int main(int argc, char **argv) {
    region(PLAYER, heap, sizeof heap); region(VTABLE, vtable, sizeof vtable);
    if (argc == 2 && !strcmp(argv[1], "--red-step-overflow")) {
        reset(false); prime(false); itembar_scroll(1); itembar_scroll(INT_MAX);
        /* UBSan must fail before the later clamp can execute. */
        assert(g_steps == MAX_WAITING); return 0;
    }
    assert(argc == 1);
    nregistered = nhooked = 0; itembar_init();
    assert(nregistered == 2 && nhooked == 2);
    assert(registered[0] == item_bar && registered[1] == prowler_bar);
    assert(hooked[0] == FN_ITEM_BAR && hooked[1] == FN_PROWLER_BAR);
    assert(detours[0] == 0x03000010u && detours[1] == 0x03000020u);
    queue_and_clamp();
    turns(false, 1); turns(false, -1); turns(true, 1); turns(true, -1);
    modes_and_gates(); validity();
    puts("PASS itembar: hunter/prowler modes, signs/repeats/clamp/consume, age/gates/validity, original-first and register restore");
    return 0;
}
