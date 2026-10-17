/* 宿主侧等价性测试：证明"成块写零"与上游"逐字节 fputc"产出的字节流完全相同。
 * 这是本次性能修补的**正确性**验证（性能验证另在机内做）。 */
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static long old_way(FILE *f, long offset, long sh_offset) {
    while (offset < sh_offset) { fputc(0, f); offset++; }
    return offset;
}

static long new_way(FILE *f, long offset, long sh_offset) {
    while (offset < sh_offset) {
        static const char zeros[4096];
        size_t n = (size_t)(sh_offset - offset);
        if (n > sizeof(zeros)) n = sizeof(zeros);
        offset += fwrite(zeros, 1, n, f);
    }
    return offset;
}

static int cmp(const char *a, const char *b, long expect_len) {
    FILE *fa = fopen(a, "rb"), *fb = fopen(b, "rb");
    if (!fa || !fb) return -1;
    long n = 0; int bad = 0;
    for (;;) {
        int ca = fgetc(fa), cb = fgetc(fb);
        if (ca == EOF || cb == EOF) { if (ca != cb) bad = 1; break; }
        if (ca != cb) { bad = 1; break; }
        n++;
    }
    fclose(fa); fclose(fb);
    if (bad || n != expect_len) { printf("MISMATCH n=%ld expect=%ld\n", n, expect_len); return 1; }
    return 0;
}

int main(void) {
    /* 覆盖：0、1、4095、4096、4097、以及一个"大 .bss 空洞"量级 */
    long gaps[] = { 0, 1, 4095, 4096, 4097, 100000, 5075500 };
    int fails = 0;
    for (unsigned i = 0; i < sizeof(gaps)/sizeof(gaps[0]); i++) {
        FILE *fa = fopen("a.bin", "wb"), *fb = fopen("b.bin", "wb");
        long ra = old_way(fa, 0, gaps[i]);
        long rb = new_way(fb, 0, gaps[i]);
        fclose(fa); fclose(fb);
        if (ra != rb) { printf("OFFSET DIFF gap=%ld old=%ld new=%ld\n", gaps[i], ra, rb); fails++; continue; }
        if (cmp("a.bin", "b.bin", gaps[i]) != 0) { printf("FAIL gap=%ld\n", gaps[i]); fails++; }
        else printf("OK gap=%ld offset=%ld\n", gaps[i], ra);
    }
    printf("PAD-EQUIV %s (fails=%d)\n", fails ? "FAIL" : "PASS", fails);
    return fails ? 1 : 0;
}
