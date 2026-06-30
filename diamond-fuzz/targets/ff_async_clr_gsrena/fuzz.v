module fuzz (
    input wire clk,
    input wire d,
    output wire out0
);

wire q_w;
(* GSR="ENABLED" *)
FD1S3DX u0 (.CK(clk), .D(d), .CD(1'b0), .Q(q_w));
reg out0_r;
always @(posedge clk) out0_r <= q_w;
assign out0 = out0_r;

endmodule
