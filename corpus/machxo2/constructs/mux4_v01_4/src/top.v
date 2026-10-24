module top (
    input [0:0] clk,
    input [3:0] a,
    input [3:0] b,
    input [3:0] c,
    input [3:0] d,
    input [1:0] s,
    output reg [3:0] y
);
  reg [3:0] m;
  always @* begin
    case (s)
      2'd0: m = a;
      2'd1: m = b;
      2'd2: m = c;
      default: m = d;
    endcase
  end
  always @(posedge clk) y <= m;
endmodule
