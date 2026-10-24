module top (input clk, input go, output reg q);
  enum reg [1:0] {A=0, B=1} st;
  always @(posedge clk) begin if (go) st <= B; q <= (st == B); end
endmodule
