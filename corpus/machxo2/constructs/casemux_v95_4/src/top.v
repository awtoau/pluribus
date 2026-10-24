module top (clk, a, b, s, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  input [1:0] s;
  output [3:0] y;
  reg [3:0] y;
  always @(posedge clk) begin
    case (s)
      2'd0: y <= a;
      2'd1: y <= b;
      2'd2: y <= a & b;
      default: y <= a ^ b;
    endcase
  end
endmodule
