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
    out += ["  // 4-input LUT as a mux tree: an X select resolves when both branches agree (as the vendor model)",
            "  function lut4(input [15:0] m, input a, input b, input c, input d);",
            "    lut4 = d ? (c ? (b ? (a ? m[15] : m[14]) : (a ? m[13] : m[12])) : (b ? (a ? m[11] : m[10]) : (a ? m[9] : m[8])))",
            "             : (c ? (b ? (a ? m[7] : m[6]) : (a ? m[5] : m[4])) : (b ? (a ? m[3] : m[2]) : (a ? m[1] : m[0])));",
            "  endfunction"]
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
        out.append(f"  assign {l['z']} = lut4(16'h{l['init']:04x}, {l['a']}, {l['b']}, {l['c']}, {l['d']});")
        out.append(f"  assign {l['cout']} = lut4(16'h{l['init']:04x}, {l['a']}, {l['b']}, {l['cin']}, 1'b0);")
    for f in des.ffs:
        q = f["q"]
        inv = dict(f.get("inv", {}))
        inv["clk"] = f["clk_inv"]
        pin = {}
        for p in ("clk", "clrn", "ena", "sclr", "sload", "asdata", "d"):
            pin[p] = f"{q}_{p}"
            out.append(f"  wire {pin[p]} = {'~' if inv.get(p) else ''}{f[p]};")
        out.append(f"  reg {q}_t = 1'b0;   // register state (the vendor primitive output)")
        out.append(f"  reg {q}_r = 1'b0;   // visible q, one non-blocking step later (the vendor q_tmp_dly)")
        out.append(f"  reg {q}_p = 1'bx;")
        out.append(f"  assign {q} = {q}_r;")
        # as the vendor register primitive: async clear is a level, a capture needs a clean 0 -> 1
        # clock edge (an X -> 1 transition is ignored), ena must be 1; the state changes in the active
        # region and q follows by a non-blocking assignment, so zero-delay races resolve as in the vendor model
        out.append(f"  always @({pin['clk']} or {pin['clrn']}) begin")
        out.append(f"    if ({pin['clrn']} === 1'b0) {q}_t = 1'b0;")
        out.append(f"    else if ({q}_p === 1'b0 && {pin['clk']} === 1'b1 && {pin['ena']} === 1'b1)")
        out.append(f"      {q}_t = ({pin['sclr']} === 1'b1) ? 1'b0 : ({pin['sload']} === 1'b1) ? {pin['asdata']} : {pin['d']};")
        out.append(f"    {q}_p = {pin['clk']};")
        out.append("  end")
        out.append(f"  always @({q}_t) {q}_r <= {q}_t;")
    out.append("endmodule")
    return "\n".join(out) + "\n"
