// Baseline: no SEDGA instance.  Reference for all SED bit diffs.
module fuzz (
    input  wire clk,
    input  wire d0,
    output wire out0
);

reg out0_r;
always @(posedge clk) out0_r <= d0;
assign out0 = out0_r;

endmodule
