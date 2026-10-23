module core (
    input clk,
    input [15:0] a,
    input [15:0] b,
    input [15:0] c,
    input [15:0] d,
    input [1:0] s,
    output logic [15:0] y
);
  logic [15:0] m;
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

module top (
    input clk,
    input [15:0] a,
    input [15:0] b,
    input [15:0] c,
    input [15:0] d,
    input [1:0] s,
    output logic par
);
  wire [15:0] y_w;
  core u0 (.clk(clk), .a(a), .b(b), .c(c), .d(d), .s(s), .y(y_w));
  always_ff @(posedge clk) par <= (^y_w);
endmodule
