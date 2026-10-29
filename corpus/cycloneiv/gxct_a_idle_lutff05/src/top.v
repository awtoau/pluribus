module top(input D, D2, output yc, output yf1, output yf2);
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKA (.dataa(D), .datab(D2), .combout(KA));
  wire u0_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u0 (.dataa(D), .combout(u0_o));
  wire u0_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f0 (.d(u0_o), .q(u0_q), .clk(KA));
  wire u1_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u1 (.dataa(u0_q), .combout(u1_o));
  wire u1_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f1 (.d(u1_o), .q(u1_q), .clk(KA));
  wire u2_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u2 (.dataa(u1_q), .combout(u2_o));
  wire u2_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f2 (.d(u2_o), .q(u2_q), .clk(KA));
  wire u3_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u3 (.dataa(u2_q), .combout(u3_o));
  wire u3_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f3 (.d(u3_o), .q(u3_q), .clk(KA));
  wire u4_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u4 (.dataa(u3_q), .combout(u4_o));
  wire u4_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f4 (.d(u4_o), .q(u4_q), .clk(KA));
  wire fl_o, fq1, fq2;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    fl (.dataa(D), .combout(fl_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far1 (.d(fl_o), .q(fq1), .clk(KA));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far2 (.d(fl_o), .q(fq2), .clk(KA));
  assign yc = u4_q;
  assign yf1 = fq1;
  assign yf2 = fq2;
endmodule
