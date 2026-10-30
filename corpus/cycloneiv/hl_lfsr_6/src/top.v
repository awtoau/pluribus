module top (
  input clk,
  output y
);
reg [8:0] lf1;
reg [14:0] lf2;
reg [39:0] lf3;
reg y_q;
always @(posedge clk) lf1 <= {lf1[7:0], ~(lf1[8] ^ lf1[4])};
always @(posedge clk) lf2 <= {lf2[13:0], ~(lf2[14] ^ lf2[13])};
always @(posedge clk) lf3 <= {lf3[38:0], ~(lf3[39] ^ lf3[37] ^ lf3[20] ^ lf3[18])};
always @(posedge clk) y_q <= (^lf1) ^ (^lf2) ^ (^lf3);
assign y = y_q;
endmodule
