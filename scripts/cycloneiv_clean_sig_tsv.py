#!/usr/bin/env python3.15t
"""Write reference/signatures.tsv from tmp/sig/<name>/sig.json (+ fit.json, LICENCE-NOTE.txt).  Structure only, no source.

  python3.15t scripts/cycloneiv_clean_sig_tsv.py
Columns: name, block_type, built_from, expected_structure, decoded_resources, quartus_fit, recovered, evidence
"""
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIG = os.path.join(REPO, "tmp", "sig")
OUT = os.path.join(REPO, "reference", "signatures.tsv")

# name -> (block type, built from, expected structure, test(sig) -> (recovered, evidence))
def has(key):
    return lambda d: (bool(d.get(key)), "; ".join(d.get(key) or []) or "no catalogue hit")


def rs_enc_has(d):
    hits = [h for s in d["scc"] for h in (s.get("rs_catalogue") or [])]
    return bool(hits), (hits[0] if hits else "no catalogue hit")


def lfsr_has(word):
    def f(d):
        hits = [h for s in d["scc"] for h in (s.get("lfsr_catalogue") or []) if word in h]
        return bool(hits), (hits[0] if hits else "no catalogue hit; SCC " + str([(s["n"], s.get("minpoly")) for s in d["scc"][:2]]))
    return f


def fft_test(d):
    return "partial", "MAC %d (Quartus mult9 16 = 8 MAC), M9K %d (delay lines, content zero), carry LUTs %d, 9 adders; twiddles are LUT logic: no ROM table to match" % (d["mac"], d["m9k"], d["carry_luts"])


def vit_test(d):
    big = sum(1 for s in d["scc"] if s["n"] == 64)
    return ("partial" if big else "no"), "%d SCCs of 64 FFs (2^(K-1) states, K=7), non-linear (ACS), %d 8-bit adders, %d carry LUTs, %d M9K; polynomials 171/133 not asserted" % (big, d["rtl"]["adders"], d["carry_luts"], d["m9k"])


def ilv_test(d):
    ok = 192 in d["shift_chains"]
    return ("partial" if ok else "no"), "shift chain of 192 FFs (block length), %d mux2 in the permutation; permutation order not tested" % d["rtl"]["muxes"]


def uart_test(d):
    return "partial", "FSM %d, carry LUTs %d (baud divider adder, widths %s), 2 SCCs of 23 FFs; no catalogue" % (d["rtl"]["fsms"], d["carry_luts"], d["rtl"]["adder_widths"])


def rom_test(d):
    n = d.get("m9k_sine_blocks", 0)
    return bool(n), "; ".join(b["sine_table"][0] for b in d["m9k_blocks"] if b["sine_table"]) or "no table"


def mac_test(d):
    return d["mac"] >= 1, "%d MAC block(s) decoded (Quartus 2 mult9)" % d["mac"]


SPEC = {
    "wimax_prbs": ("LFSR randomiser", "MIT VHDL prbs.vhd (OmarElayat/Channel-Coding-QPSK-For-WiMAX-system), 1 bit/clk", "15-FF linear SCC, primitive poly x^15+x^14+1 (either orientation)", lfsr_has("PRBS15")),
    "prbs15_lfsr": ("LFSR randomiser", "MIT lfsr.v (alexforencich/verilog-ethernet) + own register wrapper, poly 15'h4001 Fibonacci, 8 bit/clk", "15-FF linear SCC, x^15+x^14+1, 8-bit parallel", lfsr_has("PRBS15")),
    "scr_80211b": ("LFSR scrambler", "80211scrambler scrambler.v (no licence stated; reference only), self-synchronising x^7+x^4+1", "7-FF linear SCC, x^7+x^4+1", lfsr_has("PRBS7")),
    "scr_xband": ("LFSR scrambler", "MIT VHDL Scrambler.vhd (moamenibrahim/X-band-Transmitter...)", "20-FF linear SCC, 20-bit LFSR", lfsr_has("PRBS20")),
    "crc32_lfsr": ("CRC32 engine", "MIT lfsr.v + own register wrapper, poly 04C11DB7 Galois, 8 bit/clk", "32-FF linear SCC, minimal polynomial = CRC-32 (IEEE 802.3)", lfsr_has("CRC32")),
    "crc8_lfsr": ("CRC8 engine (802.16 HCS poly 07)", "MIT lfsr.v + own register wrapper, poly 07 Galois, 8 bit/clk", "8-FF linear SCC, x^8+x^2+x+1", lfsr_has("CRC8")),
    "rs255_enc": ("Reed-Solomon encoder RS(255,239)", "MIT dshekhalev/FEC rs_enc.sv, n=255 check=16 m=8 irrpol=285", "128-FF linear SCC whose minimal polynomial equals the GF(2^8) generator-LFSR (16 roots a^0..a^15)", rs_enc_has),
    "rs255_dec": ("Reed-Solomon decoder RS(255,239)", "MIT dshekhalev/FEC rs_dec.sv (+bch_buffer.sv), n=255 check=16", "minimal polynomials of a^0..a^15 among 8-FF linear SCCs (syndrome / Chien registers)", has("rs_syndrome_catalogue")),
    "conv_k7": ("Convolutional encoder K=7 171/133", "MIT dshekhalev/FEC vit_enc.sv, vit_trellis.svh K=7 171/133", "6-FF shift chain + two XOR tap cones with delay sets {1,2,3,6} and {2,3,5,6} (delay 0 gated)", has("conv_catalogue")),
    "viterbi_k7": ("Viterbi decoder K=7", "MIT dshekhalev/FEC vit_dec.sv family, K=7 171/133, LLR width 4", "64-state ACS array: SCCs of 64 FFs", vit_test),
    "interleaver_wimax": ("Block interleaver (192-bit)", "MIT VHDL inter_top/sipo/piso (OmarElayat...)", "192-FF shift chain + permutation", ilv_test),
    "fft64_r22sdf": ("FFT 64-pt R2^2 SDF", "MIT nanamake/r22sdf FFT64.v, 16-bit", "MAC array (complex multiplier), delay-line RAM, twiddle ROM", fft_test),
    "uart": ("UART tx/rx", "MIT alexforencich/verilog-uart uart.v, prescale input", "baud counter (carry chain) + tx/rx FSMs", uart_test),
    "sine_rom": ("Cosine ROM (twiddle/NCO table)", "own code: 256 x 16-bit full-wave cos in M9K via $readmemh", "M9K block whose words sample cos(2*pi*i/256) with peak 32000", rom_test),
    "ip_multadd": ("Hard multiplier-adder (Altera altera_mult_add)", "ip-generate defaults, SC Lite", "one MAC block", mac_test),
}
NODEC = {
    "altera_fft64": ("FFT 64-pt (Altera FFT II, variable streaming, fixed point, 16-bit)", "ip-generate altera_fft_ii length=64 Variable Streaming Fixed Point in=16 twid=16 out=22"),
    "ip_nco": ("NCO (Altera NCO II)", "ip-generate altera_nco_ii defaults"),
    "ip_cic": ("CIC filter (Altera CIC II)", "ip-generate altera_cic_ii defaults"),
    "ip_rs_ii": ("Reed-Solomon (Altera RS II)", "ip-generate altera_rs_ii defaults"),
    "ip_bch": ("BCH (Altera BCH)", "ip-generate altera_bch defaults"),
    "ip_vit": ("Viterbi (Altera Viterbi II)", "ip-generate altera_viterbi_ii defaults"),
}


def fit(n):
    p = os.path.join(SIG, n, "fit.json")
    if not os.path.exists(p):
        return ""
    f = json.load(open(p))
    return "LE %s, FF %s, mem bits %s, mult9 %s, pins %s" % (f["les"], f["regs"], f["m9k"], f["mult9"], f["pins"])


def main():
    rows = [["name", "block_type", "built_from", "expected_structure", "decoded_resources", "quartus_fit", "recovered", "evidence"]]
    for n, (bt, src, exp, test) in SPEC.items():
        p = os.path.join(SIG, n, "sig.json")
        if not os.path.exists(p):
            rows.append([n, bt, src, exp, "", fit(n), "not run", ""])
            continue
        d = json.load(open(p))
        r, ev = test(d)
        rec = r if isinstance(r, str) else ("yes" if r else "no")
        res = "LUT %d (carry %d), FF %d, M9K %d, MAC %d, pads in/out %d/%d" % (d["luts"], d["carry_luts"], d["ffs"], d["m9k"], d["mac"], d["pads_in"], d["pads_out"])
        rows.append([n, bt, src, exp, res, fit(n), rec, ev])
    for n, (bt, src) in NODEC.items():
        rows.append([n, bt, src, "(Quartus-side counts only)", "", fit(n), "not decodable",
                     "OpenCore Plus: time-limited .sof only, quartus_cpf refuses .rbf; SOF payload layout differs from the rbf plane"])
    with open(OUT, "w") as fh:
        for r in rows:
            fh.write("\t".join(x.replace("\t", " ").replace("\n", " ") for x in r) + "\n")
    print("wrote", OUT, len(rows) - 1, "rows")


if __name__ == "__main__":
    main()
