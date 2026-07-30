// SEDGA: SED_CLK_FREQ=2.4 CHECKALWAYS=DISABLED DEV_DENSITY=12KU
module fuzz (
    input  wire clk,
    input  wire d0,
    output wire sedclkout,
    output wire seddone,
    output wire sedinprog,
    output wire sederr,
    output wire out0
);

SEDGA #(
    .SED_CLK_FREQ("2.4"),
    .CHECKALWAYS("DISABLED"),
    .DEV_DENSITY("12KU")
) u_sedga (
    .SEDENABLE (1'b0),
    .SEDSTART  (1'b0),
    .SEDFRCERR (1'b0),
    .SEDCLKOUT (sedclkout),
    .SEDDONE   (seddone),
    .SEDINPROG (sedinprog),
    .SEDERR    (sederr)
);

reg out0_r;
always @(posedge clk) out0_r <= d0;
assign out0 = out0_r;

endmodule
