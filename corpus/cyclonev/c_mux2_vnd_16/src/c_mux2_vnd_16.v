module c_mux2_vnd_16 (a, b, s, y);
  input [15:0] a, b;
  input s;
  output [15:0] y;
  lpm_mux #(.lpm_width(16), .lpm_size(2), .lpm_widths(1)) u (.data({b, a}), .sel(s), .result(y));
endmodule
