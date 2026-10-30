module top (
  input clk,
  output y
);
reg [19:0] lf1;
reg [39:0] lf2;
reg y_q;
always @(posedge clk) lf1 <= {lf1[18:0], ~(lf1[19] ^ lf1[16])};
always @(posedge clk) lf2 <= {lf2[38:0], ~(lf2[39] ^ lf2[37] ^ lf2[20] ^ lf2[18])};
always @(posedge clk) y_q <= (^lf1) ^ (^lf2);
assign y = y_q;
endmodule
