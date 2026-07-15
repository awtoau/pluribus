module fuzz(input wire clk,output wire out0);
 wire g=1'b0; wire [17:0] o;
 PDPW8KC #(.DATA_WIDTH_W(9),.DATA_WIDTH_R(2),.REGMODE("OUTREG"),.INITVAL_00("0x00000000000000000000000000000000000000000000000000000000000000000000000000000000")
) u0 (
    .CLKW(clk),.CEW(g),.CSW2(g),.CSW1(g),.CSW0(g),.RST(g),
    .ADW8(g),.ADW7(g),.ADW6(g),.ADW5(g),.ADW4(g),.ADW3(g),.ADW2(g),.ADW1(g),.ADW0(g),
    .DI17(g),.DI16(g),.DI15(g),.DI14(g),.DI13(g),.DI12(g),.DI11(g),.DI10(g),.DI9(g),
    .DI8(g),.DI7(g),.DI6(g),.DI5(g),.DI4(g),.DI3(g),.DI2(g),.DI1(g),.DI0(g),
    .CLKR(clk),.CER(g),.OCER(g),.CSR2(g),.CSR1(g),.CSR0(g),
    .ADR10(g),.ADR9(g),.ADR8(g),.ADR7(g),.ADR6(g),.ADR5(g),.ADR4(g),.ADR3(g),.ADR2(g),.ADR1(g),.ADR0(g),
    .DO17(o[17]),.DO16(o[16]),.DO15(o[15]),.DO14(o[14]),.DO13(o[13]),.DO12(o[12]),.DO11(o[11]),
    .DO10(o[10]),.DO9(o[9]),.DO8(o[8]),.DO7(o[7]),.DO6(o[6]),.DO5(o[5]),.DO4(o[4]),.DO3(o[3]),
    .DO2(o[2]),.DO1(o[1]),.DO0(o[0])
);
 reg r; always @(posedge clk) r<=^o; assign out0=r;
endmodule
