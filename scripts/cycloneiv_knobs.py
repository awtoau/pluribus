"""Directed Cyclone IV GX builds (EP4CGX150, WYSIWYG dffeas / IO cells).

  gx150_ffc_NNN  register-control corpus
  gx150_io_NNN   every user pin as input and as output
Each member varies one thing; the CRAM diff is the knob plus the routing it forces.
"""

FFC_DESIGNS = 120          # gx150_ffc_NNN: register-control corpus (directed, WYSIWYG dffeas)


def ffc_design(seed, inv_ctl=False):
    """Groups of registers sharing control signals; every control/clock choice random per group."""
    import random
    r = random.Random(seed)
    ctl = {"clk": ["clk0", "clk1"], "ena": ["e0", "e1"], "clrn": ["c0", "c1"], "sclr": ["s0", "s1"],
           "sload": ["l0", "l1"]}
    ndata = r.randrange(12, 28)
    data = [f"d{k}" for k in range(ndata)]
    body, outs, q = [], [], []
    for g in range(r.randrange(5, 11)):
        use = {k: (r.choice(v) if r.random() < (1.0 if k == "clk" else 0.55) else None) for k, v in ctl.items()}
        if inv_ctl:       # inverted control signals: the pin inverter bits
            use = {k: (("~" + u) if u and k != "clk" and r.random() < 0.4 else u) for k, u in use.items()}
        inv = r.random() < 0.15
        for j in range(r.randrange(3, 10)):
            nm = f"r{g}_{j}"
            d_src = r.choice(data)
            if r.random() < 0.5:
                body.append(f"  wire n{g}_{j} = {r.choice(data)} & {d_src};")
                d_src = f"n{g}_{j}"
            ports = [f".d({d_src})", f".clk({'~' if inv else ''}{use['clk']})", f".q({nm}_q)"]
            for k in ("ena", "clrn", "sclr", "sload"):
                if use[k]:
                    ports.append(f".{k}({use[k]})")
            if use["sload"]:
                ports.append(f".asdata({r.choice(data)})")
            body.append(f"  wire {nm}_q;")
            body.append(f"  dffeas #(.power_up(\"low\"), .is_wysiwyg(\"true\")) {nm} ({', '.join(ports)});")
            q.append(f"{nm}_q")
    r.shuffle(q)
    n_out = max(4, len(q) // 8)
    for o in range(n_out):
        grp = q[o::n_out]
        outs.append(f"o{o}")
        body.append(f"  assign o{o} = ^{{{', '.join(grp)}}};")
    allc = [c for v in ctl.values() for c in v]
    return (f"module top(input {', '.join(allc + data)}, output {', '.join(outs)});\n" + "\n".join(body)
            + "\nendmodule\n")


def ffc_specs():
    out = {}
    for j in range(FFC_DESIGNS):
        out[f"gx150_ffi_{j:03d}"] = {
            "top": "top", "verilog": ffc_design(41_000_000 + j, inv_ctl=True), "device": "EP4CGX150DF31C7",
            "qsf": ["set_global_assignment -name SEED %d" % (1 + j)],
            "purpose": "register-control corpus with inverted control signals on EP4CGX150",
            "exercises": ["ff_controls", "pin_inverters"]}
    for j in range(FFC_DESIGNS):
        out[f"gx150_ffc_{j:03d}"] = {
            "top": "top", "verilog": ffc_design(31_000_000 + j), "device": "EP4CGX150DF31C7",
            "qsf": ["set_global_assignment -name SEED %d" % (1 + j)],
            "purpose": "register-control corpus (WYSIWYG dffeas groups) on EP4CGX150",
            "exercises": ["ff_controls", "lab_controls"]}
    return out


IO_DESIGNS = 220           # gx150_io_NNN: every user pin used as input and as output several times


def user_pins():
    """User I/O balls of the EP4CGX150 F896 from a built design's pin report (reserved or used)."""
    import re
    from pathlib import Path
    rep = Path(__file__).resolve().parent.parent / "corpus" / "cycloneiv" / "gx150_ffc_001" / "build.pin"
    pins = []
    if not rep.exists():
        return pins
    for ln in rep.read_text().splitlines():
        p = [x.strip() for x in ln.split(":")]
        if len(p) >= 7 and re.match(r"^[A-Z]{1,2}\d+$", p[1]) and p[5]:
            name = p[0]
            if name.startswith("RESERVED_INPUT") or (p[2] in ("input", "output", "bidir") and not name.startswith("~")):
                pins.append(p[1])
    return sorted(set(pins))


def io_design(seed, pins):
    import random
    r = random.Random(seed)
    k = r.randrange(16, 29)
    chosen = r.sample(pins, 2 * k)
    ins, outs = chosen[:k], chosen[k:]
    body = []
    for j in range(k):
        a, b, c = (r.choice(range(k)) for _ in range(3))
        body.append(f"  assign o{j} = i{a} ^ (i{b} & i{c});")
    v = (f"module top(input {', '.join(f'i{j}' for j in range(k))}, output {', '.join(f'o{j}' for j in range(k))});\n"
         + "\n".join(body) + "\nendmodule\n")
    qsf = [f"set_location_assignment PIN_{p} -to i{j}" for j, p in enumerate(ins)]
    qsf += [f"set_location_assignment PIN_{p} -to o{j}" for j, p in enumerate(outs)]
    return v, qsf


def io_specs():
    out = {}
    pins = user_pins()
    for j in range(IO_DESIGNS if pins else 0):
        v, q = io_design(51_000_000 + j, pins)
        out[f"gx150_io_{j:03d}"] = {
            "top": "top", "verilog": v, "device": "EP4CGX150DF31C7", "qsf": q,
            "purpose": "pin sweep: every user pin as input and as output (IO site signatures)",
            "exercises": ["io"]}
    return out
