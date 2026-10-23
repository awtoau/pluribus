// clkg forced onto a global clock, clkr onto a regional clock (design.toml qsf).
module clock_promotion(input clkg, input clkr, input [3:0] d, output reg [3:0] qg,
                       output reg [3:0] qr);
  always @(posedge clkg) qg <= d;
  always @(posedge clkr) qr <= qg;
endmodule
