module top (
    input clk,
    input [3:0] a,
    input [3:0] b,
    input [3:0] c,
    input [3:0] d,
    input [1:0] s,
    output logic [3:0] y
);
  logic [3:0] m;
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
