module fuzz (
    input wire clk, input wire d0,
    output wire pad_ot, pad_oc
);

OBCO u0 (.I(d0), .OT(pad_ot), .OC(pad_oc));

endmodule
