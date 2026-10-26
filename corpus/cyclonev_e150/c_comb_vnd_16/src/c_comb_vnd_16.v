module c_comb_vnd_16 (a, b, c, y);
  input [15:0] a, b, c;
  output [15:0] y;
  (* keep *) wire [15:0] t1 = a & b;
  (* keep *) wire [15:0] t2 = ~a & c;
  (* keep *) wire [15:0] t3 = t1 | t2;
  (* keep *) wire [15:0] t4 = b | c;
  assign y = t3 ^ t4;
endmodule
