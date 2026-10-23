// Two independent clock domains, a counter in each, plus a 2-FF crossing.
module two_clocks(input clka, input clkb, output reg [3:0] ca, output reg [3:0] cb,
                  output reg sync_b);
  reg meta;
  always @(posedge clka) ca <= ca + 4'd1;
  always @(posedge clkb) cb <= cb + 4'd1;
  always @(posedge clkb) begin meta <= ca[3]; sync_b <= meta; end
endmodule
