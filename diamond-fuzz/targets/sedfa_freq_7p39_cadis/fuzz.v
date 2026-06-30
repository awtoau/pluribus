module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire sedout_w;
SEDFA #(
    .SED_CLK_FREQ("7.39"),
    .CHECKALWAYS("DISABLED")
) u0 (
    .SEDENABLE(1'b1), .SEDSTDBY(gnd),
    .SEDFRCERR(gnd), .SEDSTART(gnd),
    .SEDDONE(sedout_w), .SEDERR(), .SEDINPROG(), .SEDCLKOUT()
);
reg out0_r;
always @(posedge clk) out0_r <= sedout_w;
assign out0 = out0_r;

endmodule
