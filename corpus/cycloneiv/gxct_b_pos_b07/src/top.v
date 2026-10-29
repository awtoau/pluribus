module top(input D, D2, output y7, output yf1, output yf2);
  wire KA;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    sKA (.dataa(D), .datab(D2), .combout(KA));
  wire KB;
  cycloneiv_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on"))
    sKB (.dataa(D), .datab(D2), .combout(KB));
  wire E;
  cycloneiv_lcell_comb #(.lut_mask(16'h8888), .sum_lutc_input("datac"), .dont_touch("on"))
    sE (.dataa(D), .datab(D2), .combout(E));
  wire C;
  cycloneiv_lcell_comb #(.lut_mask(16'h6666), .sum_lutc_input("datac"), .dont_touch("on"))
    sC (.dataa(D), .datab(D2), .combout(C));
  wire S;
  cycloneiv_lcell_comb #(.lut_mask(16'hEEEE), .sum_lutc_input("datac"), .dont_touch("on"))
    sS (.dataa(D), .datab(D2), .combout(S));
  wire L;
  cycloneiv_lcell_comb #(.lut_mask(16'h1111), .sum_lutc_input("datac"), .dont_touch("on"))
    sL (.dataa(D), .datab(D2), .combout(L));
  wire M;
  cycloneiv_lcell_comb #(.lut_mask(16'hCCCC), .sum_lutc_input("datac"), .dont_touch("on"))
    sM (.dataa(D), .datab(D2), .combout(M));
  wire l7_o, q7;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    l7 (.dataa(D), .combout(l7_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) r7 (.d(l7_o), .q(q7), .clk(KA));
  wire fl_o, fq1, fq2;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    fl (.dataa(D), .combout(fl_o));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far1 (.d(fl_o), .q(fq1), .clk(KB), .ena(E), .clrn(C), .sclr(S), .sload(L), .asdata(M));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) far2 (.d(fl_o), .q(fq2), .clk(KA));
  assign y7 = q7;
  assign yf1 = fq1;
  assign yf2 = fq2;
endmodule
