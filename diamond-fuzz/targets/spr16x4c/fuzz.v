module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire [3:0] do_w;
SPR16X4C u0 (
    .DI3(gnd), .DI2(gnd), .DI1(gnd), .DI0(gnd),
    .AD3(gnd), .AD2(gnd), .AD1(gnd), .AD0(gnd),
    .WRE(gnd), .CK(clk),
    .DO3(do_w[3]), .DO2(do_w[2]), .DO1(do_w[1]), .DO0(do_w[0])
);
reg [3:0] q;
always @(posedge clk) q <= do_w;
assign out0 = ^q;

endmodule
