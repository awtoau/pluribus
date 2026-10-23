module c_comb_vnd_8 (a, b, c, y);
  input [7:0] a, b, c;
  output [7:0] y;
  (* keep *) wire [7:0] t1 = a & b;
  (* keep *) wire [7:0] t2 = ~a & c;
  (* keep *) wire [7:0] t3 = t1 | t2;
  (* keep *) wire [7:0] t4 = b | c;
  assign y = t3 ^ t4;
endmodule
