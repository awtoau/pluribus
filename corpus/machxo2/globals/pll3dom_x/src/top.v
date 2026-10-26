module top (
    input wire clk,
    input wire rst,
    input wire ce,
    input wire d,
    output wire q
);

wire gnd = 1'b0, vcc = 1'b1;
wire clkop_w, clkos_w, clkos2_w, lock_w, intlock_w, refclk_w, clkintfb_w;
EHXPLLJ #(.CLKI_DIV(1), .CLKFB_DIV(1), .CLKOP_DIV(1), .CLKOP_ENABLE("ENABLED"),
    .FEEDBK_PATH("CLKOP"), .CLKOS_DIV(4), .CLKOS_ENABLE("ENABLED"),
    .CLKOS2_DIV(2), .CLKOS2_ENABLE("ENABLED"), .CLKOS3_ENABLE("DISABLED")) u0 (
    .CLKI(clk), .CLKFB(clkop_w), .RST(gnd), .STDBY(gnd), .PLLWAKESYNC(gnd),
    .PHASESEL1(gnd), .PHASESEL0(gnd), .PHASEDIR(gnd), .PHASESTEP(gnd), .LOADREG(gnd),
    .RESETM(gnd), .RESETC(gnd), .RESETD(gnd), .ENCLKOP(vcc), .ENCLKOS(vcc), .ENCLKOS2(vcc),
    .ENCLKOS3(gnd), .PLLCLK(gnd), .PLLRST(gnd), .PLLSTB(gnd), .PLLWE(gnd),
    .PLLADDR4(gnd), .PLLADDR3(gnd), .PLLADDR2(gnd), .PLLADDR1(gnd), .PLLADDR0(gnd),
    .PLLDATI7(gnd), .PLLDATI6(gnd), .PLLDATI5(gnd), .PLLDATI4(gnd),
    .PLLDATI3(gnd), .PLLDATI2(gnd), .PLLDATI1(gnd), .PLLDATI0(gnd),
    .CLKOP(clkop_w), .CLKOS(clkos_w), .CLKOS2(clkos2_w), .LOCK(lock_w), .INTLOCK(intlock_w),
    .REFCLK(refclk_w), .CLKINTFB(clkintfb_w));
reg [119:0] ra;
always @(posedge clkop_w) if (rst) ra <= 0; else if (ce) ra <= {ra[118:0], d};
reg [119:0] rb;
always @(posedge clkos_w) if (rst) rb <= 0; else if (ce) rb <= {rb[118:0], ra[119]};
reg [119:0] rc;
always @(posedge clkos2_w) if (rst) rc <= 0; else if (ce) rc <= {rc[118:0], rb[119]};
reg qr; always @(posedge clk) qr <= ^{ra[119], rb[119], rc[119]};
assign q = qr;
endmodule
