module top(output y);
  wire u0_o;
  wire u2_o;
  cycloneiv_lcell_comb #(.lut_mask(16'h0000), .sum_lutc_input("datac"), .dont_touch("on"))
    u0 (.combout(u0_o));
  cycloneiv_lcell_comb #(.lut_mask(16'hFFFF), .sum_lutc_input("datac"), .dont_touch("on"))
    u2 (.datab(u0_o), .combout(u2_o));
  cycloneiv_lcell_comb #(.lut_mask(16'hFFFF), .sum_lutc_input("datac"), .dont_touch("on"))
    u1 (.datab(u0_o), .dataa(u2_o), .combout(y));
endmodule
