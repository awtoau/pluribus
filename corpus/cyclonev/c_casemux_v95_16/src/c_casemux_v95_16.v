module c_casemux_v95_16 (a, b, c, s, y);
  input [15:0] a, b, c;
  input [1:0] s;
  output [15:0] y;
  reg [15:0] y;
  always @(a or b or c or s)
    case (s)
      2'd0: y = a;
      2'd1: y = b;
      2'd2: y = c;
      default: y = 16'd0;
    endcase
endmodule
