module c_casemux_vnd_1 (a, b, c, s, y);
  input [0:0] a, b, c;
  input [1:0] s;
  output [0:0] y;
  reg [0:0] y;
  always @(a or b or c or s)
    case (s) // synthesis full_case parallel_case
      2'd0: y = a;
      2'd1: y = b;
      2'd2: y = c;
    endcase
endmodule
