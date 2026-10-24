module top (input clk, input d, output reg q);
  localparam W = $clog2(10);
  reg [W-1:0] r;
  always @(posedge clk) begin r <= {W{d}}; q <= r[0]; end
endmodule
