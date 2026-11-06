// Public fixtures run without platform_init: match its SIGPIPE policy and make
// readiness assertions observable without sleeps or host LD_PRELOAD tricks.
#include <signal.h>
#include <stdio.h>

__attribute__((constructor)) static void initialize_fixture(void) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    signal(SIGPIPE, SIG_IGN);
}
