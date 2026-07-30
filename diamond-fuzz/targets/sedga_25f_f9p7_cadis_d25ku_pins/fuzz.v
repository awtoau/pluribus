// SEDGA: SED_CLK_FREQ=9.7 CHECKALWAYS=DISABLED DEV_DENSITY=25KU
module fuzz (
    input  wire clk,
    input  wire d0,
    input  wire sedenable,
    input  wire sedstart,
    input  wire sedfrcerr,
    output wire sedclkout,
    output wire seddone,
    output wire sedinprog,
    output wire sederr,
    output wire out0
);

SEDGA #(
    .SED_CLK_FREQ("9.7"),
    .CHECKALWAYS("DISABLED"),
    .DEV_DENSITY("25KU")
) u_sedga (
    .SEDENABLE (sedenable),
    .SEDSTART  (sedstart),
    .SEDFRCERR (sedfrcerr),
    .SEDCLKOUT (sedclkout),
    .SEDDONE   (seddone),
    .SEDINPROG (sedinprog),
    .SEDERR    (sederr)
);

reg out0_r;
always @(posedge clk) out0_r <= d0;
assign out0 = out0_r;

endmodule
