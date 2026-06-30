module fuzz (
    input  wire clk,
    output reg  out0
);
    wire gnd = 1'b0;
    wire osc_w;
    OSCH #(.NOM_FREQ("133.00")) u0 (.STDBY(gnd), .OSC(osc_w));
    always @(posedge osc_w) out0 <= ~out0;
endmodule
