module top(input a, output y, output y1);
  wire n;
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    l1 (.dataa(a), .combout(n));
  cycloneiv_lcell_comb #(.lut_mask(16'h5555), .sum_lutc_input("datac"), .dont_touch("on"))
    l2 (.dataa(n), .combout(y));
  assign y1 = n;
endmodule
