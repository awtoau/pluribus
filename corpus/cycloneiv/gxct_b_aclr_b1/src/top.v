module top(input D, D2, output y0, output yf1, output yf2);
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKA (.dataa(D), .datab(D2), .combout(KA));
  wire C;
  cycloneiv_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input("datac"), .dont_touch("on"))
    sC (.dataa(D), .datab(D2), .combout(C));
  wire C2;
  cycloneiv_lcell_comb #(.lut_mask(16'h9999), .sum_lutc_input("datac"), .dont_touch("on"))
    sC2 (.dataa(D), .datab(D2), .combout(C2));
  wire l0_o, q0;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    l0 (.dataa(D), .combout(l0_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) r0 (.d(l0_o), .q(q0), .clk(KA));
  wire fl_o, fq1, fq2;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    fl (.dataa(D), .combout(fl_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far1 (.d(fl_o), .q(fq1), .clk(KA), .clrn(C));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far2 (.d(fl_o), .q(fq2), .clk(KA), .clrn(C2));
  assign y0 = q0;
  assign yf1 = fq1;
  assign yf2 = fq2;
endmodule
