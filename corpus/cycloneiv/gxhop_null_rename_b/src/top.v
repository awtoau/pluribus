module top(output y);
  wire u0_or;
  cycloneiv_lcell_comb #(.lut_mask(16'h0000), .sum_lutc_input("datac"), .dont_touch("on"))
    u0r (.combout(u0_or));
  cycloneiv_lcell_comb #(.lut_mask(16'hFFFF), .sum_lutc_input("datac"), .dont_touch("on"))
    u1r (.combout(y));
endmodule
