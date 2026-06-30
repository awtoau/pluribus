module fuzz (
    output wire out0
);

wire gnd = 1'b0;
wire osc_w;
OSCH #(.NOM_FREQ("2.89")) u0 (.STDBY(gnd), .OSC(osc_w));
reg out0_r;
always @(posedge osc_w) out0_r <= ~out0_r;
assign out0 = out0_r;

endmodule
