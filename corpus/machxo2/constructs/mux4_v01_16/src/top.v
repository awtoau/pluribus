module core (
    input [0:0] clk,
    input [15:0] a,
    input [15:0] b,
    input [15:0] c,
    input [15:0] d,
    input [1:0] s,
    output reg [15:0] y
);
  reg [15:0] m;
  always @* begin
    case (s)
      2'd0: m = a;
      2'd1: m = b;
      2'd2: m = c;
      default: m = d;
    endcase
  end
  always @(posedge clk) y <= m;
endmodule

module top (
    input [0:0] clk,
    input [15:0] a,
    input [15:0] b,
    input [15:0] c,
    input [15:0] d,
    input [1:0] s,
    output reg [0:0] par
);
  wire [15:0] y_w;
  core u0 (.clk(clk), .a(a), .b(b), .c(c), .d(d), .s(s), .y(y_w));
  always @(posedge clk) par <= (^y_w);
endmodule
