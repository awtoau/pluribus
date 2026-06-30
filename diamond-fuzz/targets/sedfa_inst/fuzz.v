module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire sederr_w, seddone_w, sedinprog_w, sedclkout_w;
SEDFA u0 (
    .SEDSTDBY(gnd), .SEDENABLE(gnd), .SEDSTART(gnd), .SEDFRCERR(gnd),
    .SEDERR(sederr_w), .SEDDONE(seddone_w), .SEDINPROG(sedinprog_w), .SEDCLKOUT(sedclkout_w)
);
reg out0_r;
always @(posedge clk) out0_r <= sederr_w ^ seddone_w ^ sedinprog_w;
assign out0 = out0_r;

endmodule
