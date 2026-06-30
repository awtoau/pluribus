module fuzz (
    input wire clk,
    output wire out0
);

wire sederr_w, seddone_w, sedinprog_w, sedclkout_w;
SEDFB u0 (
    .SEDERR(sederr_w), .SEDDONE(seddone_w), .SEDINPROG(sedinprog_w), .SEDCLKOUT(sedclkout_w)
);
reg out0_r;
always @(posedge clk) out0_r <= sederr_w ^ seddone_w ^ sedinprog_w;
assign out0 = out0_r;

endmodule
