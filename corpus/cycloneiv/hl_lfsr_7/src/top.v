module top (
  input clk,
  output y
);
reg [14:0] lf1;
reg [8:0] lf2;
reg y_q;
always @(posedge clk) lf1 <= {lf1[13:0], ~(lf1[14] ^ lf1[13])};
always @(posedge clk) lf2 <= {lf2[7:0], ~(lf2[8] ^ lf2[4])};
always @(posedge clk) y_q <= (^lf1) ^ (^lf2);
assign y = y_q;
endmodule
