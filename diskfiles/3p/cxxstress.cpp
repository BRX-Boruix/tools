/* cxxstress.cpp —— 用**编 cc1 的同一个交叉 g++** 编出来的 C++ 运行期压力探针。
 *
 * 为什么需要它：cc1 崩在 `build_gimple_cfg`，而那里第一件事就是
 *   `discriminator_per_locus = new hash_table<locus_discrim_hasher> (13);`
 * ——即 **libstdc++ 的 operator new/delete + GCC 自己的 hash_table**。
 * 这条路径（C++ 运行期 + 我们 libc 的 malloc/free）此前**从未在系统内跑过**：
 * 已有的机内程序都是 C。本探针把它跑到与 cc1 同量级的强度。
 *
 * 覆盖：new/delete（含数组、含大块）、std::string 拼接、std::vector 反复扩容、
 *       std::map 红黑树、std::sort、以及一个 hash 风格的开链容器。
 */
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include <map>
#include <algorithm>

struct Node {
    unsigned key;
    unsigned val;
    Node *next;
    Node(unsigned k, unsigned v) : key(k), val(v), next(nullptr) {}
};

static unsigned rng = 987654321u;
static unsigned rnd() { rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5; return rng; }

int main() {
    int fails = 0;

    /* 1) new / delete（含数组与较大块） */
    for (int i = 0; i < 20000; i++) {
        unsigned n = 1 + rnd() % 512;
        unsigned char *p = new unsigned char[n];
        for (unsigned j = 0; j < n; j++) p[j] = (unsigned char)(i + j);
        for (unsigned j = 0; j < n; j++) if (p[j] != (unsigned char)(i + j)) { fails++; break; }
        delete[] p;
    }
    { char *big = new char[1 << 20]; memset(big, 0x5A, 1 << 20); if (big[0] != 0x5A || big[(1<<20)-1] != 0x5A) fails++; delete[] big; }
    printf("ok   new/delete 20000 轮 + 1MiB 块\n");

    /* 2) std::string 反复拼接/扩容 */
    {
        std::string s;
        for (int i = 0; i < 20000; i++) s += (char)('a' + (i % 26));
        if (s.size() != 20000) fails++;
        std::string t = s + s;
        if (t.size() != 40000 || t[0] != s[0]) fails++;
        printf("ok   std::string 拼接 20000 次（len=%zu）\n", s.size());
    }

    /* 3) std::vector 反复扩容 + std::sort */
    {
        std::vector<unsigned> v;
        for (int i = 0; i < 100000; i++) v.push_back(rnd());
        std::sort(v.begin(), v.end());
        for (size_t i = 1; i < v.size(); i++) if (v[i-1] > v[i]) { fails++; break; }
        printf("ok   std::vector 10 万 + std::sort（n=%zu）\n", v.size());
    }

    /* 4) std::map（红黑树，大量节点分配/释放） */
    {
        std::map<unsigned, unsigned> m;
        for (int i = 0; i < 50000; i++) m[rnd() % 100000] = (unsigned)i;
        unsigned cnt = 0;
        for (std::map<unsigned,unsigned>::iterator it = m.begin(); it != m.end(); ++it) cnt++;
        printf("ok   std::map 5 万次插入（去重后 n=%u）\n", cnt);
    }

    /* 5) hash 风格开链容器（与 GCC hash_table 同形） */
    {
        const unsigned BUCKETS = 13;
        Node *tab[BUCKETS];
        for (unsigned i = 0; i < BUCKETS; i++) tab[i] = nullptr;
        for (int i = 0; i < 50000; i++) {
            unsigned k = rnd() % 100000;
            unsigned b = k % BUCKETS;
            Node *n = new Node(k, (unsigned)i);
            n->next = tab[b];
            tab[b] = n;
        }
        unsigned cnt = 0;
        for (unsigned i = 0; i < BUCKETS; i++) {
            for (Node *p = tab[i]; p; p = p->next) cnt++;
            Node *p = tab[i];
            while (p) { Node *nx = p->next; delete p; p = nx; }
        }
        if (cnt != 50000) fails++;
        printf("ok   开链 hash 5 万节点（cnt=%u）\n", cnt);
    }

    printf("cxxstress: fails=%d\n", fails);
    return fails ? 1 : 0;
}
