module fuzz (
    input wire clk, input wire d0,
    output wire pad_out
);

wire gnd = 1'b0;
OBZ u0 (.I(d0), .T(gnd), .O(pad_out));

endmodule
