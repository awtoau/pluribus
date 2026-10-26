module top(input a, b, d, e, output y0, y1);
  wire co0, co1;
  cycloneive_lcell_comb #(.lut_mask(16'h6688), .sum_lutc_input("datac"), .dont_touch("on"))
    l0 (.dataa(a), .datab(b), .datac(1'b0), .datad(1'b1), .combout(y0), .cout(co0));
  cycloneive_lcell_comb #(.lut_mask(16'h9617), .sum_lutc_input("datac"), .dont_touch("on"))
    l1 (.dataa(d), .datab(e), .datac(1'b0), .datad(1'b1), .cin(1'b0), .combout(y1), .cout(co1));
endmodule
