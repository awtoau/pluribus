module top(input ina, output y);
  wire t_o, q;
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKAr (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(KA));
  wire KB;
  cycloneiv_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on"))
    sKBr (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(KB));
  wire E;
  cycloneiv_lcell_comb #(.lut_mask(16'h8888), .sum_lutc_input("datac"), .dont_touch("on"))
    sEr (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(E));
  wire C;
  cycloneiv_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input("datac"), .dont_touch("on"))
    sCr (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(C));
  wire S;
  cycloneiv_lcell_comb #(.lut_mask(16'hEEEE), .sum_lutc_input("datac"), .dont_touch("on"))
    sSr (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(S));
  wire L;
  cycloneiv_lcell_comb #(.lut_mask(16'h1111), .sum_lutc_input("datac"), .dont_touch("on"))
    sLr (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(L));
  wire M;
  cycloneiv_lcell_comb #(.lut_mask(16'hCCCC), .sum_lutc_input("datac"), .dont_touch("on"))
    sMr (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(M));
  cycloneiv_lcell_comb #(.lut_mask(16'h0800), .sum_lutc_input("datac"), .dont_touch("on"))
    tr (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(t_o));
  assign y = t_o;
endmodule
