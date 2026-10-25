module top (input [3:0] a, output reg [3:0] y);
  always @* for (int i = 0; i < 4; i++) y[i] = ~a[i];
endmodule
