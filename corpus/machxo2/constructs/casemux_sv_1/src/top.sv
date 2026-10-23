module top (
    input clk,
    input a,
    input b,
    input [1:0] s,
    output logic y
);
  always_ff @(posedge clk) begin
    case (s)
      2'd0: y <= a;
      2'd1: y <= b;
      2'd2: y <= a & b;
      default: y <= a ^ b;
    endcase
  end
endmodule
