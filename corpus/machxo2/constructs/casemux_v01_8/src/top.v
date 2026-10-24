module top (
    input [0:0] clk,
    input [7:0] a,
    input [7:0] b,
    input [1:0] s,
    output reg [7:0] y
);
  reg [7:0] m;
  always @* begin
    case (s)
      2'd0: m = a;
      2'd1: m = b;
      2'd2: m = a & b;
      default: m = a ^ b;
    endcase
  end
  always @(posedge clk) y <= m;
endmodule
