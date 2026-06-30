module fuzz (
    input wire clk, input wire d0,
    output wire pad_out
);

wire gnd = 1'b0;
LVDSOB u0 (.D(d0), .E(gnd), .Q(pad_out));

endmodule
