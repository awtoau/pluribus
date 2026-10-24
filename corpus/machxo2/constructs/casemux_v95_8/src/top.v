module top (clk, a, b, s, y);
  input clk;
  input [7:0] a;
  input [7:0] b;
  input [1:0] s;
  output [7:0] y;
  reg [7:0] y;
  always @(posedge clk) begin
    case (s)
      2'd0: y <= a;
      2'd1: y <= b;
      2'd2: y <= a & b;
      default: y <= a ^ b;
    endcase
  end
endmodule
