module top (
  input clk,
  output y
);
reg [11:0] lf1;
reg [7:0] lf2;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) lf1 <= {lf1[10:0], ~(lf1[11] ^ lf1[5] ^ lf1[3] ^ lf1[0])};
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) lf2 <= {lf2[6:0], ~(lf2[7] ^ lf2[5] ^ lf2[4] ^ lf2[3] ^ stim0[24])};
always @(posedge clk) y_q <= (^lf1) ^ (^lf2);
assign y = y_q;
endmodule
