module fuzz (
    input  wire clk,
    input  wire a,
    input  wire b,
    output reg  out0
);
    (* syn_keep = 1 *) wire w;
    assign w = a ^ b;
    always @(posedge clk) out0 <= w;
endmodule
