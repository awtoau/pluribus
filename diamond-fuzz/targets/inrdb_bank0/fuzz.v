module fuzz (
    input wire clk, input wire pad_in,
    output wire out0
);

wire gnd = 1'b0;
wire rx;
INRDB u0 (.D(pad_in), .E(gnd), .Q(rx));
reg out0_r;
always @(posedge clk) out0_r <= rx;
assign out0 = out0_r;

endmodule
