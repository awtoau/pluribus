module top(input ina, output y, output y2);
  wire u0_o;
  cycloneiv_lcell_comb #(.lut_mask(16'h0000), .sum_lutc_input("datac"), .dont_touch("on"))
    u0 (.combout(u0_o));
  cycloneiv_lcell_comb #(.lut_mask(16'h0000), .sum_lutc_input("datac"), .dont_touch("on"))
    u1 (.dataa(u0_o), .combout(y));
  cycloneiv_lcell_comb #(.lut_mask(16'hFFFF), .sum_lutc_input("datac"), .dont_touch("on"))
    u2 (.combout(y2));
endmodule
