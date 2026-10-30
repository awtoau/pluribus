module top (
  input clk,
  output y
);
reg [47:0] lf1;
reg [15:0] lf2;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) lf1 <= {lf1[46:0], ~(lf1[47] ^ lf1[46] ^ lf1[20] ^ lf1[19])};
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) lf2 <= {lf2[14:0], ~(lf2[15] ^ lf2[14] ^ lf2[12] ^ lf2[3] ^ stim0[29])};
always @(posedge clk) y_q <= (^lf1) ^ (^lf2);
assign y = y_q;
endmodule
