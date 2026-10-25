"""Random RTL designs for the Cyclone IV routing / LAB-control corpus (`rnd_*` in corpus/cycloneiv).

Each design: scalar input pins, a random 4-input LUT network, registers with random controls
(enable, sync clear, async clear, sync load), adders (carry chains), outputs = XOR groups that
cover every node (so synthesis keeps the logic).  Pins are left to the fitter; a per-design
fitter SEED varies placement and routing.  Seeded: the same name always regenerates the same text.
"""
import random

# (count, LUT nodes range, inputs, outputs): small ones isolate, big ones cover most LABs.
TIERS = [("s", 40, (20, 120), (8, 24), (4, 16)),
         ("m", 40, (300, 700), (16, 40), (8, 24)),
         ("l", 40, (900, 1500), (24, 40), (16, 32))]
# Sources mostly from the last LOCAL nodes: random global wiring made 2600-node designs
# unroutable in 10 min on EP4CE6.
LOCAL = 60
P_LOCAL = 0.85


def rnd_design(seed, n_nodes, n_in, n_out):
    r = random.Random(seed)
    ins = [f"i{k}" for k in range(n_in)]
    two_clk = r.random() < 0.4
    clks = ["clk0", "clk1"] if two_clk else ["clk0"]
    pool = list(ins)
    body, regs, decl = [], [], []
    n_add = r.randrange(0, 4) if n_nodes > 40 else r.randrange(0, 2)
    k = 0
    for i in range(n_nodes):
        if n_add and r.random() < n_add / max(n_nodes, 1) * 4:
            w = r.randrange(3, 13)
            a = [r.choice(pool) for _ in range(w)]
            b = [r.choice(pool) for _ in range(w)]
            op = r.choice("+-")
            nm = f"s{k}"
            k += 1
            decl.append(f"  wire [{w}:0] {nm};")
            body.append(f"  assign {nm} = {{1'b0, {', '.join(a)}}} {op} {{1'b0, {', '.join(b)}}};")
            pool += [f"{nm}[{j}]" for j in range(w + 1)]
            continue
        src = [r.choice(pool[-LOCAL:] if r.random() < P_LOCAL else pool) for _ in range(4)]
        mask = r.randrange(1, 0xFFFF)
        nm = f"n{i}"
        decl.append(f"  wire {nm};")
        body.append(f"  assign {nm} = 16'h{mask:04x} >> {{{', '.join(src)}}};")
        if r.random() < 0.35:
            q = f"q{i}"
            clk = r.choice(clks)
            edge = "negedge" if r.random() < 0.1 else "posedge"
            ctl = {c: r.choice(pool) for c in ("en", "sclr", "aclr", "sld") if r.random() < 0.3}
            sens = f"{edge} {clk}" + (f" or posedge {ctl['aclr']}" if "aclr" in ctl else "")
            rv = r.randrange(2) if "aclr" in ctl else 0
            decl.append(f"  reg {q};")
            st = f"{q} <= {nm};"
            if "sld" in ctl:
                st = f"if ({ctl['sld']}) {q} <= {r.choice(pool)}; else {st}"
            if "sclr" in ctl:
                st = f"if ({ctl['sclr']}) {q} <= 1'b0; else {st}"
            if "en" in ctl:
                st = f"if ({ctl['en']}) begin {st} end"
            if "aclr" in ctl:
                st = f"if ({ctl['aclr']}) {q} <= 1'b{rv}; else begin {st} end"
            regs.append(f"  always @({sens}) begin {st} end")
            pool.append(q)
        else:
            pool.append(nm)
    internal = [p for p in pool if p not in ins]
    r.shuffle(internal)
    outs = [f"o{j}" for j in range(n_out)]
    groups = [internal[j::n_out] for j in range(n_out)]
    assigns = []
    for j, o in enumerate(outs):
        g = groups[j] or [r.choice(ins)]
        inv = "~" if r.random() < 0.2 else ""
        assigns.append(f"  assign {o} = {inv}(^{{{', '.join(g)}}});")
    ports = [f"input {c}" for c in clks] + [f"input {i}" for i in ins] + [f"output {o}" for o in outs]
    v = (f"module top({', '.join(ports)});\n" + "\n".join(decl) + "\n" + "\n".join(body) + "\n"
         + "\n".join(regs) + "\n" + "\n".join(assigns) + "\nendmodule\n")
    return v


def rnd_specs():
    out = {}
    for tier, count, (lo, hi), (ilo, ihi), (olo, ohi) in TIERS:
        for j in range(count):
            seed = 1_000_003 * (ord(tier) - 96) + j
            r = random.Random(seed)
            n_nodes, n_in, n_out = r.randrange(lo, hi + 1), r.randrange(ilo, ihi + 1), r.randrange(olo, ohi + 1)
            v = rnd_design(seed, n_nodes, n_in, n_out)
            name = f"rnd_{tier}{j:02d}"
            out[name] = {"top": "top", "verilog": v,
                         "qsf": [f"set_global_assignment -name SEED {1 + r.randrange(1000)}"],
                         "purpose": f"random RTL, {n_nodes} LUT nodes, {n_in} in / {n_out} out (routing corpus)",
                         "exercises": ["routing", "lab_controls", "carry", "io"]}
    return out
