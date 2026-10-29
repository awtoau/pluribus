module top(input D, D2, output yc, output yf1, output yf2);
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKA (.dataa(D), .datab(D2), .combout(KA));
  wire u0_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u0 (.dataa(D), .combout(u0_o));
  wire u1_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u1 (.dataa(u0_o), .combout(u1_o));
  wire u2_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u2 (.dataa(u1_o), .combout(u2_o));
  wire fl_o, fq1, fq2;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    fl (.dataa(D), .combout(fl_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far1 (.d(fl_o), .q(fq1), .clk(KA));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far2 (.d(fl_o), .q(fq2), .clk(KA));
  assign yc = u2_o;
  assign yf1 = fq1;
  assign yf2 = fq2;
endmodule
