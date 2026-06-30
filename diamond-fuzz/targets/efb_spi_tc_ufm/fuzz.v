module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire wbacko_w;
wire [7:0] wbdato_w;
EFB #(
    .EFB_I2C1("DISABLED"),
    .EFB_I2C2("DISABLED"),
    .EFB_SPI("ENABLED"),
    .EFB_TC("ENABLED"),
    .EFB_UFM("ENABLED"),
    .SPI_MODE("SLAVE"),
    .EFB_WB_CLK_FREQ("100.0")
) u0 (
    .WBCLKI(clk),
    .WBRSTI(gnd),
    .WBCYCI(gnd),
    .WBSTBI(gnd),
    .WBWEI(gnd),
    .WBADRI7(gnd), .WBADRI6(gnd), .WBADRI5(gnd), .WBADRI4(gnd),
    .WBADRI3(gnd), .WBADRI2(gnd), .WBADRI1(gnd), .WBADRI0(gnd),
    .WBDATI7(gnd), .WBDATI6(gnd), .WBDATI5(gnd), .WBDATI4(gnd),
    .WBDATI3(gnd), .WBDATI2(gnd), .WBDATI1(gnd), .WBDATI0(gnd),
    .PLL0DATI7(gnd), .PLL0DATI6(gnd), .PLL0DATI5(gnd), .PLL0DATI4(gnd),
    .PLL0DATI3(gnd), .PLL0DATI2(gnd), .PLL0DATI1(gnd), .PLL0DATI0(gnd),
    .PLL0ACKI(gnd),
    .PLL1DATI7(gnd), .PLL1DATI6(gnd), .PLL1DATI5(gnd), .PLL1DATI4(gnd),
    .PLL1DATI3(gnd), .PLL1DATI2(gnd), .PLL1DATI1(gnd), .PLL1DATI0(gnd),
    .PLL1ACKI(gnd),
    .I2C1SCLI(gnd), .I2C1SDAI(gnd),
    .I2C2SCLI(gnd), .I2C2SDAI(gnd),
    .SPISCKI(gnd), .SPIMISOI(gnd), .SPIMOSII(gnd), .SPISCSN(gnd),
    .TCCLKI(gnd), .TCRSTN(gnd), .TCIC(gnd),
    .UFMSN(gnd),
    .WBDATO7(wbdato_w[7]), .WBDATO6(wbdato_w[6]),
    .WBDATO5(wbdato_w[5]), .WBDATO4(wbdato_w[4]),
    .WBDATO3(wbdato_w[3]), .WBDATO2(wbdato_w[2]),
    .WBDATO1(wbdato_w[1]), .WBDATO0(wbdato_w[0]),
    .WBACKO(wbacko_w)
);
reg out0_r;
always @(posedge clk) out0_r <= wbacko_w ^ ^wbdato_w;
assign out0 = out0_r;

endmodule
