module top(input D, D2, output y0, output yf1, output yf2);
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKA (.dataa(D), .datab(D2), .combout(KA));
  wire L;
  cycloneiv_lcell_comb #(.lut_mask(16'h1111), .sum_lutc_input("datac"), .dont_touch("on"))
    sL (.dataa(D), .datab(D2), .combout(L));
  wire M;
  cycloneiv_lcell_comb #(.lut_mask(16'hCCCC), .sum_lutc_input("datac"), .dont_touch("on"))
    sM (.dataa(D), .datab(D2), .combout(M));
  // l0: comb LUT whose DATAC pin is r0's own Q (LE_USE_REGISTER_FEEDBACK, F-010's validated comb-pin case).
  // r0's sload/ASDATA is separately driven by M (a real, different signal, NOT q0) -- the #183 interaction:
  // one LE where the register-feedback bit is set AND the independent sload mux selects a different source.
  wire l0_o, q0;
  cycloneiv_lcell_comb #(.lut_mask(16'h9688), .sum_lutc_input("datac"), .dont_touch("on"))
    l0 (.dataa(D), .datab(D2), .datac(q0), .datad(M), .combout(l0_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) r0 (.d(l0_o), .q(q0), .clk(KA), .sload(L), .asdata(M));
  wire fl_o, fq1, fq2;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    fl (.dataa(D), .combout(fl_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far1 (.d(fl_o), .q(fq1), .clk(KA), .sload(L), .asdata(M));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far2 (.d(fl_o), .q(fq2), .clk(KA));
  assign y0 = q0;
  assign yf1 = fq1;
  assign yf2 = fq2;
endmodule
