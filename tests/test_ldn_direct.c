// Public synthetic direct-UDP regression for upstream 0.15.3.
// Real runtime/net/ldn.c, but NO sockets, listeners, DNS or background threads.
// State/protocol coverage only: not evidence of NAT traversal or actual game play.
//
// Linux: clang -std=gnu11 -O1 -g -fsigned-char -ffunction-sections \
//   -fdata-sections -Iruntime -I<declaration-stubs> tests/test_ldn_direct.c -Wl,--gc-sections \
//   -pthread -o test_ldn_direct
// ./test_ldn_direct && ./test_ldn_direct --blocked
// Sanitizers: add -fsanitize=address,undefined -fno-omit-frame-pointer.
// For a different source worktree, define MHGU_LDN_SOURCE to its quoted absolute
// runtime/net/ldn.c path and use its runtime include directory. All link stubs are here.
// overlay.h also needs graphics declarations: use installed headers or tiny
// generated SDL3/SDL.h (SDL_Event forward declaration) and vulkan/vulkan.h (seven
// opaque Vk handles). No graphics code or libraries are linked.
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#include "config.h"
#include "hle.h"

#define CHECK(c) do { if (!(c)) { \
    fprintf(stderr, "test-ldn-direct:%d: check failed: %s\n", __LINE__, #c); exit(1); \
} } while (0)
static _Noreturn void unexpected(const char *name) {
    fprintf(stderr, "test-ldn-direct: forbidden service: %s\n", name);
    exit(1);
}
enum { UDP_FD = 40, TCP_FD = 41, LISTEN_FD = 42, CAPACITY = 128, WIRE_MAX = 16384 };
typedef struct {
    struct sockaddr_in addr;
    uint8_t bytes[WIRE_MAX];
    size_t size;
    bool failed;
} Datagram;
static Datagram sent[CAPACITY], incoming[CAPACITY];
static unsigned sent_n, incoming_n, incoming_i, receive_calls, sleep_calls, timeout_calls;
static unsigned fail_udp_mask, tcp_calls, delivered, logs;
static uint8_t tcp_bytes[65536], delivered_data[WIRE_MAX];
static size_t tcp_n, tcp_chunk, delivered_n;
static uint64_t now_ns = 100000000000ull;
static const char *block_setting;
static bool host_loop;
static unsigned select_calls;
static ssize_t synthetic_sendto(int, const void *, size_t, int, const struct sockaddr *, socklen_t);
static ssize_t synthetic_recvfrom(int, void *, size_t, int, struct sockaddr *, socklen_t *);
static ssize_t synthetic_send(int, const void *, size_t, int);
static int synthetic_setsockopt(int, int, int, const void *, socklen_t);
static int synthetic_select(int, fd_set *, fd_set *, fd_set *, struct timeval *);
static char *synthetic_getenv(const char *);
static void synthetic_log(const char *, ...);

// Fail closed if a future runtime change accidentally reaches setup code.
// Headers are preloaded; function-like macros do not rename struct members.
#define socket(...) (unexpected("socket"), -1)
#define bind(...) (unexpected("bind"), -1)
#define listen(...) (unexpected("listen"), -1)
#define accept(...) (unexpected("accept"), -1)
#define connect(...) (unexpected("connect"), -1)
#define recv(...) (unexpected("recv"), (ssize_t)-1)
#define select synthetic_select
#define shutdown(...) (unexpected("shutdown"), -1)
#define close(...) (unexpected("close"), -1)
#define fcntl(...) (unexpected("fcntl"), -1)
#define getsockopt(...) (unexpected("getsockopt"), -1)
#define getaddrinfo(...) (unexpected("getaddrinfo"), EAI_FAIL)
#define freeaddrinfo(...) unexpected("freeaddrinfo")
#define pthread_create(...) (unexpected("pthread_create"), -1)
#define arc4random(...) (unexpected("arc4random"), 0u)
#define sendto synthetic_sendto
#define recvfrom synthetic_recvfrom
#define send synthetic_send
#define setsockopt synthetic_setsockopt
#define getenv synthetic_getenv
#undef LOG
#define LOG(...) synthetic_log(__VA_ARGS__)
#ifndef MHGU_LDN_SOURCE
#define MHGU_LDN_SOURCE "../runtime/net/ldn.c"
#endif
#include MHGU_LDN_SOURCE
#undef socket
#undef bind
#undef listen
#undef accept
#undef connect
#undef recv
#undef select
#undef shutdown
#undef close
#undef fcntl
#undef getsockopt
#undef getaddrinfo
#undef freeaddrinfo
#undef pthread_create
#undef arc4random
#undef sendto
#undef recvfrom
#undef send
#undef setsockopt
#undef getenv

static VPacket delivered_packet;
static const uint8_t message[] = {0x00, 0x7f, 0x80, 0xff, 'U', 'D', 'P'};
uint64_t plat_now_ns(void) { return now_ns; }
void plat_sleep_until_ns(uint64_t until) {
    CHECK(until >= now_ns && until - now_ns <= 5000000ull);
    sleep_calls++;
    now_ns = until;
}
void vsock_deliver(const VPacket *p, const void *data, uint32_t n) {
    CHECK(n <= sizeof delivered_data);
    delivered++;
    delivered_packet = *p;
    delivered_n = n;
    memcpy(delivered_data, data, n);
}
void ryu_send(const RyuProxy *p, const void *data, uint32_t n) {
    (void)p; (void)data; (void)n; unexpected("ryu_send");
}
void room_send_proxy(const uint8_t src[4], uint16_t sport, const uint8_t dst[4], uint16_t dport,
                     uint8_t proto, bool broadcast, const void *data, uint32_t n) {
    (void)src; (void)sport; (void)dst; (void)dport; (void)proto;
    (void)broadcast; (void)data; (void)n; unexpected("room_send_proxy");
}
static char *synthetic_getenv(const char *name) {
    if (!strcmp(name, "MHGU_LDN_BLOCK_DIRECT")) return (char *)block_setting;
    // Do not inherit host RTT / lag / loss settings.
    return NULL;
}
static void synthetic_log(const char *fmt, ...) {
    char text[2048];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(text, sizeof text, fmt, ap);
    va_end(ap);
    CHECK(n >= 0 && (size_t)n < sizeof text);
    logs++;
}
static ssize_t synthetic_sendto(int fd, const void *buf, size_t n, int flags,
                                const struct sockaddr *to, socklen_t len) {
    CHECK(fd == UDP_FD && flags == 0 && len == sizeof(struct sockaddr_in));
    CHECK(to && to->sa_family == AF_INET && n <= WIRE_MAX && sent_n < CAPACITY);
    unsigned i = sent_n++;
    Datagram *d = &sent[i];
    memcpy(&d->addr, to, len);
    memcpy(d->bytes, buf, n);
    d->size = n;
    d->failed = i < 32 && (fail_udp_mask & (1u << i));
    if (d->failed) { errno = EIO; return -1; }
    return (ssize_t)n;
}
static ssize_t synthetic_send(int fd, const void *buf, size_t n, int flags) {
    CHECK(fd == TCP_FD && flags == 0);
    if (tcp_chunk && n > tcp_chunk) n = tcp_chunk;
    CHECK(n && n <= sizeof tcp_bytes - tcp_n);
    memcpy(tcp_bytes + tcp_n, buf, n);
    tcp_n += n;
    tcp_calls++;
    return (ssize_t)n;
}
static int synthetic_setsockopt(int fd, int level, int option, const void *value, socklen_t len) {
    CHECK(fd == UDP_FD && level == SOL_SOCKET && option == SO_RCVTIMEO);
    CHECK(len == sizeof(struct timeval));
    const struct timeval *tv = value;
    CHECK(tv->tv_sec == 0 && tv->tv_usec == 100000);
    timeout_calls++;
    return 0;
}
static int synthetic_select(int nfds, fd_set *r, fd_set *w, fd_set *e, struct timeval *tv) {
    CHECK(host_loop && L.hosting && nfds == LISTEN_FD + 1 && r && !w && !e);
    CHECK(tv && tv->tv_sec == 0 && tv->tv_usec == 100000);
    CHECK(FD_ISSET(LISTEN_FD, r) && FD_ISSET(UDP_FD, r));
    CHECK(++select_calls <= CAPACITY && incoming_i < incoming_n);
    FD_ZERO(r);
    FD_SET(UDP_FD, r);  // never mark the fake listening descriptor ready
    return 1;
}
static ssize_t synthetic_recvfrom(int fd, void *buf, size_t cap, int flags,
                                  struct sockaddr *from, socklen_t *len) {
    CHECK(fd == UDP_FD && flags == 0 && from && len && *len >= sizeof(struct sockaddr_in));
    CHECK(++receive_calls <= CAPACITY);
    // Bound the real receive loop, including rejected datagrams and timeouts.
    if (incoming_i == incoming_n) {
        L.uth_run = false;
        errno = EAGAIN;
        return -1;
    }
    Datagram *d = &incoming[incoming_i++];
    CHECK(d->size <= cap);
    memcpy(buf, d->bytes, d->size);
    memcpy(from, &d->addr, sizeof d->addr);
    *len = sizeof d->addr;
    if (incoming_i == incoming_n) {
        L.uth_run = false;
        if (host_loop) L.listen_s = BADSOCK;  // terminate actual host loop on next iteration
    }
    return (ssize_t)d->size;
}
static struct sockaddr_in address(uint32_t ip, uint16_t port) {
    struct sockaddr_in a = {0};
    a.sin_family = AF_INET;
    a.sin_addr.s_addr = htonl(ip);
    a.sin_port = htons(port);
    return a;
}
static void clear_io(void) {
    sent_n = incoming_n = incoming_i = receive_calls = sleep_calls = timeout_calls = 0;
    tcp_n = tcp_calls = delivered = delivered_n = 0;
    fail_udp_mask = 0;
    tcp_chunk = 0;
    select_calls = 0;
}
static void fresh_link(Link *l) {
    CHECK(!pthread_mutex_destroy(&l->wmu));
    memset(l, 0, sizeof *l);
    CHECK(!pthread_mutex_init(&l->wmu, NULL));
    l->s = TCP_FD;
    l->alive = true;
    l->token = 0xabcdef13u;
    l->relay_pair = 0x10293847u;
    l->relay_secret = 0x1122334455667788ull;
    l->uaddr = address(0xc000020a, 39510);  // RFC 5737 TEST-NET relay
    l->paddr = address(0xc6336414, 40000);  // RFC 5737 TEST-NET peer
    direct_reset(l, true);
}
static void reset(void) {
    clear_io();
    now_ns = 100000000000ull;
    L.state = ST_STATION_CONNECTED;
    L.own_ip = 0xa9fe0102;
    L.subnet = 0xa9fe0100;
    L.ryu = L.room = false;
    L.us = L.disc_s = UDP_FD;
    L.listen_s = BADSOCK;
    L.hosting = L.uth_run = false;
    host_loop = false;
    rtt_on = 0;
    fresh_link(&L.up);
    for (int i = 0; i < MAX_NODES; i++) {
        fresh_link(&L.nodes[i]);
        L.nodes[i].alive = false;
        L.nodes[i].ip = L.subnet | (unsigned)(i + 1);
    }
}
static void known_peer(Link *l) {
    l->p_known = true;
    l->dkey = 0xfedcba9876543210ull;
    l->p_since = now_ns;
}
static VPacket packet(void) {
    VPacket p = {0};
    p.src_ip = L.own_ip;
    p.dst_ip = 0xa9fe0101;
    p.src_port = 12345;
    p.dst_port = 23456;
    p.proto = VPROTO_UDP;
    return p;
}
// Independent wire constructors: don't let a broken runtime serializer self-pass.
static void put32(void *p, uint32_t n) { memcpy(p, &n, 4); }
static void put64(void *p, uint64_t n) { memcpy(p, &n, 8); }
static uint32_t get32(const void *p) { uint32_t n; memcpy(&n, p, 4); return n; }
static uint64_t get64(const void *p) { uint64_t n; memcpy(&n, p, 8); return n; }
static void answer_bytes(uint8_t b[32], const Link *l) {
    memset(b, 0, 32);
    memcpy(b, "MHGP", 4);
    put32(b + 4, l->relay_pair);
    put64(b + 8, l->relay_secret);
    memcpy(b + 16, &l->paddr.sin_addr.s_addr, 4);
    memcpy(b + 20, &l->paddr.sin_port, 2);
    put64(b + 24, 0xfedcba9876543210ull);
}
static void queue_bytes(const struct sockaddr_in *from, const void *data, size_t n) {
    CHECK(incoming_n < CAPACITY && n <= WIRE_MAX);
    Datagram *d = &incoming[incoming_n++];
    d->addr = *from;
    d->size = n;
    memcpy(d->bytes, data, n);
}
static Datagram wire(const Link *l, bool direct, uint8_t kind, uint8_t flags, bool with_packet) {
    Datagram d = {0};
    size_t offset = direct ? 16 : 0;
    d.addr = direct ? l->paddr : l->uaddr;
    if (direct) {
        memcpy(d.bytes, "MHGR", 4);
        put32(d.bytes + 4, l->relay_pair);
        put64(d.bytes + 8, l->dkey);
    }
    memcpy(d.bytes + offset, "MHGD", 4);
    put32(d.bytes + offset + 4, l->token);
    d.bytes[offset + 8] = kind;
    d.bytes[offset + 9] = flags;
    d.size = offset + 12;
    if (with_packet) {
        VPacket p = packet();
        memcpy(d.bytes + d.size, &p, sizeof p);
        d.size += sizeof p;
        memcpy(d.bytes + d.size, message, sizeof message);
        d.size += sizeof message;
    }
    return d;
}
static void queue_wire(Datagram d) { queue_bytes(&d.addr, d.bytes, d.size); }
static void run_station(void) {
    L.uth_run = true;
    CHECK(station_udp_thread(NULL) == NULL);
    CHECK(!L.uth_run && incoming_i == incoming_n && timeout_calls == 1);
    CHECK(receive_calls == (incoming_n ? incoming_n : 1));
}
static void run_host(void) {
    CHECK(incoming_n);
    host_loop = L.hosting = true;
    L.listen_s = LISTEN_FD;
    CHECK(host_thread(NULL) == NULL);
    CHECK(L.listen_s == BADSOCK && incoming_i == incoming_n);
    CHECK(receive_calls == incoming_n && select_calls == incoming_n && !timeout_calls);
    host_loop = L.hosting = false;
}
static void assert_delivery(void) {
    VPacket p = packet();
    CHECK(delivered == 1 && delivered_n == sizeof message);
    CHECK(!memcmp(delivered_data, message, sizeof message));
    CHECK(!memcmp(&delivered_packet, &p, sizeof p));
}
static void assert_datagram(const Datagram *d, const Link *l, bool direct, uint8_t kind,
                            const VPacket *p, const void *data, size_t n) {
    size_t prefix = l->relay_pair ? 16 : 0;
    CHECK(same_addr(&d->addr, direct ? &l->paddr : &l->uaddr));
    CHECK(d->size == prefix + 12 + (p ? sizeof *p : 0) + n);
    if (prefix) {
        CHECK(!memcmp(d->bytes, "MHGR", 4) && get32(d->bytes + 4) == l->relay_pair);
        CHECK(get64(d->bytes + 8) == (direct ? l->dkey : l->relay_secret));
    }
    const uint8_t *h = d->bytes + prefix;
    CHECK(!memcmp(h, "MHGD", 4) && get32(h + 4) == l->token && h[8] == kind);
    CHECK(h[10] == 0 && h[11] == 0);
    if (p) CHECK(!memcmp(h + 12, p, sizeof *p));
    if (n) CHECK(!memcmp(h + 12 + (p ? sizeof *p : 0), data, n));
}
static void assert_tcp(const VPacket *p, const void *data, size_t n) {
    CHECK(tcp_calls > 0 && tcp_n == 5 + sizeof *p + n);
    CHECK(get32(tcp_bytes) == 1 + sizeof *p + n && tcp_bytes[4] == F_PACKET);
    CHECK(!memcmp(tcp_bytes + 5, p, sizeof *p));
    CHECK(!memcmp(tcp_bytes + 5 + sizeof *p, data, n));
}

static void test_reset(void) {
    for (unsigned mode = 0; mode < 3; mode++) {
        reset();
        Link *l = &L.up;
        l->p_known = l->p_up = l->p_ever = l->p_noanswer_said = l->p_nopunch_said = true;
        l->p_rx_ns = l->p_since = l->next_query = l->next_punch = l->dkey = 77;
        l->p_good = 8;
        if (mode == 2) l->relay_pair = 0;
        uint32_t token = l->token, pair = l->relay_pair;
        uint64_t secret = l->relay_secret;
        now_ns++;
        direct_reset(l, mode != 1);
        CHECK(l->direct_ok == (mode == 0));
        CHECK(!l->p_known && !l->p_up && !l->p_ever && !l->p_noanswer_said && !l->p_nopunch_said);
        CHECK(!l->p_rx_ns && !l->p_since && !l->next_query && !l->next_punch && !l->dkey && !l->p_good);
        CHECK(l->born_ns == now_ns && l->q_since == now_ns);
        CHECK(l->token == token && l->relay_pair == pair && l->relay_secret == secret);
        peer_query(UDP_FD, l, now_ns, "test");
        CHECK(sent_n == (mode == 0 ? 1u : 0u));
    }
    puts("test-ldn-direct: reset enabled / disabled / LAN: PASS");
}
static void test_query(void) {
    reset();
    CHECK(QUERY_FAST_NS == 30000000000ull && PUNCH_FAST_NS == 15000000000ull);
    Link *l = &L.up;
    peer_query(UDP_FD, l, now_ns, "test");
    CHECK(sent_n == 1 && sent[0].size == 32 && PEER_MSG_SIZE == 32);
    CHECK(same_addr(&sent[0].addr, &l->uaddr));
    CHECK(!memcmp(sent[0].bytes, "MHGR", 4) && get32(sent[0].bytes + 4) == l->relay_pair);
    CHECK(get64(sent[0].bytes + 8) == l->relay_secret && !memcmp(sent[0].bytes + 16, "MHGQ", 4));
    for (int i = 20; i < 32; i++) CHECK(sent[0].bytes[i] == 0);
    CHECK(l->next_query == now_ns + 1000000000ull);
    peer_query(UDP_FD, l, now_ns + 999999999ull, "test");
    CHECK(sent_n == 1);
    now_ns += 1000000000ull;
    peer_query(UDP_FD, l, now_ns, "test");
    CHECK(sent_n == 2);
    now_ns = l->born_ns + QUERY_FAST_NS + 1;
    peer_query(UDP_FD, l, now_ns, "test");
    CHECK(sent_n == 3 && l->p_noanswer_said && l->next_query == now_ns + 15000000000ull);
    l->p_up = true;
    peer_query(UDP_FD, l, now_ns + 20000000000ull, "test");
    CHECK(sent_n == 3);
    puts("test-ldn-direct: query wire identity / padding / fast-to-slow retry: PASS");
}
static void test_answer(void) {
    reset();
    Link *l = &L.up;
    uint8_t b[33] = {0};
    answer_bytes(b, l);
    for (int n = 0; n <= 33; n++) {
        if (n == 32) continue;
        CHECK(!peer_answer(l, b, n, "test") && !l->p_known && !l->dkey);
    }
    const unsigned fields[] = {0, 4, 8};
    for (unsigned i = 0; i < sizeof fields / sizeof fields[0]; i++) {
        b[fields[i]] ^= 1;
        CHECK(!peer_answer(l, b, 32, "test") && !l->p_known && !l->dkey);
        b[fields[i]] ^= 1;
    }
    l->direct_ok = false;
    CHECK(!peer_answer(l, b, 32, "test"));
    l->direct_ok = true;
    CHECK(peer_answer(l, b, 32, "test") && l->p_known);
    CHECK(l->dkey == 0xfedcba9876543210ull && l->p_since == now_ns && !l->next_punch);
    CHECK(l->paddr.sin_family == AF_INET && !memcmp(&l->paddr.sin_addr.s_addr, b + 16, 4));
    CHECK(!memcmp(&l->paddr.sin_port, b + 20, 2));
    uint64_t since = l->p_since;
    now_ns++;
    l->next_punch = 123;
    CHECK(peer_answer(l, b, 32, "test") && l->p_since == since && l->next_punch == 123);
    put64(b + 24, 0x9988776655443322ull);
    CHECK(peer_answer(l, b, 32, "test") && l->dkey == 0x9988776655443322ull);
    b[19] ^= 1;
    CHECK(peer_answer(l, b, 32, "test") && l->p_since == now_ns && !l->next_punch);
    puts("test-ldn-direct: answer exact size / identity / disabled / address update: PASS");
}
static void test_answer_source(void) {
    for (unsigned mode = 0; mode < 4; mode++) {
        reset();
        uint8_t b[32];
        answer_bytes(b, &L.up);
        struct sockaddr_in from = L.up.uaddr;
        if (mode == 1) from.sin_port ^= htons(1);
        if (mode == 2) from.sin_addr.s_addr ^= htonl(1);
        if (mode == 3) L.up.direct_ok = false;
        queue_bytes(&from, b, sizeof b);
        run_station();
        CHECK(L.up.p_known == (mode == 0) && (L.up.dkey != 0) == (mode == 0));
        CHECK(!L.up.p_up && !delivered && !L.up.udp_rx_ns);
    }
    puts("test-ldn-direct: real station trusts answers only from exact relay endpoint: PASS");
}
static void test_direct_source(void) {
    reset();
    Link *l = &L.up;
    struct sockaddr_in from = l->paddr;
    CHECK(!direct_from(l, &from));
    known_peer(l);
    from.sin_addr.s_addr ^= htonl(1);
    CHECK(!direct_from(l, &from));
    from = l->paddr;
    from.sin_port = htons(45678);
    CHECK(direct_from(l, &from) && l->paddr.sin_port == from.sin_port);
    CHECK(!l->p_rx_ns && !l->p_up);
    puts("test-ldn-direct: peer IP required / authenticated peer port change: PASS");
}
static void test_receive_rejections(void) {
    // All these go through the actual station_udp_thread, not a duplicate parser.
    for (unsigned mode = 0; mode < 14; mode++) {
        reset();
        known_peer(&L.up);
        Datagram d = wire(&L.up, true, U_HELLO_ACK, 0, false);
        switch (mode) {
        case 0: d.bytes[0] ^= 1; break;          // outer magic
        case 1: d.bytes[4] ^= 1; break;          // pair
        case 2: d.bytes[8] ^= 1; break;          // direct key
        case 3: d.bytes[20] ^= 1; break;         // token
        case 4: d.addr.sin_addr.s_addr ^= htonl(1); break;
        case 5: d.size = 15; break;
        case 6: d.size = 27; break;
        case 7: d.bytes[16] ^= 1; break;         // inner magic
        case 8: L.up.p_known = false; break;
        case 9: L.up.dkey = 0; break;
        case 10: L.up.relay_pair = 0; break;
        case 11: d = wire(&L.up, false, U_HELLO_ACK, 0, false); d.addr = L.up.paddr; break;
        case 12: d.addr = L.up.uaddr; break;     // relay must strip MHGR
        case 13: put64(d.bytes + 8, L.up.relay_secret); break;  // relay secret is NOT the direct key
        }
        queue_wire(d);
        run_station();
        CHECK(!L.up.p_up && !L.up.p_rx_ns && !L.up.p_good && !L.up.udp_rx_ns && !delivered);
    }
    puts("test-ldn-direct: real station rejects bad magic / pair / key / token / IP / lengths: PASS");
}
static void test_handshake_sequence(void) {
    reset();
    uint8_t b[32];
    answer_bytes(b, &L.up);
    queue_bytes(&L.up.uaddr, b, sizeof b);
    // Independent incoming direct ACK is already constructed with the server's
    // key; the runtime must learn that key from the queued answer first.
    known_peer(&L.up);
    queue_wire(wire(&L.up, true, U_HELLO_ACK, 0, false));
    queue_wire(wire(&L.up, false, U_HELLO_ACK, 0, false));
    queue_wire(wire(&L.up, true, U_DATA, 0, true));
    L.up.p_known = false;
    L.up.dkey = 0;
    run_station();  // four receive iterations in ONE actual runtime loop
    CHECK(L.up.p_up && L.up.udp_up && L.up.p_good == 1 && L.up.p_ever);
    CHECK(sent_n == 4 && !tcp_n);
    assert_datagram(&sent[0], &L.up, false, U_HELLO, NULL, &now_ns, 8);
    CHECK(sent[1].size == 32 && !memcmp(sent[1].bytes + 16, "MHGQ", 4));
    assert_datagram(&sent[2], &L.up, true, U_HELLO, NULL, &now_ns, 8);
    assert_datagram(&sent[3], &L.up, true, U_HELLO, NULL, &now_ns, 8);
    CHECK(sent[2].bytes[25] == 0 && sent[3].bytes[25] == UF_DIRECT_OK);
    assert_delivery();
    puts("test-ldn-direct: real multi-iteration answer -> hello -> ACK -> confirmed hello handshake: PASS");
}
static Link *host_setup(void) {
    reset();
    L.state = ST_AP_CREATED;
    L.own_ip = 0xa9fe0101;
    Link *l = &L.nodes[1];
    l->alive = true;
    known_peer(l);
    return l;
}
static void test_host_receive(void) {
    Link *l = host_setup();
    const uint8_t stamp[16] = {1, 2, 3, 4, 5, 6, 7, 8, 99, 98, 97, 96, 95, 94, 93, 92};
    Datagram d = wire(l, true, U_HELLO, 0, false);
    memcpy(d.bytes + d.size, stamp, sizeof stamp);
    d.size += sizeof stamp;
    queue_wire(d);
    run_host();
    CHECK(!l->p_up && l->p_rx_ns == now_ns && !l->udp_up);
    CHECK(sent_n == 4);  // relay registration, query, punch, ACK
    CHECK(sent[0].size == 16 && get64(sent[0].bytes + 8) == l->relay_secret);
    assert_datagram(&sent[2], l, true, U_PUNCH, NULL, NULL, 0);
    assert_datagram(&sent[3], l, true, U_HELLO_ACK, NULL, stamp, 8);  // echo bounded to eight

    clear_io();
    d = wire(l, true, U_HELLO, UF_DIRECT_OK, false);
    queue_wire(d);
    run_host();
    CHECK(l->p_up && l->p_rx_ns == now_ns);
    assert_datagram(&sent[sent_n - 1], l, true, U_HELLO_ACK, NULL, NULL, 0);
    clear_io();
    queue_wire(wire(l, true, U_HELLO, 0, false));
    run_host();
    CHECK(!l->p_up);  // authenticated one-way report withdraws direct routing
    clear_io();
    queue_wire(wire(l, true, U_DATA, 0, true));
    run_host();
    CHECK(l->p_up && l->p_rx_ns == now_ns && delivered == 1);
    CHECK(delivered_packet.src_ip == l->ip && delivered_packet.dst_ip == L.own_ip);
    CHECK(delivered_n == sizeof message && !memcmp(delivered_data, message, sizeof message));
    clear_io();
    queue_wire(wire(l, false, U_HELLO, 0, false));
    run_host();
    CHECK(l->udp_up && l->udp_rx_ns == now_ns);
    assert_datagram(&sent[sent_n - 1], l, false, U_HELLO_ACK, NULL, NULL, 0);
    puts("test-ldn-direct: real host receive direct hello flags / bounded echo / data source / relay hello: PASS");
}
static void test_host_rejections(void) {
    for (unsigned mode = 0; mode < 9; mode++) {
        Link *l = host_setup();
        Datagram d = wire(l, true, U_DATA, 0, true);
        switch (mode) {
        case 0: d.bytes[0] ^= 1; break;
        case 1: d.bytes[4] ^= 1; break;
        case 2: d.bytes[8] ^= 1; break;
        case 3: d.bytes[20] ^= 1; break;
        case 4: d.addr.sin_addr.s_addr ^= htonl(1); break;
        case 5: d.size = 15; break;
        case 6: d.size = 27; break;
        case 7: d = wire(l, false, U_DATA, 0, true); d.addr = l->paddr; break;
        case 8: d.addr = l->uaddr; break;
        }
        queue_wire(d);
        run_host();
        CHECK(!l->p_up && !l->p_rx_ns && !l->udp_up && !l->udp_rx_ns && !delivered);
    }
    for (unsigned mode = 0; mode < 3; mode++) {
        Link *l = host_setup();
        l->p_known = false;
        l->dkey = 0;
        uint8_t b[32];
        answer_bytes(b, l);
        struct sockaddr_in from = l->uaddr;
        if (mode == 1) from.sin_port ^= htons(1);
        if (mode == 2) from.sin_addr.s_addr ^= htonl(1);
        queue_bytes(&from, b, sizeof b);
        run_host();
        CHECK(l->p_known == (mode == 0) && (l->dkey != 0) == (mode == 0));
    }
    puts("test-ldn-direct: real host rejects direct identity / endpoint errors and untrusted answers: PASS");
}
static void test_receive_paths(void) {
    reset();
    known_peer(&L.up);
    Datagram d = wire(&L.up, true, U_HELLO_ACK, 0, false);
    d.addr.sin_port = htons(45678);
    queue_wire(d);
    run_station();
    CHECK(L.up.p_up && L.up.p_ever && L.up.p_good == 1 && L.up.p_rx_ns == now_ns);
    CHECK(L.up.paddr.sin_port == htons(45678) && !L.up.udp_up && !L.up.udp_rx_ns && !delivered);
    clear_io();
    now_ns += 100000000ull;
    uint64_t proof = L.up.p_rx_ns;
    queue_wire(wire(&L.up, true, U_PUNCH, 0, false));
    run_station();
    CHECK(L.up.p_rx_ns == proof);
    clear_io();
    queue_wire(wire(&L.up, true, U_DATA, 0, true));
    run_station();
    assert_delivery();
    CHECK(L.up.p_rx_ns == proof);  // data and punches do not prove station's transmit path
    clear_io();
    queue_wire(wire(&L.up, false, U_HELLO_ACK, 0, false));
    run_station();
    CHECK(L.up.udp_up && L.up.udp_rx_ns == now_ns && L.up.p_rx_ns == proof);
    clear_io();
    queue_wire(wire(&L.up, false, U_DATA, 0, true));
    run_station();
    assert_delivery();
    clear_io();
    d = wire(&L.up, true, U_DATA, 0, true);
    d.size = 16 + 12 + sizeof(VPacket) - 1;
    queue_wire(d);
    run_station();
    CHECK(!delivered);
    reset();
    L.up.relay_pair = 0;
    direct_reset(&L.up, true);
    queue_wire(wire(&L.up, false, U_HELLO_ACK, 0, false));
    run_station();
    CHECK(L.up.udp_up && !L.up.direct_ok && !L.up.p_up && sent_n == 1);
    assert_datagram(&sent[0], &L.up, false, U_HELLO, NULL, &now_ns, 8);
    puts("test-ldn-direct: real direct ACK / punch / data / relay UDP / LAN receive: PASS");
}
static void test_silence_and_recovery(void) {
    reset();
    CHECK(DIRECT_REUP == 3 && DIRECT_SILENCE_NS == 3500000000ull);
    CHECK(DIRECT_HELLO_NS == 1000000000ull && UDP_SILENCE_NS == 15000000000ull);
    known_peer(&L.up);
    Link *l = &L.up;
    l->p_up = l->p_ever = true;
    l->p_good = 7;
    l->p_rx_ns = now_ns;
    l->udp_up = true;
    l->udp_rx_ns = now_ns;
    now_ns += DIRECT_SILENCE_NS + 1;
    queue_wire(wire(l, true, U_PUNCH, 0, false));
    run_station();  // actual periodic silence check and immediate query
    CHECK(!l->p_up && !l->p_good && l->p_ever && l->udp_up);
    CHECK(l->q_since == now_ns && l->p_since == now_ns);
    bool query = false;
    for (unsigned i = 0; i < sent_n; i++)
        if (sent[i].size == 32 && !memcmp(sent[i].bytes + 16, "MHGQ", 4)) query = true;
    CHECK(query);
    for (int i = 1; i <= DIRECT_REUP; i++) {
        clear_io();
        now_ns += 100000000ull;
        queue_wire(wire(l, true, U_HELLO_ACK, 0, false));
        run_station();
        CHECK(l->p_good == i && l->p_up == (i == DIRECT_REUP));
    }
    clear_io();
    now_ns = l->udp_rx_ns + UDP_SILENCE_NS + 1;
    run_station();  // timeout-only bounded iteration, relay expires independently
    CHECK(!l->udp_up && !l->p_up && sleep_calls == 1);
    puts("test-ldn-direct: silence fallback / immediate query / three-ACK recovery / UDP expiry: PASS");
}
static void test_route(bool host) {
    reset();
    Link *l = &L.up;
    VPacket p = packet();
    if (host) {
        L.state = ST_AP_CREATED;
        L.own_ip = 0xa9fe0101;
        l = &L.nodes[1];
        l->alive = true;
        p.src_ip = L.own_ip;
        p.dst_ip = l->ip;
    }
    known_peer(l);
    l->p_up = l->p_ever = l->udp_up = true;
    l->p_rx_ns = l->udp_rx_ns = now_ns;
    ldn_send(&p, message, sizeof message);
    CHECK(sent_n == 1 && !tcp_n && !delivered);
    assert_datagram(&sent[0], l, true, U_DATA, &p, message, sizeof message);
    clear_io();
    now_ns += DIRECT_SILENCE_NS;  // exact threshold already unusable for sending
    CHECK(!direct_usable(l) && udp_usable(l));
    ldn_send(&p, message, sizeof message);
    CHECK(sent_n == 1 && !tcp_n);
    assert_datagram(&sent[0], l, false, U_DATA, &p, message, sizeof message);
    clear_io();
    now_ns = l->udp_rx_ns + UDP_SILENCE_NS;
    tcp_chunk = 3;  // exercise actual send_all loop
    ldn_send(&p, message, sizeof message);
    CHECK(!sent_n && tcp_calls > 3);
    assert_tcp(&p, message, sizeof message);
    clear_io();
    l->p_rx_ns = l->udp_rx_ns = now_ns;
    fail_udp_mask = 1;
    ldn_send(&p, message, sizeof message);
    CHECK(sent_n == 2 && sent[0].failed && !sent[1].failed && !tcp_n);
    assert_datagram(&sent[1], l, false, U_DATA, &p, message, sizeof message);
    clear_io();
    fail_udp_mask = 3;
    ldn_send(&p, message, sizeof message);
    CHECK(sent_n == 2 && sent[0].failed && sent[1].failed);
    assert_tcp(&p, message, sizeof message);
    clear_io();
    if (host) L.disc_s = BADSOCK; else L.us = BADSOCK;
    ldn_send(&p, message, sizeof message);
    CHECK(!sent_n);
    assert_tcp(&p, message, sizeof message);
    printf("test-ldn-direct: %s ldn_send direct -> relay UDP -> TCP / send-error fallback: PASS\n",
           host ? "host" : "station");
}
static void test_local_and_host_filter(void) {
    reset();
    VPacket p = packet();
    p.dst_ip = L.own_ip;
    ldn_send(&p, message, sizeof message);
    CHECK(delivered == 1 && !sent_n && !tcp_n);
    clear_io();
    L.state = ST_STATION;
    ldn_send(&p, message, sizeof message);
    CHECK(!delivered && !sent_n && !tcp_n);
    reset();
    L.state = ST_AP_CREATED;
    L.own_ip = 0xa9fe0101;
    p = packet();
    p.dst_ip = 0xffffffffu;
    for (int i = 1; i <= 3; i++) {
        Link *l = &L.nodes[i];
        l->alive = true;
        known_peer(l);
        l->p_up = true;
        l->p_rx_ns = now_ns;
        l->token += (unsigned)i;
    }
    L.nodes[3].alive = false;
    host_route(1, &p, message, sizeof message);
    CHECK(delivered == 1 && sent_n == 1 && !tcp_n);  // no reflection or dead-node send
    assert_datagram(&sent[0], &L.nodes[2], true, U_DATA, &p, message, sizeof message);
    clear_io();
    p.dst_ip = L.nodes[1].ip;
    host_route(0, &p, message, sizeof message);
    CHECK(!delivered && sent_n == 1);
    assert_datagram(&sent[0], &L.nodes[1], true, U_DATA, &p, message, sizeof message);
    puts("test-ldn-direct: local / disconnected / host broadcast and source filtering: PASS");
}
static void test_payload_bound(void) {
    reset();
    known_peer(&L.up);
    static uint8_t data[8193];
    VPacket p = packet();
    CHECK(UDP_MAX_PAYLOAD == 8192 && sizeof(UHdr) == 12 && sizeof(VPacket) == 16);
    CHECK(udp_send(UDP_FD, &L.up.paddr, &L.up, false, U_DATA, 0, &p, data, 8192));
    CHECK(sent_n == 1);
    assert_datagram(&sent[0], &L.up, true, U_DATA, &p, data, 8192);
    CHECK(!udp_send(UDP_FD, &L.up.paddr, &L.up, false, U_DATA, 0, &p, data, 8193) && sent_n == 1);
    clear_io();
    L.up.p_up = L.up.udp_up = true;
    L.up.p_rx_ns = L.up.udp_rx_ns = now_ns;
    ldn_send(&p, data, sizeof data);
    CHECK(!sent_n);
    assert_tcp(&p, data, sizeof data);
    puts("test-ldn-direct: UDP payload bound / oversized TCP fallback: PASS");
}
static void test_blocked(void) {
    reset();
    known_peer(&L.up);
    CHECK(!direct_from(&L.up, &L.up.paddr));
    queue_wire(wire(&L.up, true, U_HELLO_ACK, 0, false));
    run_station();
    CHECK(!L.up.p_up && !L.up.p_rx_ns && !delivered);
    puts("test-ldn-direct: deterministic MHGU_LDN_BLOCK_DIRECT rejection: PASS");
}
int main(int argc, char **argv) {
    CHECK(argc == 1 || (argc == 2 && !strcmp(argv[1], "--blocked")));
    CHECK(!pthread_mutex_init(&L.up.wmu, NULL));
    for (int i = 0; i < MAX_NODES; i++) CHECK(!pthread_mutex_init(&L.nodes[i].wmu, NULL));
    if (argc == 2) {
        block_setting = "0";
        test_blocked();
    } else {
        test_reset();
        test_query();
        test_answer();
        test_answer_source();
        test_direct_source();
        test_receive_rejections();
        test_handshake_sequence();
        test_host_receive();
        test_host_rejections();
        test_receive_paths();
        test_silence_and_recovery();
        test_route(false);
        test_route(true);
        test_local_and_host_filter();
        test_payload_bound();
    }
    CHECK(!pthread_mutex_destroy(&L.up.wmu));
    for (int i = 0; i < MAX_NODES; i++) CHECK(!pthread_mutex_destroy(&L.nodes[i].wmu));
    puts("test-ldn-direct: PASS (synthetic only; zero real network or background threads)");
    return 0;
}
