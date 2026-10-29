module top(input ina, output y);
  wire t_o, q;
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKA (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(KA));
  wire KB;
  cycloneiv_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on"))
    sKB (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(KB));
  wire E;
  cycloneiv_lcell_comb #(.lut_mask(16'h8888), .sum_lutc_input("datac"), .dont_touch("on"))
    sE (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(E));
  wire C;
  cycloneiv_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input("datac"), .dont_touch("on"))
    sC (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(C));
  wire S;
  cycloneiv_lcell_comb #(.lut_mask(16'hEEEE), .sum_lutc_input("datac"), .dont_touch("on"))
    sS (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(S));
  wire L;
  cycloneiv_lcell_comb #(.lut_mask(16'h1111), .sum_lutc_input("datac"), .dont_touch("on"))
    sL (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(L));
  wire M;
  cycloneiv_lcell_comb #(.lut_mask(16'hCCCC), .sum_lutc_input("datac"), .dont_touch("on"))
    sM (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(M));
  cycloneiv_lcell_comb #(.lut_mask(16'h0282), .sum_lutc_input("datac"), .dont_touch("on"))
    t (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(t_o));
  assign y = t_o;
endmodule
