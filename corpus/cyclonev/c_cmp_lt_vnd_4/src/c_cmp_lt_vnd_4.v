module c_cmp_lt_vnd_4 (a, b, y);
  input [3:0] a, b;
  output y;
  lpm_compare #(.lpm_width(4), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .alb(y));
endmodule
