module fuzz (
    input wire clk,
    input wire d,
    input wire d2,
    input wire d3,
    output wire out0
);

wire out_w;
LUT4 #(.init(16'hFF7F)) u0 (.A(d), .B(d2), .C(d3), .D(1'b0), .Z(out_w));
reg out0_r;
always @(posedge clk) out0_r <= out_w;
assign out0 = out0_r;

endmodule
