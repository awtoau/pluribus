module fuzz (
    input  wire clk,
    input  wire d,
    output wire out0
);
    reg [15:0] shreg;
    always @(posedge clk) shreg <= {shreg[14:0], d};
    assign out0 = shreg[15];
endmodule
