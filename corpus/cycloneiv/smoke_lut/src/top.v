module top(input a, b, c, d, clk, output y, q);
  wire n;
  cycloneive_lcell_comb #(.lut_mask(16'h6996), .sum_lutc_input("datac"), .dont_touch("on"))
    lut (.dataa(a), .datab(b), .datac(c), .datad(d), .combout(n));
  assign y = n;
  dffeas #(.power_up("low"), .is_wysiwyg("true")) r (.d(n), .clk(clk), .q(q));
endmodule
