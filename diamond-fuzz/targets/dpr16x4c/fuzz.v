module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire [3:0] do_w;
DPR16X4C u0 (
    .DI3(gnd), .DI2(gnd), .DI1(gnd), .DI0(gnd),
    .WAD3(gnd), .WAD2(gnd), .WAD1(gnd), .WAD0(gnd),
    .WRE(gnd), .WCK(clk),
    .RAD3(gnd), .RAD2(gnd), .RAD1(gnd), .RAD0(gnd),
    .DO3(do_w[3]), .DO2(do_w[2]), .DO1(do_w[1]), .DO0(do_w[0])
);
reg [3:0] q;
always @(posedge clk) q <= do_w;
assign out0 = ^q;

endmodule
