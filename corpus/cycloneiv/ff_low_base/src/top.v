module top(input a, b, clk, output q);
  wire n;
  cycloneive_lcell_comb #(.lut_mask(16'h8888), .sum_lutc_input("datac"), .dont_touch("on"))
    lut (.dataa(a), .datab(b), .combout(n));
  dffeas #(.power_up("low"), .is_wysiwyg("true")) r (.d(n), .clk(clk), .q(q));
endmodule
