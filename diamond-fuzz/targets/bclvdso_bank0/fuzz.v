module fuzz (
    input wire clk, input wire lvds_en,
    output wire out0
);

wire gnd = 1'b0;
BCLVDSO u0 (.LVDSENI(lvds_en));
reg out0_r;
always @(posedge clk) out0_r <= lvds_en;
assign out0 = out0_r;

endmodule
