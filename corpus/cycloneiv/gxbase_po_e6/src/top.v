module top(input a, output y);
  cycloneiv_lcell_comb #(.lut_mask(16'hAAAA), .sum_lutc_input("datac"), .dont_touch("on"))
    l1 (.dataa(a), .combout(y));
endmodule
