module c_mux4_vnd_16 (a, b, c, d, s, y);
  input [15:0] a, b, c, d;
  input [1:0] s;
  output [15:0] y;
  lpm_mux #(.lpm_width(16), .lpm_size(4), .lpm_widths(2)) u (.data({d, c, b, a}), .sel(s), .result(y));
endmodule
