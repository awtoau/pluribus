module fuzz (
    input  wire clk,
    input  wire d,
    input  wire rst,
    output reg  q
);
    (* syn_useioff = 1 *)
    always @(posedge clk or posedge rst)
        if (rst) q <= 1'b0;
        else     q <= d;
endmodule
