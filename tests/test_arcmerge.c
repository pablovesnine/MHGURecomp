// Public, handwritten ARC fixtures. No game files or compressed game payloads.
#define _GNU_SOURCE
#include "arcmerge.h"
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

typedef struct { const char *name; uint32_t type; uint8_t value; } Item;

static void put32(uint8_t *p, uint32_t v) {
    for (int i = 0; i < 4; ++i) p[i] = (uint8_t)(v >> (8 * i));
}

static uint32_t get32(const uint8_t *p) {
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void fixture(const char *path, const Item *items, unsigned n, unsigned version) {
    size_t size = 12 + n * 81;
    uint8_t *image = calloc(size, 1);
    assert(image);
    memcpy(image, "ARC", 4);
    image[4] = version;
    image[6] = n;
    for (unsigned i = 0; i < n; ++i) {
        uint8_t *e = image + 12 + i * 80;
        size_t offset = 12 + n * 80 + i;
        assert(strlen(items[i].name) < 64);
        strcpy((char *)e, items[i].name);
        put32(e + 64, items[i].type);
        put32(e + 68, 1);
        put32(e + 72, 1);
        put32(e + 76, offset);
        image[offset] = items[i].value;
    }
    FILE *f = fopen(path, "wb");
    assert(f && fwrite(image, 1, size, f) == size);
    assert(fclose(f) == 0);
    free(image);
}

static void expect(const char *path, const Item *items, unsigned n) {
    FILE *f = fopen(path, "rb");
    assert(f);
    uint8_t head[12], entry[80];
    assert(fread(head, 1, 12, f) == 12);
    assert(!memcmp(head, "ARC", 4) && head[6] == n && head[7] == 0);
    for (unsigned i = 0; i < n; ++i) {
        assert(fseek(f, 12 + i * 80, SEEK_SET) == 0);
        assert(fread(entry, 1, 80, f) == 80);
        assert(!strcmp((char *)entry, items[i].name));
        assert(get32(entry + 64) == items[i].type);
        assert(get32(entry + 68) == 1);
        assert(fseek(f, get32(entry + 76), SEEK_SET) == 0);
        assert(fgetc(f) == items[i].value);
    }
    assert(fclose(f) == 0);
}

int main(void) {
    char directory[] = "/tmp/mhgu-arc-test-XXXXXX";
    char previous[4096], first[1200], second[1200], ignored[1200], overlap[65];
    assert(getcwd(previous, sizeof previous));
    assert(mkdtemp(directory) && chdir(directory) == 0);
    const Item original[] = {{"same", 1, 10}, {"same", 2, 20}, {"other", 1, 30}};
    const Item partial[] = {{"same", 1, 11}};
    const Item later[] = {{"same", 1, 12}, {"new", 1, 40}};
    const Item disjoint[] = {{"unrelated", 1, 50}};
    const Item first_expected[] = {{"same", 1, 11}, {"same", 2, 20}, {"other", 1, 30}};
    const Item second_expected[] = {
        {"same", 1, 12}, {"same", 2, 20}, {"other", 1, 30}, {"new", 1, 40}};
    fixture("original.arc", original, 3, 17);
    fixture("partial.arc", partial, 1, 17);
    fixture("later.arc", later, 2, 17);
    fixture("full.arc", original, 3, 17);
    fixture("disjoint.arc", disjoint, 1, 17);
    fixture("empty.arc", NULL, 0, 17);
    fixture("wrong-version.arc", partial, 1, 18);
    FILE *bad = fopen("malformed.arc", "wb");
    assert(bad && fwrite("ARC", 1, 3, bad) == 3 && fclose(bad) == 0);
    assert(arc_partial("original.arc", "partial.arc"));
    assert(!arc_partial("original.arc", "full.arc"));
    assert(!arc_partial("original.arc", "disjoint.arc"));
    assert(!arc_partial("original.arc", "empty.arc"));
    assert(!arc_partial("original.arc", "wrong-version.arc"));
    assert(!arc_partial("original.arc", "malformed.arc"));
    assert(!arc_partial("original.arc", "missing.arc"));
    assert(arc_merge("original.arc", "original.arc", "partial.arc", first, sizeof first));
    expect(first, first_expected, 3);
    assert(arc_merge("original.arc", "original.arc", "partial.arc", ignored, sizeof ignored));
    assert(!strcmp(first, ignored));
    expect(ignored, first_expected, 3);
    assert(arc_overlap("original.arc", "partial.arc", "later.arc", overlap, sizeof overlap) == 1);
    assert(!strcmp(overlap, "same"));
    assert(arc_overlap("original.arc", "partial.arc", "disjoint.arc", NULL, 0) == 0);
    assert(arc_overlap("original.arc", "partial.arc", "wrong-version.arc", NULL, 0) == -1);
    assert(arc_merge("original.arc", first, "later.arc", second, sizeof second));
    expect(second, second_expected, 4);
    assert(!arc_merge("original.arc", first, "wrong-version.arc", ignored, sizeof ignored));
    assert(!arc_merge("original.arc", first, "malformed.arc", ignored, sizeof ignored));
    assert(remove(first) == 0 && remove(second) == 0);
    const char *files[] = {"original.arc", "partial.arc", "later.arc", "full.arc",
                          "disjoint.arc", "empty.arc", "wrong-version.arc", "malformed.arc"};
    for (unsigned i = 0; i < sizeof files / sizeof *files; ++i) assert(remove(files[i]) == 0);
    assert(rmdir("cache/arcmerge") == 0 && rmdir("cache") == 0);
    assert(chdir(previous) == 0 && rmdir(directory) == 0);
    puts("partial ARC overlays, entry types, cache and load order: PASS");
    return 0;
}
