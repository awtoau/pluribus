module top(input D, D2, output y0, output yf1, output yf2);
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKA (.dataa(D), .datab(D2), .combout(KA));
  wire E;
  cycloneiv_lcell_comb #(.lut_mask(16'h8888), .sum_lutc_input("datac"), .dont_touch("on"))
    sE (.dataa(D), .datab(D2), .combout(E));
  wire E2;
  cycloneiv_lcell_comb #(.lut_mask(16'h7777), .sum_lutc_input("datac"), .dont_touch("on"))
    sE2 (.dataa(D), .datab(D2), .combout(E2));
  wire l0_o, q0;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    l0 (.dataa(D), .combout(l0_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) r0 (.d(l0_o), .q(q0), .clk(KA), .ena(E));
  wire fl_o, fq1, fq2;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    fl (.dataa(D), .combout(fl_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far1 (.d(fl_o), .q(fq1), .clk(KA), .ena(E));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far2 (.d(fl_o), .q(fq2), .clk(KA), .ena(E2));
  assign y0 = q0;
  assign yf1 = fq1;
  assign yf2 = fq2;
endmodule
