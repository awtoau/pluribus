module top (
  input clk,
  output y
);
reg [15:0] lf1;
reg [11:0] lf2;
reg y_q;
always @(posedge clk) lf1 <= {lf1[14:0], ~(lf1[15] ^ lf1[14] ^ lf1[12] ^ lf1[3])};
always @(posedge clk) lf2 <= {lf2[10:0], ~(lf2[11] ^ lf2[5] ^ lf2[3] ^ lf2[0])};
always @(posedge clk) y_q <= (^lf1) ^ (^lf2);
assign y = y_q;
endmodule
