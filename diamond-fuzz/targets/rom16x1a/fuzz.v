module fuzz (
    input wire clk,
    output wire out0
);

wire gnd = 1'b0;
wire do_w;
ROM16X1A #(.initval("0x0000")) u0 (
    .AD0(gnd),
    .AD1(gnd),
    .AD2(gnd),
    .AD3(gnd),
    .DO0(do_w)
);
reg out0_r;
always @(posedge clk) out0_r <= do_w;
assign out0 = out0_r;

endmodule
