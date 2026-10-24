module top (clk, en, s, y);
  input clk;
  input en;
  input s;
  output [1:0] y;
  reg [1:0] y;
  always @(posedge clk) begin
    y <= 0;
    if (en) y[s] <= 1'b1;
  end
endmodule
