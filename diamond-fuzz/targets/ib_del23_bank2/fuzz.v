module fuzz (
    input wire clk,
    input wire d,
    output wire out0
);

wire q_w;
(* LOC="35", IO_TYPE="LVCMOS33", DEL_VALUE=23 *)
IB u0 (.I(d), .O(q_w));
reg out0_r;
always @(posedge clk) out0_r <= q_w;
assign out0 = out0_r;

endmodule
