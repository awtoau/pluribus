module fuzz (
    input wire clk,
    input wire d,
    output wire out0
);

wire gnd = 1'b0;
reg out0_r;
(* LOC="84", IO_TYPE="LVCMOS25" *)
OB u0 (.I(out0_r), .O(out0));
always @(posedge clk) out0_r <= d;

endmodule
