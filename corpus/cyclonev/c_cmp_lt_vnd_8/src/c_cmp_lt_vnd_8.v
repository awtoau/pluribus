module c_cmp_lt_vnd_8 (a, b, y);
  input [7:0] a, b;
  output y;
  lpm_compare #(.lpm_width(8), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .alb(y));
endmodule
