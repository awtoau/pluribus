module top (input clk, input d, output reg q);
  logic t;
  always @(posedge clk) begin t <= d; q <= t; end
endmodule
