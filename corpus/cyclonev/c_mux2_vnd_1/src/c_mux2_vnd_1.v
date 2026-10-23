module c_mux2_vnd_1 (a, b, s, y);
  input [0:0] a, b;
  input s;
  output [0:0] y;
  lpm_mux #(.lpm_width(1), .lpm_size(2), .lpm_widths(1)) u (.data({b, a}), .sel(s), .result(y));
endmodule
