module top (
    input clk,
    input a,
    input b,
    input c,
    input d,
    input [1:0] s,
    output logic y
);
  logic m;
  always_comb begin
    unique case (s)
      2'd0: m = a;
      2'd1: m = b;
      2'd2: m = c;
      default: m = d;
    endcase
  end
  always_ff @(posedge clk) y <= m;
endmodule
