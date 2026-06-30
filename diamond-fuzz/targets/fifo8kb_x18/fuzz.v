module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire [17:0] q_w;
wire ef_w, aef_w, af_w, ff_w;
FIFO8KB #(
    .DATA_WIDTH_W(18),
    .DATA_WIDTH_R(18),
    .REGMODE("NOREG"),
    .GSR("DISABLED"),
    .RESETMODE("ASYNC"),
    .CSDECODE_W("0b00"),
    .CSDECODE_R("0b00"),
    .ASYNC_RESET_RELEASE("SYNC")
) u0 (
    .CLKW(clk), .WE(gnd), .CSW1(gnd), .CSW0(gnd), .RST(gnd), .FULLI(gnd),
    .DI17(gnd), .DI16(gnd), .DI15(gnd), .DI14(gnd), .DI13(gnd),
    .DI12(gnd), .DI11(gnd), .DI10(gnd), .DI9(gnd),
    .DI8(gnd),  .DI7(gnd),  .DI6(gnd),  .DI5(gnd),
    .DI4(gnd),  .DI3(gnd),  .DI2(gnd),  .DI1(gnd),  .DI0(gnd),
    .CLKR(clk), .RE(gnd), .ORE(gnd), .CSR1(gnd), .CSR0(gnd), .RPRST(gnd), .EMPTYI(gnd),
    .DO17(q_w[17]), .DO16(q_w[16]), .DO15(q_w[15]), .DO14(q_w[14]),
    .DO13(q_w[13]), .DO12(q_w[12]), .DO11(q_w[11]), .DO10(q_w[10]),
    .DO9(q_w[9]),   .DO8(q_w[8]),   .DO7(q_w[7]),   .DO6(q_w[6]),
    .DO5(q_w[5]),   .DO4(q_w[4]),   .DO3(q_w[3]),   .DO2(q_w[2]),
    .DO1(q_w[1]),   .DO0(q_w[0]),
    .EF(ef_w), .AEF(aef_w), .AFF(af_w), .FF(ff_w)
);
reg out0_r;
always @(posedge clk) out0_r <= ef_w ^ ff_w ^ ^q_w;
assign out0 = out0_r;

endmodule
