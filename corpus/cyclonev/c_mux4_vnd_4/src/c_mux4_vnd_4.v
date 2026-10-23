module c_mux4_vnd_4 (a, b, c, d, s, y);
  input [3:0] a, b, c, d;
  input [1:0] s;
  output [3:0] y;
  lpm_mux #(.lpm_width(4), .lpm_size(4), .lpm_widths(2)) u (.data({d, c, b, a}), .sel(s), .result(y));
endmodule
