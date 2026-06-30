module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire [8:0] do_w;
SP8KC #(
    .DATA_WIDTH(9),
    .REGMODE("NOREG"),
    .INITVAL_00("0x00000000000000000000000000000000000000000000000000000000000000000000000000000000")
) u0 (
    .CLK(clk), .CE(gnd), .OCE(gnd), .WE(gnd), .CS2(gnd), .CS1(gnd), .CS0(gnd), .RST(gnd),
    .AD10(gnd), .AD9(gnd), .AD8(gnd), .AD7(gnd), .AD6(gnd),
    .AD5(gnd),  .AD4(gnd), .AD3(gnd), .AD2(gnd), .AD1(gnd), .AD0(gnd),
    .DI8(gnd), .DI7(gnd), .DI6(gnd), .DI5(gnd), .DI4(gnd),
    .DI3(gnd), .DI2(gnd), .DI1(gnd), .DI0(gnd),
    .DO8(do_w[8]), .DO7(do_w[7]), .DO6(do_w[6]), .DO5(do_w[5]),
    .DO4(do_w[4]), .DO3(do_w[3]), .DO2(do_w[2]), .DO1(do_w[1]), .DO0(do_w[0])
);
reg out0_r;
always @(posedge clk) out0_r <= ^do_w;
assign out0 = out0_r;

endmodule
