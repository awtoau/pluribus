module top(input a, b, c, d, output y);
  cycloneive_lcell_comb #(.lut_mask(16'h8000), .sum_lutc_input("datac"), .dont_touch("on"))
    lut (.dataa(a), .datab(b), .datac(c), .datad(d), .combout(y));
endmodule
