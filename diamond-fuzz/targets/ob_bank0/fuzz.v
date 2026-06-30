module fuzz (
    input wire clk, input wire d0,
    output wire pad_out
);

OB u0 (.I(d0), .O(pad_out));

endmodule
