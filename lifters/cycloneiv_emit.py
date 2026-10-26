"""Verilog emitter for the Cyclone IV netlist (lifters/cycloneiv_lift.Design).

Self-contained behavioural Verilog: no vendor models.  One module; boundary nets (pads, clock
wires, unresolved inputs) are input ports, every LUT / FF output is a wire named c_x_y_le /
q_x_y_le (so a testbench can probe them).  Unresolved inputs are listed in a header comment and
are inputs the caller must drive (X in the gate: a fault, never a pass).

LUT   c  = init[{d, cc, b, a}]   (cc = c, or cin in carry mode);  co = init[{1'b0, cin, b, a}]
FF    q <= 0 on !clrn (async); on posedge clk (inverted when clk_inv) and ena:
      sclr ? 0 : sload ? asdata : d
"""


def emit(des, top="cycloneiv_lifted"):
    ports = sorted(des.terminals)
    out = [f"// Cyclone IV lifted netlist: {len(des.luts)} LUTs, {len(des.ffs)} FFs, "
           f"{len(ports)} boundary inputs, {len(des.unresolved)} unresolved cell inputs",
           f"// NOT LIFTED: {dict(des.not_lifted) or 'nothing recorded'}"]
    out.append(f"module {top}({', '.join(ports)});")
    for p in ports:
        out.append(f"  input {p};")
    nets = set()
    for l in des.luts:
        nets |= {l["z"], l["cout"]}
    for f in des.ffs:
        nets.add(f["q"])
    for n in sorted(nets):
        out.append(f"  wire {n};")
    for l in des.luts:
        out.append(f"  assign {l['z']} = (16'h{l['init']:04x} >> {{{l['d']}, {l['c']}, {l['b']}, {l['a']}}}) & 1'b1;")
        out.append(f"  assign {l['cout']} = (16'h{l['init']:04x} >> {{1'b0, {l['cin']}, {l['b']}, {l['a']}}}) & 1'b1;")
    for f in des.ffs:
        clk = f"{f['q']}_clk"
        out.append(f"  wire {clk} = {'~' if f['clk_inv'] else ''}{f['clk']};")
        out.append(f"  reg {f['q']}_r = 1'b0;")
        out.append(f"  assign {f['q']} = {f['q']}_r;")
        out.append(f"  always @(posedge {clk} or negedge {f['clrn']})")
        out.append(f"    if (!{f['clrn']}) {f['q']}_r <= 1'b0;")
        out.append(f"    else if ({f['ena']}) {f['q']}_r <= {f['sclr']} ? 1'b0 : {f['sload']} ? {f['asdata']} : {f['d']};")
    out.append("endmodule")
    return "\n".join(out) + "\n"
