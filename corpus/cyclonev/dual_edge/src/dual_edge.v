// Same clock, one bank of registers on each edge.
module dual_edge(input clk, input [3:0] d, output reg [3:0] qp, output reg [3:0] qn);
  always @(posedge clk) qp <= d;
  always @(negedge clk) qn <= qp ^ d;
endmodule
