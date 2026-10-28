module top(output y);
  cycloneiv_lcell_comb #(.lut_mask(16'hFFFF), .sum_lutc_input("datac"), .dont_touch("on"))
    u0 (.combout(y));
endmodule
