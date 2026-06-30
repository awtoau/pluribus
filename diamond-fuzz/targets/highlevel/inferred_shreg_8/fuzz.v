module fuzz (
    input  wire clk,
    input  wire d,
    output wire out0
);
    reg [7:0] shreg;
    always @(posedge clk) shreg <= {shreg[6:0], d};
    assign out0 = shreg[7];
endmodule
