module fuzz(input wire clk,output wire out0);
 wire g=1'b0; wire [7:0] o; wire a;
 EFB #(.EFB_I2C1("ENABLED"),.EFB_I2C2("DISABLED"),.EFB_SPI("ENABLED"),.EFB_TC("ENABLED"),.EFB_UFM("ENABLED"),.SPI_MODE("MASTER"),.EFB_WB_CLK_FREQ("100.0"))
) u0 (
    .WBCLKI(clk),.WBRSTI(g),.WBCYCI(g),.WBSTBI(g),.WBWEI(g),
    .WBADRI7(g),.WBADRI6(g),.WBADRI5(g),.WBADRI4(g),.WBADRI3(g),.WBADRI2(g),.WBADRI1(g),.WBADRI0(g),
    .WBDATI7(g),.WBDATI6(g),.WBDATI5(g),.WBDATI4(g),.WBDATI3(g),.WBDATI2(g),.WBDATI1(g),.WBDATI0(g),
    .PLL0DATI7(g),.PLL0DATI6(g),.PLL0DATI5(g),.PLL0DATI4(g),.PLL0DATI3(g),.PLL0DATI2(g),.PLL0DATI1(g),.PLL0DATI0(g),.PLL0ACKI(g),
    .PLL1DATI7(g),.PLL1DATI6(g),.PLL1DATI5(g),.PLL1DATI4(g),.PLL1DATI3(g),.PLL1DATI2(g),.PLL1DATI1(g),.PLL1DATI0(g),.PLL1ACKI(g),
    .I2C1SCLI(g),.I2C1SDAI(g),.I2C2SCLI(g),.I2C2SDAI(g),
    .SPISCKI(g),.SPIMISOI(g),.SPIMOSII(g),.SPISCSN(g),
    .TCCLKI(g),.TCRSTN(g),.TCIC(g),.UFMSN(g),
    .WBDATO7(o[7]),.WBDATO6(o[6]),.WBDATO5(o[5]),.WBDATO4(o[4]),
    .WBDATO3(o[3]),.WBDATO2(o[2]),.WBDATO1(o[1]),.WBDATO0(o[0]),.WBACKO(a)
);
 reg r; always @(posedge clk) r<=a^(^o); assign out0=r;
endmodule
