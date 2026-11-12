// Narrow production-leaf regression: include actual vsock.c, call only vsock_deliver.
// Synthetic bytes and virtual socket records; no guest mappings, real sockets,
// threads, emulator, hub, or game data. CHECK remains live under NDEBUG.
#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../runtime/hle.h"
#include "../runtime/net/net.h"

#ifndef MHGU_TEST_HITSYNC_CROSSPLAY
#error "select MHGU_TEST_HITSYNC_CROSSPLAY=0 (0.16.0) or =1 (>=0.16.1)"
#endif
#if MHGU_TEST_HITSYNC_CROSSPLAY != 0 && MHGU_TEST_HITSYNC_CROSSPLAY != 1
#error "MHGU_TEST_HITSYNC_CROSSPLAY must be 0 or 1"
#endif
static unsigned checks;
#define CHECK(x) do { ++checks; if (!(x)) { \
    fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #x); exit(1); \
} } while (0)

static unsigned depth, nlock, nunlock, nwake, nreceived;
static const void *expected_data;
static uint32_t expected_len;
static int fixture_lock(pthread_mutex_t *p) {
    CHECK(depth == 0); int r = pthread_mutex_lock(p);
    CHECK(r == 0); ++depth; ++nlock; return r;
}
static int fixture_unlock(pthread_mutex_t *p) {
    CHECK(depth == 1); --depth; ++nunlock; return pthread_mutex_unlock(p);
}
static int fixture_broadcast(pthread_cond_t *p) {
    CHECK(depth == 1); ++nwake; return pthread_cond_broadcast(p);
}
static void *forbidden_guest(uint32_t a) {
    (void)a; CHECK(false); return NULL;
}
#undef G2H
#undef LD8
#undef LD16
#undef LD32
#undef ST8
#undef ST16
#undef ST32
#define G2H(a) forbidden_guest((uint32_t)(a))
#define LD8(a) (*(uint8_t *)G2H(a))
#define LD16(a) (*(uint16_t *)G2H(a))
#define LD32(a) (*(uint32_t *)G2H(a))
#define ST8(a,v) (*(uint8_t *)G2H(a) = (uint8_t)(v))
#define ST16(a,v) (*(uint16_t *)G2H(a) = (uint16_t)(v))
#define ST32(a,v) (*(uint32_t *)G2H(a) = (uint32_t)(v))
#define pthread_mutex_lock fixture_lock
#define pthread_mutex_unlock fixture_unlock
#define pthread_cond_broadcast fixture_broadcast
#ifndef MHGU_VSOCK_SOURCE
#define MHGU_VSOCK_SOURCE "../runtime/net/vsock.c"
#endif
#include MHGU_VSOCK_SOURCE
#undef pthread_mutex_lock
#undef pthread_mutex_unlock
#undef pthread_cond_broadcast

uint32_t ldn_broadcast_ip(void) { return 0x0a17ffffu; }
void ldn_send(const VPacket *p, const void *data, uint32_t len) {
    (void)p; (void)data; (void)len; CHECK(false); // Tested leaf must never send.
}
void hitsync_aux_received(const void *data, uint32_t len) {
    // Dispatch precedes the vsock mutex: avoid lock inversion with hitsync's own lock.
    CHECK(depth == 0 && data == expected_data && len == expected_len);
    ++nreceived;
}
static void deliver(VPacket p, const void *data, uint32_t len, bool hit) {
    expected_data = data; expected_len = len;
    unsigned before = nreceived, locked = nlock, woke = nwake;
    vsock_deliver(&p, data, len);
    CHECK(nreceived == before + (hit && MHGU_TEST_HITSYNC_CROSSPLAY));
    CHECK(depth == 0 && nlock == locked + 1 && nunlock == nlock && nwake == woke + 1);
}
int main(int argc, char **argv) {
    (void)argv; CHECK(argc == 1);
    const uint8_t bytes[] = {0x55, 0xaa, 0, 1, 2, 3, 4};
    // Literal port is intentional: a production constant/dispatch mutation must fail.
    VPacket p = {0x0a170003u, 0x0a17ffffu, 12345, 47318, VPROTO_UDP, 0, 0};
    deliver(p, bytes, sizeof bytes, true); // No virtual listener needed.
    deliver(p, bytes, 0, true); // Dispatch is not a wire decoder.
    p.dst_port = 47317; deliver(p, bytes, sizeof bytes, false);
    p.src_port = 47318; p.dst_port = 12345; deliver(p, bytes, sizeof bytes, false);
    p.dst_port = 47318; p.proto = VPROTO_TCP; p.kind = VTCP_DATA;
    deliver(p, bytes, sizeof bytes, false);

    // The callback is additive, not consuming: ordinary UDP delivery still runs.
    p.proto = VPROTO_UDP; p.kind = 0; p.src_port = 12345;
    VSock *s = alloc_sock(S_SOCK_DGRAM); CHECK(s != NULL); s->port = 47318;
    deliver(p, bytes, sizeof bytes, true);
    CHECK(s->nq == 1 && s->head == s->tail && s->head->next == NULL);
    CHECK(s->head->ip == p.src_ip && s->head->port == p.src_port && s->head->len == sizeof bytes);
    CHECK(memcmp(s->head->data, bytes, sizeof bytes) == 0);
    free_queue(s); CHECK(s->nq == 0);

    // Actual dispatch gates only on UDP + destination port, NOT source port/IP,
    // destination IP, payload validity, net-up, settings, or crossplay status.
    s->ip = 0x0a170002u;
    p.dst_ip = 0x0b180004u; p.src_port = 1;
    deliver(p, bytes, sizeof bytes, true);
    CHECK(s->nq == 0); // Unicast address mismatch blocks socket queue, not callback.
    s->rip = p.src_ip + 1; p.dst_ip = ldn_broadcast_ip();
    deliver(p, bytes, sizeof bytes, true); CHECK(s->nq == 0);
    s->rip = 0; s->nq = MAX_QUEUED;
    deliver(p, bytes, sizeof bytes, true); CHECK(s->nq == MAX_QUEUED && !s->head);
    s->nq = 0;
    printf("test-hitsync-vsock: PASS (%u fail-closed CHECKs; crossplay=%d)\n",
           checks, MHGU_TEST_HITSYNC_CROSSPLAY);
    return 0;
}
