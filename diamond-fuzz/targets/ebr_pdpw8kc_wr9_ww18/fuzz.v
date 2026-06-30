module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire [17:0] dout_w;
PDPW8KC #(
    .DATA_WIDTH_R(9), .DATA_WIDTH_W(18),
    .CSDECODE_R("0b111"), .CSDECODE_W("0b111"),
    .GSR("DISABLED"), .RESETMODE("SYNC")
) u0 (
    .CLKW(clk), .CEW(gnd), .CSW2(gnd), .CSW1(gnd), .CSW0(gnd), .RST(gnd),
    .CLKR(clk), .CER(gnd), .OCER(gnd), .CSR2(gnd), .CSR1(gnd), .CSR0(gnd),
    .ADW8(gnd),.ADW7(gnd),.ADW6(gnd),.ADW5(gnd),.ADW4(gnd),.ADW3(gnd),.ADW2(gnd),.ADW1(gnd),.ADW0(gnd),
    .ADR10(gnd),.ADR9(gnd),.ADR8(gnd),.ADR7(gnd),.ADR6(gnd),.ADR5(gnd),.ADR4(gnd),.ADR3(gnd),.ADR2(gnd),.ADR1(gnd),.ADR0(gnd),
    .DI17(gnd),.DI16(gnd),.DI15(gnd),.DI14(gnd),.DI13(gnd),.DI12(gnd),.DI11(gnd),.DI10(gnd),
    .DI9(gnd),.DI8(gnd),.DI7(gnd),.DI6(gnd),.DI5(gnd),.DI4(gnd),.DI3(gnd),.DI2(gnd),.DI1(gnd),.DI0(gnd),
    .DO17(dout_w[17]),.DO16(dout_w[16]),.DO15(dout_w[15]),.DO14(dout_w[14]),
    .DO13(dout_w[13]),.DO12(dout_w[12]),.DO11(dout_w[11]),.DO10(dout_w[10]),
    .DO9(dout_w[9]),.DO8(dout_w[8]),.DO7(dout_w[7]),.DO6(dout_w[6]),
    .DO5(dout_w[5]),.DO4(dout_w[4]),.DO3(dout_w[3]),.DO2(dout_w[2]),.DO1(dout_w[1]),.DO0(dout_w[0])
);
reg out0_r;
always @(posedge clk) out0_r <= ^dout_w;
assign out0 = out0_r;

endmodule
