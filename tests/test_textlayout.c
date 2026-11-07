// Synthetic font/archive inputs only; no font or other game data.
#include <assert.h>
#include "../runtime/hle/textlayout.c"

static void check_archive(void) {
    static const unsigned char plain[] = "public synthetic glyph metrics";
    unsigned char compressed[128];
    uLongf compressed_size = sizeof compressed;
    assert(compress(compressed, &compressed_size, plain, sizeof plain) == Z_OK);
    for (int packed = 0; packed < 2; packed++) {
        FILE *f = tmpfile();
        assert(f);
        unsigned char header[12] = {'A', 'R', 'C', 0, 0, 0, 1};
        unsigned char entry[80] = "synthetic";
        uint32_t cs = packed ? (uint32_t)compressed_size : sizeof plain;
        uint32_t ds = sizeof plain, off = sizeof header + sizeof entry;
        memcpy(entry + 68, &cs, 4);
        memcpy(entry + 72, &ds, 4);
        memcpy(entry + 76, &off, 4);
        assert(fwrite(header, 1, sizeof header, f) == sizeof header);
        assert(fwrite(entry, 1, sizeof entry, f) == sizeof entry);
        assert(fwrite(packed ? compressed : plain, 1, cs, f) == cs);
        uint32_t size = 0;
        unsigned char *result = arc_entry(f, "synthetic", &size);
        assert(result && size == sizeof plain);
        assert(!memcmp(result, plain, size));
        free(result);
        assert(!arc_entry(f, "missing", &size));
        assert(!fseek(f, off, SEEK_SET));
        assert(fputc(0, f) != EOF);
        if (packed) assert(!arc_entry(f, "synthetic", &size));
        fclose(f);
    }
    FILE *empty = tmpfile();
    assert(empty);
    uint32_t size = 0;
    assert(!arc_entry(empty, "synthetic", &size));
    fclose(empty);
}

static void check_page(void) {
    unsigned char texture[24 + 512] = {'T', 'E', 'X', 0, 0xa0};
    uint32_t dimensions = 1 | (8 << 6) | (8 << 19);
    memcpy(texture + 8, &dimensions, 4);
    texture[13] = 7;
    texture[24 + 3] = 200;
    Page page;
    assert(page_open(&page, texture, sizeof texture));
    assert(page.w == 8 && page.h == 8);
    assert(alpha(&page, 0, 0) == 200);
    assert(alpha(&page, 8, 0) == 0);
    assert(alpha(&page, 0, 8) == 0);
    assert(!page_open(&page, texture, sizeof texture - 1));
    assert(!page_open(&page, texture, 20));
    texture[13] = 0;
    assert(!page_open(&page, texture, sizeof texture));
}

static void check_pairs(void) {
    Glyph left = {.code = 'V', .b = 8 | (8 << 12), .width = 8};
    Glyph right = {.code = 'a', .b = 8 | (8 << 12), .width = 8};
    for (int row = 0; row < ROWS; row++) {
        left.rp[row] = 1;
        right.lp[row] = 0;
    }
    assert(kern_pair(&left, &right) == -2);
    left.code = '1';
    assert(kern_pair(&left, &right) == 0);
    left.code = '.';
    right.code = ',';
    assert(kern_pair(&left, &right) == 0);
    left.code = 'V';
    right.code = 'a';
    right.b = 8 | (9 << 12);
    assert(kern_pair(&left, &right) == 0);
    right.b = left.b;
    left.width = 30;
    assert(kern_pair(&left, &right) == -KERN_MAX);
}

int main(void) {
    check_archive();
    check_page();
    check_pairs();
    puts("test-textlayout: synthetic archives, page bounds and kerning OK");
    return 0;
}
