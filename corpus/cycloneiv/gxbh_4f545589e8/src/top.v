module top(input ina, input inb, input inc, input ind, output y);
  wire u0_o;
  cycloneiv_lcell_comb #(.lut_mask(16'h0000), .sum_lutc_input("datac"), .dont_touch("on"))
    u0 (.dataa(ina), .datab(inb), .datac(inc), .datad(ind), .combout(u0_o));
  cycloneiv_lcell_comb #(.lut_mask(16'h0004), .sum_lutc_input("datac"), .dont_touch("on"))
    u1 (.datab(u0_o), .dataa(ina), .datac(inc), .datad(ind), .combout(y));
endmodule
