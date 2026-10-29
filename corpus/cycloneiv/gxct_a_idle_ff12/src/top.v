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
  wire u5_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u5 (.dataa(u4_q), .combout(u5_o));
  wire u5_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f5 (.d(u5_o), .q(u5_q), .clk(KA));
  wire u6_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u6 (.dataa(u5_q), .combout(u6_o));
  wire u6_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f6 (.d(u6_o), .q(u6_q), .clk(KA));
  wire u7_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u7 (.dataa(u6_q), .combout(u7_o));
  wire u7_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f7 (.d(u7_o), .q(u7_q), .clk(KA));
  wire u8_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u8 (.dataa(u7_q), .combout(u8_o));
  wire u8_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f8 (.d(u8_o), .q(u8_q), .clk(KA));
  wire u9_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u9 (.dataa(u8_q), .combout(u9_o));
  wire u9_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f9 (.d(u9_o), .q(u9_q), .clk(KA));
  wire u10_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u10 (.dataa(u9_q), .combout(u10_o));
  wire u10_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f10 (.d(u10_o), .q(u10_q), .clk(KA));
  wire u11_o;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    u11 (.dataa(u10_q), .combout(u11_o));
  wire u11_q;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) f11 (.d(u11_o), .q(u11_q), .clk(KA));
  wire fl_o, fq1, fq2;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    fl (.dataa(D), .combout(fl_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far1 (.d(fl_o), .q(fq1), .clk(KA));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far2 (.d(fl_o), .q(fq2), .clk(KA));
  assign yc = u11_q;
  assign yf1 = fq1;
  assign yf2 = fq2;
endmodule
