"""Directed knob builds for Cyclone IV LE / FF mode bits (EP4CE6, WYSIWYG cells at fixed sites).

Each family varies ONE thing between its members, everything else (cells, sites, pins, masks)
is identical, so the CRAM diff is the knob plus the routing it forces.

carry_*  : LE pair (N0 -> N2) at LAB X5_Y5.
  carry_cin     N2 sum_lutc_input="cin",   cin = N0.cout
  carry_dcin    N2 sum_lutc_input="datac", cin = N0.cout   (link present, LUT ignores it)
  carry_dgnd    N2 sum_lutc_input="datac", cin = gnd       (no link)
  carry_cin_cout  as carry_cin but N2.cout also drives a third LE's cin (chain of three)
"""

PINS = ["PIN_28", "PIN_30", "PIN_31", "PIN_32", "PIN_33", "PIN_34", "PIN_38", "PIN_39", "PIN_42", "PIN_43",
        "PIN_44", "PIN_46"]


def carry_design(mode2, link, third=False):
    ins = ["a", "b", "d", "e"]
    v = ["module top(input a, b, d, e, output y0, y1" + (", y2" if third else "") + ");",
         "  wire co0, co1;",
         "  cycloneive_lcell_comb #(.lut_mask(16'h6688), .sum_lutc_input(\"datac\"), .dont_touch(\"on\"))",
         "    l0 (.dataa(a), .datab(b), .datac(1'b0), .datad(1'b1), .combout(y0), .cout(co0));",
         "  cycloneive_lcell_comb #(.lut_mask(16'h9617), .sum_lutc_input(\"%s\"), .dont_touch(\"on\"))" % mode2,
         "    l1 (.dataa(d), .datab(e), .datac(1'b0), .datad(1'b1), .cin(%s), .combout(y1), .cout(co1));" %
         ("co0" if link else "1'b0")]
    if third:
        v += ["  cycloneive_lcell_comb #(.lut_mask(16'h9617), .sum_lutc_input(\"cin\"), .dont_touch(\"on\"))",
              "    l2 (.dataa(a), .datab(e), .datac(1'b0), .datad(1'b1), .cin(co1), .combout(y2), .cout());"]
    v.append("endmodule")
    qsf = ["set_location_assignment LCCOMB_X5_Y5_N0 -to l0", "set_location_assignment LCCOMB_X5_Y5_N2 -to l1"]
    if third:
        qsf.append("set_location_assignment LCCOMB_X5_Y5_N4 -to l2")
    outs = ["y0", "y1"] + (["y2"] if third else [])
    qsf += [f"set_location_assignment {p} -to {n}" for p, n in zip(PINS, ins + outs)]
    return "\n".join(v) + "\n", qsf


def knob_specs():
    out = {}
    for name, mode, link, third in (("carry_cin", "cin", True, False), ("carry_dcin", "datac", True, False),
                                    ("carry_dgnd", "datac", False, False), ("carry_cin3", "cin", True, True)):
        v, q = carry_design(mode, link, third)
        out[f"knob_{name}"] = {"top": "top", "verilog": v, "qsf": q,
                               "purpose": f"carry knob {name}", "exercises": ["carry"]}
    return out
