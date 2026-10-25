module c_latch_v95_1 (s, c, e, d, x, q1, q2, q3);
  input s, c, e, d, x;
  output q1, q2, q3;
  reg q1, q2;
  wire q3;
  always @* if (s & e) q1 = 1'b1; else if (c) q1 = 1'b0;
  always @* if (e) q2 = d;
  assign q3 = ~(q3 & x);
endmodule
