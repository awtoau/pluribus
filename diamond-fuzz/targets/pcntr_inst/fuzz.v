module fuzz (
    input wire clk, input wire stdby_in,
    output wire out0
);

wire gnd = 1'b0;
wire stdby_w, stop_w, sflag_w;
PCNTR u0 (
    .CLK(clk), .USERTIMEOUT(gnd), .USERSTDBY(stdby_in), .CLRFLAG(gnd),
    .CFGWAKE(gnd), .CFGSTDBY(gnd),
    .STDBY(stdby_w), .STOP(stop_w), .SFLAG(sflag_w)
);
reg out0_r;
always @(posedge clk) out0_r <= stdby_w ^ stop_w ^ sflag_w;
assign out0 = out0_r;

endmodule
