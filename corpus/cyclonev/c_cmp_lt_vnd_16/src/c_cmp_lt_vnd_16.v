module c_cmp_lt_vnd_16 (a, b, y);
  input [15:0] a, b;
  output y;
  lpm_compare #(.lpm_width(16), .lpm_representation("UNSIGNED")) u (.dataa(a), .datab(b), .alb(y));
endmodule
