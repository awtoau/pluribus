module c_mux4_vnd_1 (a, b, c, d, s, y);
  input [0:0] a, b, c, d;
  input [1:0] s;
  output [0:0] y;
  lpm_mux #(.lpm_width(1), .lpm_size(4), .lpm_widths(2)) u (.data({d, c, b, a}), .sel(s), .result(y));
endmodule
