module c_mux2_vnd_8 (a, b, s, y);
  input [7:0] a, b;
  input s;
  output [7:0] y;
  lpm_mux #(.lpm_width(8), .lpm_size(2), .lpm_widths(1)) u (.data({b, a}), .sel(s), .result(y));
endmodule
