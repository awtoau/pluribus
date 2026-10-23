module c_comb_vnd_1 (a, b, c, y);
  input [0:0] a, b, c;
  output [0:0] y;
  (* keep *) wire [0:0] t1 = a & b;
  (* keep *) wire [0:0] t2 = ~a & c;
  (* keep *) wire [0:0] t3 = t1 | t2;
  (* keep *) wire [0:0] t4 = b | c;
  assign y = t3 ^ t4;
endmodule
