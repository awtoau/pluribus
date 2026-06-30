module fuzz (
    input wire clk,
    input wire d,
    inout wire bio,
    output wire out0
);

wire vcc = 1'b1;
wire q_w;
(* LOC="36", IO_TYPE="LVCMOS33" *)
BB u0 (.B(bio), .I(d), .T(vcc), .O(q_w));
reg out0_r;
always @(posedge clk) out0_r <= q_w;
assign out0 = out0_r;

endmodule
