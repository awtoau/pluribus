module top (clk, en, s, y);
  input clk;
  input en;
  input [2:0] s;
  output [7:0] y;
  reg [7:0] y;
  always @(posedge clk) begin
    y <= 0;
    if (en) y[s] <= 1'b1;
  end
endmodule
