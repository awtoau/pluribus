module fuzz (
    input  wire clk,
    input  wire d,
    output reg  q
);
    (* syn_useioff = 1 *)
    always @(posedge clk) q <= d;
endmodule
