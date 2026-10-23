module c_mux2_vnd_4 (a, b, s, y);
  input [3:0] a, b;
  input s;
  output [3:0] y;
  lpm_mux #(.lpm_width(4), .lpm_size(2), .lpm_widths(1)) u (.data({b, a}), .sel(s), .result(y));
endmodule
