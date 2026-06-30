module fuzz (
    input wire clk,
    input wire d,
    output wire out0
);

reg out0_r;
(* LOC="84", IO_TYPE="LVCMOS12", DRIVE=6 *)
OB u0 (.I(out0_r), .O(out0));
always @(posedge clk) out0_r <= d;

endmodule
