module top(input ina, output y);
  wire u0_o;
  cycloneiv_lcell_comb #(.lut_mask(16'h0004), .sum_lutc_input("datac"), .dont_touch("on"))
    u0 (.dataa(ina), .datab(ina), .datac(ina), .datad(ina), .combout(u0_o));
  cycloneiv_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on"))
    u1 (.dataa(ina), .datab(u0_o), .datac(ina), .datad(ina), .combout(y));
endmodule
