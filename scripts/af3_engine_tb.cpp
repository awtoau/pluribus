// Verilator harness for the AF3 engine cone (scripts/cycloneiv_clean_af3_engine.py) with a virtual 1-Wire slave.
// usage: Vengine --cycles N [--mhz F] [--slave none|ds] [--secret HEX16] [--romseed N] [--macord B] [--badmac] [--trace FILE] [--ff]
// Slave = public DS28E01-class protocol (reset/presence, ROM cmds 33/CC, write scratchpad 0F, read authenticated page A5, SHA-1 MAC)
// with a DUMMY secret given on the command line (default fixed dummy).  No real secret exists in this file.
// The engine's own secret words (message words W0 / W12 at RAM 0x110 / 0x11c) are replaced by the dummy secret (ovr_w0 / ovr_w12 inputs) and never printed.
#include "Vengine.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cstdint>
#include <string>
#include <vector>

static uint32_t rol(uint32_t x, int n) { return (x << n) | (x >> (32 - n)); }
// SHA-1 compression (FIPS 180); add_iv = 0 returns the raw a..e after round 79 (no final addition)
static void sha1_block(const uint8_t b[64], uint32_t out[5], int add_iv) {
    uint32_t h[5] = {0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0}, w[80];
    for (int i = 0; i < 16; i++) w[i] = (uint32_t)b[4 * i] << 24 | (uint32_t)b[4 * i + 1] << 16 | (uint32_t)b[4 * i + 2] << 8 | b[4 * i + 3];
    for (int i = 16; i < 80; i++) w[i] = rol(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1);
    uint32_t a = h[0], bb = h[1], c = h[2], d = h[3], e = h[4];
    for (int i = 0; i < 80; i++) {
        uint32_t f, k;
        if (i < 20) { f = (bb & c) | (~bb & d); k = 0x5A827999; }
        else if (i < 40) { f = bb ^ c ^ d; k = 0x6ED9EBA1; }
        else if (i < 60) { f = (bb & c) | (bb & d) | (c & d); k = 0x8F1BBCDC; }
        else { f = bb ^ c ^ d; k = 0xCA62C1D6; }
        uint32_t t = rol(a, 5) + f + e + k + w[i];
        e = d; d = c; c = rol(bb, 30); bb = a; a = t;
    }
    uint32_t r[5] = {a, bb, c, d, e};
    for (int i = 0; i < 5; i++) out[i] = add_iv ? r[i] + h[i] : r[i];
}
static uint8_t crc8(uint8_t crc, uint8_t b) { for (int i = 0; i < 8; i++) { uint8_t m = (crc ^ b) & 1; crc >>= 1; if (m) crc ^= 0x8C; b >>= 1; } return crc; }   // x^8+x^5+x^4+1
static uint16_t crc16(uint16_t crc, uint8_t b) { for (int i = 0; i < 8; i++) { uint16_t m = (crc ^ b) & 1; crc >>= 1; if (m) crc ^= 0xA001; b >>= 1; } return crc; }   // x^16+x^15+x^2+1

struct Slave {
    double us_per_cycle;
    uint64_t t_fall = 0; int prev = 1; bool pulling = false; uint64_t pull_until = 0;
    enum { IDLE, ROMCMD, FUNC, RXB, TXB } st = IDLE;
    uint8_t rom[8], secret[8], page[32], sp[8]; uint8_t ta1 = 0, ta2 = 0;
    std::vector<uint8_t> tx, rx; size_t txi = 0; int txbit = 0, rxbit = 0, need = 0, after_tx = IDLE; uint8_t rxbyte = 0, cmd = 0;
    bool present_pending = false; uint64_t present_at = 0; int macord = 0; bool badmac = false;
    std::vector<std::string> evlog;
    void ev(const std::string& s, uint64_t cyc) { char b[64]; snprintf(b, sizeof b, "%llu ", (unsigned long long)cyc); evlog.push_back(b + s); }
    Slave(double u, int rs, const uint8_t* sec, int mo, bool bad) : us_per_cycle(u), macord(mo), badmac(bad) {
        memset(page, 0, 32); memset(sp, 0, 8);
        for (int i = 0; i < 7; i++) rom[i] = 0x10 + i + rs;
        rom[0] = 0x2F; uint8_t c = 0; for (int i = 0; i < 7; i++) c = crc8(c, rom[i]); rom[7] = c;
        memcpy(secret, sec, 8);
    }
    // block layout inferred from the engine's RAM image (structure): secret[0..3] | page 32 | 00 00 FF FF | 0x40 | ROM[0..6] | secret[4..7] | 00 00 00 | 0x80 | 0.. | 01 B8
    void mac(uint8_t out[20]) {
        uint8_t b[64]; memset(b, 0, 64);
        memcpy(b, secret, 4); memcpy(b + 4, page, 32); b[38] = 0xFF; b[39] = 0xFF; b[40] = 0x40; memcpy(b + 41, rom, 7); memcpy(b + 48, secret + 4, 4);
        b[55] = 0x80; b[62] = 0x01; b[63] = 0xB8;
        uint32_t h[5]; sha1_block(b, h, (macord >> 2) & 1);
        for (int i = 0; i < 5; i++) {
            int wi = (macord & 1) ? 4 - i : i;
            for (int k = 0; k < 4; k++) out[4 * i + k] = (macord & 2) ? (h[wi] >> (8 * k)) : (h[wi] >> (24 - 8 * k));
        }
        if (badmac) out[3] ^= 1;
    }
    void load_tx(const std::vector<uint8_t>& v, int nxt) { tx = v; txi = 0; txbit = 0; st = TXB; after_tx = nxt; }
    void byte_done(uint8_t b, uint64_t cyc) {
        char s[48]; snprintf(s, sizeof s, "RX %02X", b); ev(s, cyc);
        if (st == ROMCMD) {
            if (b == 0xCC) st = FUNC;
            else if (b == 0x33) load_tx(std::vector<uint8_t>(rom, rom + 8), FUNC);
            else st = IDLE;
        } else if (st == FUNC) {
            cmd = b; rx.clear();
            if (b == 0x0F) { need = 10; st = RXB; } else if (b == 0xA5) { need = 2; st = RXB; } else st = IDLE;
        } else if (st == RXB) {
            rx.push_back(b);
            if ((int)rx.size() == need) {
                if (cmd == 0x0F) {
                    ta1 = rx[0]; ta2 = rx[1]; memcpy(sp, &rx[2], 8);
                    uint16_t c = 0; c = crc16(c, 0x0F); for (auto x : rx) c = crc16(c, x); c = ~c;
                    load_tx({(uint8_t)(c & 0xFF), (uint8_t)(c >> 8)}, IDLE);
                } else if (cmd == 0xA5) {
                    std::vector<uint8_t> v; uint16_t c = 0; c = crc16(c, 0xA5); c = crc16(c, rx[0]); c = crc16(c, rx[1]);
                    for (int a = rx[0] & 0x1F; a < 32; a++) { v.push_back(page[a]); c = crc16(c, page[a]); }
                    v.push_back(0xFF); c = crc16(c, 0xFF); c = ~c; v.push_back(c & 0xFF); v.push_back(c >> 8);
                    uint8_t m[20]; mac(m); v.insert(v.end(), m, m + 20);
                    load_tx(v, IDLE);
                }
            }
        }
    }
    bool step(uint64_t cyc, int line) {      // line = level driven by the master (1 = released); returns whether the slave pulls low next cycle
        if (pulling && cyc >= pull_until) pulling = false;
        if (present_pending && cyc >= present_at) { present_pending = false; pulling = true; pull_until = cyc + (uint64_t)(120.0 / us_per_cycle); ev("PRESENCE", cyc); }
        if (prev == 1 && line == 0) { t_fall = cyc; on_fall(cyc); }
        if (prev == 0 && line == 1) on_rise(cyc, (cyc - t_fall) * us_per_cycle);
        prev = line;
        return pulling;
    }
    void on_fall(uint64_t cyc) {
        if (st == TXB) { int bit = (tx[txi] >> txbit) & 1; if (!bit) { pulling = true; pull_until = cyc + (uint64_t)(40.0 / us_per_cycle); } }
    }
    void on_rise(uint64_t cyc, double low_us) {
        if (low_us >= 400) {
            ev("RESET low=" + std::to_string((int)low_us) + "us", cyc);
            present_pending = true; present_at = cyc + (uint64_t)(30.0 / us_per_cycle); st = ROMCMD; rxbit = 0; rxbyte = 0; txbit = 0; txi = 0;
            return;
        }
        if (st == TXB) {
            txbit++; if (txbit == 8) { txbit = 0; txi++; if (txi >= tx.size()) { st = (decltype(st))after_tx; ev("TX done", cyc); } }
            return;
        }
        int bit = low_us < 30.0 ? 1 : 0;      // write-1 low 1..15 us, write-0 low 60..120 us
        rxbyte |= bit << rxbit; rxbit++;
        if (rxbit == 8) { uint8_t b = rxbyte; rxbit = 0; rxbyte = 0; byte_done(b, cyc); }
    }
};

static int hexv(char c) { return c <= '9' ? c - '0' : (c | 32) - 'a' + 10; }

int main(int argc, char** argv) {
    Verilated::commandArgs(argc, argv);
    uint64_t cycles = 1000000; double mhz = 40.0; std::string slave = "none", trace = ""; bool ffd = false, bad = false; int romseed = 0, macord = 0;
    uint8_t sec[8]; for (int i = 0; i < 8; i++) sec[i] = 0xA0 + i;    // DUMMY default
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--cycles")) cycles = strtoull(argv[++i], 0, 0);
        else if (!strcmp(argv[i], "--mhz")) mhz = atof(argv[++i]);
        else if (!strcmp(argv[i], "--slave")) slave = argv[++i];
        else if (!strcmp(argv[i], "--ff")) ffd = true;
        else if (!strcmp(argv[i], "--badmac")) bad = true;
        else if (!strcmp(argv[i], "--romseed")) romseed = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--macord")) macord = atoi(argv[++i]);
        else if (!strcmp(argv[i], "--secret")) { const char* h = argv[++i]; for (int k = 0; k < 8; k++) sec[k] = hexv(h[2 * k]) << 4 | hexv(h[2 * k + 1]); }
        else if (!strcmp(argv[i], "--trace")) trace = argv[++i];
    }
    Vengine* d = new Vengine;
    Slave sl(1.0 / mhz, romseed, sec, macord, bad);
    d->ovr_w0 = (uint32_t)sec[0] << 24 | sec[1] << 16 | sec[2] << 8 | sec[3];
    d->ovr_w12 = (uint32_t)sec[4] << 24 | sec[5] << 16 | sec[6] << 8 | sec[7];
    FILE* tf = trace.empty() ? nullptr : fopen(trace.c_str(), "w");
    int line = 1, prevline = 1; uint32_t paddr = 0xFFFF; int pwe = 0; bool slave_low = false;
    char bufr[16], bufw[16];
    for (uint64_t c = 0; c < cycles; c++) {
        int mline = d->af3_oe ? (d->af3_drv ? 1 : 0) : 1;     // master drive; released = pulled up
        line = (mline && !slave_low) ? 1 : 0;
        d->pad_AF3 = line; d->clk = 0; d->eval(); d->pad_AF3 = line; d->eval(); d->clk = 1; d->eval();
        slave_low = (slave != "none") ? sl.step(c, mline) : false;
        if (tf) {
            if (line != prevline) fprintf(tf, "%llu AF3 %d oe=%d drv=%d\n", (unsigned long long)c, line, (int)d->af3_oe, (int)d->af3_drv);
            if (d->ramaddr != paddr || d->ramwe != pwe) {
                // dummy-secret words are not printed either (positions W0 = 0x110, W12 = 0x11c)
                bool sec_now = d->ramaddr == 0x110 || d->ramaddr == 0x11c, sec_prev = paddr == 0x110 || paddr == 0x11c;
                snprintf(bufr, sizeof bufr, "%08x", (unsigned)d->ramrd); snprintf(bufw, sizeof bufw, "%08x", (unsigned)d->ramwd);
                fprintf(tf, "%llu RAM a=%03x we=%d rd=%s wd=%s\n", (unsigned long long)c, (unsigned)d->ramaddr, (int)d->ramwe, sec_prev ? "<secret>" : bufr, sec_now ? "<secret>" : bufw);
                if (ffd) { fprintf(tf, "  FF"); for (int w = 6; w >= 0; w--) fprintf(tf, " %08x", (unsigned)d->ffvec[w]); fprintf(tf, "\n"); }
                paddr = d->ramaddr; pwe = d->ramwe;
            }
        }
        prevline = line;
    }
    if (tf) fclose(tf);
    printf("FINAL-FF"); for (int w = 6; w >= 0; w--) printf(" %08x", (unsigned)d->ffvec[w]); printf("\n");
    for (auto& e : sl.evlog) printf("SLAVE %s\n", e.c_str());
    d->final(); delete d;
    return 0;
}
