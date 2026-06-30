module fuzz (
    input  wire clk,
    input  wire d,
    output reg  q_rise,
    output reg  q_fall
);
    always @(posedge clk) q_rise <= d;
    always @(negedge clk) q_fall <= d;
endmodule
