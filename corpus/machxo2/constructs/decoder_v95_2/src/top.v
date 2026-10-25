module top (clk, en, s, y);
  input clk;
  input en;
  input [1:0] s;
  output [3:0] y;
  reg [3:0] y;
  always @(posedge clk) begin
    y <= 0;
    if (en) y[s] <= 1'b1;
  end
endmodule
