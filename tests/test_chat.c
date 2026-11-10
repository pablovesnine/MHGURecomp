#include "test_0160_fixture.h"
#include "../runtime/hle/chat.c" /* ACTUAL, byte-exact upstream production source */

enum { PLAYER = 0x08000000u, DATA = 0x08002000u, STACK = 0x0a000000u,
       MESSAGE = 0x08004000u, NET = 0x08005000u, OBJECT = 0x08006000u };
static unsigned char globals[0x2000], depth[4], heap[0x7000], stack[0x1000];
static Cpu cpu;
static bool ti_active;
static char ti_text[512], initial[32];
static int ti_max, ti_event, begin_count, end_count;
static int32_t net_index = 2;
static uint32_t online = 1, object = OBJECT, me = PLAYER;
static char sent[32][TEXT_BYTES];
static size_t nsent;
static uint8_t expected_original_name;
static unsigned original_count;

/* Text-entry stub: bounded snapshots and events, valid UTF-8 supplied by tests.
 * MAX_CHARS negotiation is asserted; real textinput_type character filtering /
 * SDL clipboard and event code are not linked or claimed tested here. */
void textinput_begin(const char *s, int max) {
    assert(!chat_active()); /* entry must exist before composing is published */
    snprintf(initial, sizeof initial, "%s", s);
    snprintf(ti_text, sizeof ti_text, "%s", s);
    ti_max = max; ti_active = true; ti_event = TI_NONE; ++begin_count;
}
void textinput_end(void) { ti_active = false; ti_event = TI_NONE; ++end_count; }
bool textinput_active(void) { return ti_active; }
void textinput_peek(char *out, size_t size) { snprintf(out, size, "%s", ti_text); }
int textinput_poll(char *out, size_t size, int *chars) {
    snprintf(out, size, "%s", ti_text);
    int n = 0;
    for (const unsigned char *s = (const unsigned char *)ti_text; *s; ++s)
        if ((*s & 0xc0) != 0x80) ++n;
    *chars = n;
    int e = ti_event; ti_event = TI_NONE; return e;
}
void guest_call(Cpu *c, uint32_t fn) {
    record(c, fn);
    switch (fn) {
    case FN_NET_INDEX: assert(c->r[0] == NET); c->r[0] = (uint32_t)net_index; break;
    case FN_NET_ONLINE: assert(c->r[0] == NET); c->r[0] = online; break;
    case FN_NET_OBJECT: assert(c->r[0] == NET && c->r[1] == 0x6b); c->r[0] = object; break;
    case FN_MY_PLAYER: assert(c->r[0] == PLAYER); c->r[0] = me; break;
    case FN_SEND_CHAT: {
        assert(nsent < 32 && c->r[0] == OBJECT);
        assert(c->r[1] == CHAT_TYPE + (online ? (uint32_t)net_index : 0));
        assert(c->r[2] == DATA + 0x514 && !(c->r[13] & 7));
        assert(LD32(c->r[13]) == 1 && c->r[3] == c->r[13] + 0x10);
        const char *s = guest_ptr(c->r[3], TEXT_BYTES);
        size_t len = strnlen(s, TEXT_BYTES);
        assert(len < TEXT_BYTES);
        memcpy(sent[nsent++], s, TEXT_BYTES);
        for (size_t j = len; j < TEXT_BYTES; ++j) assert(s[j] == 0);
        assert(LD8(c->r[3] - 1) == 0xa5 && LD8(c->r[3] + TEXT_BYTES) == 0xa5);
        c->r[0] = 0x1234;
        break;
    }
    default: abort();
    }
    /* Emulate caller-saved clobbering; send_text must restore all 16 regs. */
    c->r[1] = 0xbad1; c->r[2] = 0xbad2; c->r[3] = 0xbad3;
}
void fnhook_call_original(Cpu *c, uint32_t fn) {
    assert(fn == FN_RECEIVE);
    assert(LD8(c->r[1] + MSG_NAME) == expected_original_name);
    ++original_count;
    c->r[0] = 0xfeed; /* return value must survive the hook */
}
static void reset(void) {
    atomic_store(&g_composing, false);
    ti_active = false; ti_event = TI_NONE; ti_text[0] = 0;
    begin_count = end_count = 0; nsent = nevents = 0;
    net_index = 2; online = 1; object = OBJECT; me = PLAYER;
    memset(stack, 0xa5, sizeof stack);
    memset(heap, 0, sizeof heap);
    memset(globals, 0, sizeof globals); memset(depth, 0, sizeof depth);
    ST32(G_SNETWORK, NET); ST32(G_SPLAYER, PLAYER); ST32(PLAYER + 0x13c4, DATA);
    init_cpu(&cpu); cpu.r[13] = STACK + 0xf03; /* verify real alignment */
}
static void submit(const char *s) {
    chat_open();
    assert(ti_max == 120 && initial[0] == 0);
    assert(strlen(s) < sizeof ti_text);
    snprintf(ti_text, sizeof ti_text, "%s", s);
    ti_event = TI_ENTER;
    uint32_t regs[16]; memcpy(regs, cpu.r, sizeof regs);
    chat_tick(&cpu);
    assert(!chat_active() && !ti_active && end_count == 1);
    assert(memcmp(regs, cpu.r, sizeof regs) == 0);
    for (size_t i = 0; i < nsent; ++i) {
        assert(strlen(sent[i]) <= 119);
        unsigned rows = 1, width = 0;
        for (const char *p = sent[i]; *p;) {
            if (*p == '\n') { assert(width <= 40); ++rows; width = 0; ++p; }
            else { int k = utf8_len(p); width += k >= 3 ? 2 : 1; p += k; }
        }
        assert(rows <= 5 && width <= 40);
    }
    if (nsent) {
        assert(nevents == 5 * nsent);
        for (size_t i = 0; i < nsent; ++i) {
            uint32_t sequence[] = {FN_NET_INDEX, FN_NET_ONLINE, FN_NET_OBJECT, FN_MY_PLAYER, FN_SEND_CHAT};
            for (size_t j = 0; j < 5; ++j) assert(events[i * 5 + j].fn == sequence[j]);
        }
    }
}
static void repeat(char *out, const char *unit, unsigned n) {
    size_t k = strlen(unit);
    for (unsigned i = 0; i < n; ++i) memcpy(out + i * k, unit, k);
    out[n * k] = 0;
}
static void assert_payload_without_wraps(const char *input) {
    char joined[512]; size_t n = 0;
    for (size_t i = 0; i < nsent; ++i)
        for (const char *p = sent[i]; *p; ++p) if (*p != '\n') joined[n++] = *p;
    joined[n] = 0; assert(strcmp(joined, input) == 0);
}
static void lifecycle(void) {
    reset(); assert(!chat_composing(NULL, 0));
    chat_open(); chat_open(); assert(begin_count == 1 && chat_active());
    strcpy(ti_text, "draft"); ti_event = TI_CHANGED;
    struct { char before; char text[3]; char after; } b = {'L', "", 'R'};
    assert(chat_composing(b.text, sizeof b.text) && !strcmp(b.text, "dr"));
    assert(b.before == 'L' && b.after == 'R');
    char one = 'X'; assert(chat_composing(&one, 1) && one == 0);
    char untouched = 'Z'; assert(chat_composing(&untouched, 0) && untouched == 'Z');
    chat_tick(&cpu); chat_tick(&cpu); assert(nsent == 0 && end_count == 0 && chat_active());
    ti_event = TI_CANCEL; chat_tick(&cpu);
    assert(!chat_active() && !ti_active && nsent == 0 && end_count == 1);
    chat_open(); assert(begin_count == 2 && ti_text[0] == 0);
    ti_active = false; chat_tick(&cpu); assert(!chat_active() && end_count == 1);
    chat_open(); chat_close(); assert(!chat_active() && ti_active);
    chat_tick(&cpu); assert(end_count == 1); /* close is NOT textinput_end */
}
static void lengths_and_unicode(void) {
    unsigned lengths[] = {0, 1, 26, 39, 40, 41, 79, 80, 81, 117, 118, 119, 120};
    char s[512];
    for (size_t i = 0; i < sizeof lengths / sizeof *lengths; ++i) {
        unsigned n = lengths[i]; repeat(s, "a", n); reset(); submit(s);
        assert(nsent == (n == 0 ? 0 : n <= 117 ? 1 : 2));
        assert_payload_without_wraps(s);
        if (n == 117) assert(strlen(sent[0]) == 119);
        if (n >= 118) assert(strlen(sent[0]) == 81 && strlen(sent[1]) == n - 80);
    }
    const char *units[] = {"\xc3\xa9", "\xe3\x81\x82", "\xf0\x9f\x98\x80"};
    for (unsigned u = 0; u < 3; ++u) {
        repeat(s, units[u], 120); reset(); submit(s);
        assert(nsent == (u == 0 ? 3 : 6));
        for (size_t i = 0; i < nsent; ++i) assert(strlen(sent[i]) == (u == 1 ? 60 : 80));
        assert_payload_without_wraps(s);
    }
    /* UTF-8 boundary at a width limit; no continuation byte split. */
    repeat(s, "a", 39); strcat(s, "\xe3\x81\x82"); reset(); submit(s);
    assert(nsent == 1 && strlen(sent[0]) == 43 && sent[0][39] == '\n');
    reset(); submit("   hello world   "); assert(nsent == 1 && !strcmp(sent[0], "hello world"));
    reset(); submit("      "); assert(nsent == 0);
    /* Five rows within the actual 120-codepoint entry limit: 5 words of 20. */
    char expected[128]; size_t p = 0;
    for (unsigned i = 0; i < 5; ++i) {
        if (i) { s[p] = ' '; expected[p++] = '\n'; }
        memset(s + p, 'b', 20); memset(expected + p, 'b', 20); p += 20;
    }
    s[p] = expected[p] = 0; reset(); submit(s);
    assert(nsent == 1 && !strcmp(sent[0], expected));
    const char *rest;
    assert(next_piece("one two three", &rest) == 13 && !*rest);
    repeat(s, "x", 30); strcat(s, " abcdefghijk");
    assert(next_piece(s, &rest) == 30 && !strcmp(rest, "abcdefghijk"));
}
static void network_gates(void) {
    for (unsigned which = 0; which < 6; ++which) {
        reset();
        switch (which) {
        case 0: ST32(G_SNETWORK, 0); break;
        case 1: ST32(G_SPLAYER, 0); break;
        case 2: object = 0; break;
        case 3: me = 0; break;
        case 4: ST32(PLAYER + 0x13c4, 0); break;
        case 5: net_index = -1; break;
        }
        submit("not sent"); assert(nsent == 0);
        assert(nevents == (which < 2 ? 0 : which == 5 ? 3 : 4));
        if (which == 5) {
            assert(events[0].fn == FN_NET_INDEX && events[1].fn == FN_NET_ONLINE &&
                   events[2].fn == FN_MY_PLAYER);
        }
    }
    reset(); online = 0; net_index = -1; submit("offline"); assert(nsent == 1);
}
static void receiver(void) {
    reset(); nregistered = nhooked = 0; chat_init();
    assert(nregistered == 1 && nhooked == 1 && registered[0] == receive_message);
    assert(hooked[0] == FN_RECEIVE && detours[0] == 0x03000010u);
    unsigned depths[] = {0, 1, 5, 127, 128, 255};
    for (unsigned type = 0; type < 12; ++type)
        for (unsigned d = 0; d < sizeof depths / sizeof *depths; ++d) {
            cpu.r[1] = MESSAGE; ST8(MESSAGE + MSG_TYPE, type); ST8(MESSAGE + MSG_NAME, 'N');
            ST8(MESSAGE + MSG_NAME + 1, 'x'); ST8(G_RECEIVE_DEPTH, depths[d]);
            bool suppress = depths[d] > 0 && depths[d] < 128 && type >= 6 && type < 10;
            expected_original_name = suppress ? 0 : 'N';
            unsigned before = original_count; registered[0](&cpu);
            assert(original_count == before + 1 && cpu.r[0] == 0xfeed);
            assert(LD8(MESSAGE + MSG_NAME) == 'N' && LD8(MESSAGE + MSG_NAME + 1) == 'x');
            assert(LD8(MESSAGE + MSG_TYPE) == type && LD8(G_RECEIVE_DEPTH) == depths[d]);
        }
}
int main(int argc, char **argv) {
    region(0x01a84000u, globals, sizeof globals);
    region(G_RECEIVE_DEPTH, depth, sizeof depth);
    region(PLAYER, heap, sizeof heap); region(STACK, stack, sizeof stack);
    if (argc == 2 && !strcmp(argv[1], "--red-truncated-utf8")) {
        const char *rest; char truncated[2] = {(char)0xc2, 0};
        /* ASan must fail: production next_piece skips beyond this NUL. */
        (void)next_piece(truncated, &rest);
        return 0;
    }
    assert(argc == 1);
    lifecycle(); lengths_and_unicode(); network_gates(); receiver();
    puts("PASS chat: lifecycle, 120-codepoint request, byte/width/row bounds, Unicode, send/order/restore, receive prefix");
    return 0;
}
