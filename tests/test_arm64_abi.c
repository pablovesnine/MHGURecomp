// Public ABI vectors only, not generated code or game data.
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include "cpu.h"

#if !defined(__aarch64__)
#error "This probe must run as an AArch64 program"
#endif

_Static_assert(GUEST_BASE == UINT64_C(0x1000000000), "ARM64 guest base");
_Static_assert((char)255 < 0, "the runtime and generated code need signed char");

int main(void) {
    assert((uintptr_t)G2H(0) == GUEST_BASE);
    assert((uintptr_t)G2H(UINT32_MAX) == GUEST_BASE + UINT32_MAX);
    assert((uintptr_t)G2H(UINT64_C(0x100000000)) == GUEST_BASE);
    assert(H2G(G2H(0)) == 0);
    assert(H2G(G2H(UINT32_MAX)) == UINT32_MAX);
    assert(GUEST_BASE + UINT64_C(0x100000000) < (UINT64_C(1) << 39));
    puts("ARM64 signed char, guest range and pointer round trips: PASS");
    return 0;
}
