module fuzz (
    input wire clk,
    output wire out0
);

wire osc_w;
wire gnd = 1'b0;
OSCH #(.NOM_FREQ("88.67")) u0 (.STDBY(gnd), .OSC(osc_w));
reg out0_r;
always @(posedge osc_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
