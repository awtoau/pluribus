module top (
  input clk,
  output y
);
reg [23:0] lf1;
reg [31:0] stim0;
reg [63:0] lf2;
reg [19:0] lf3;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) lf1 <= {lf1[22:0], ~(lf1[23] ^ lf1[22] ^ lf1[21] ^ lf1[16] ^ stim0[1])};
always @(posedge clk) lf2 <= {lf2[62:0], ~(lf2[63] ^ lf2[62] ^ lf2[60] ^ lf2[59])};
always @(posedge clk) lf3 <= {lf3[18:0], ~(lf3[19] ^ lf3[16])};
always @(posedge clk) y_q <= (^lf1) ^ (^lf2) ^ (^lf3);
assign y = y_q;
endmodule
