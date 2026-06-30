module fuzz (
    input wire clk,
    input wire d,
    output wire out0
);

wire gnd = 1'b0;
wire stdby_w, stop_w, sflag_w;
PCNTR #(
    .STDBYOPT("USER_CFG"),
    .WAKEUP("CFG"),
    .TIMEOUT("COUNTER"),
    .POROFF("FALSE"),
    .BGOFF("FALSE")
) u0 (
    .CLK(clk), .USERSTDBY(d), .USERTIMEOUT(d), .CLRFLAG(d),
    .CFGWAKE(gnd), .CFGSTDBY(gnd),
    .STDBY(stdby_w), .STOP(stop_w), .SFLAG(sflag_w)
);
reg out0_r;
always @(posedge clk) out0_r <= stdby_w ^ stop_w;
assign out0 = out0_r;

endmodule
