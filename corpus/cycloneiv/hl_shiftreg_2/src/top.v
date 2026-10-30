module top (
  input clk,
  output y
);
reg [3:0] sr1;
reg [31:0] stim0;
reg [23:0] sr2;
reg [23:0] sr3;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) sr1 <= {sr1[2:0], stim0[20]};
always @(posedge clk) if (stim0[15] & stim0[25]) sr2 <= {stim0[7], stim0[4], stim0[9], stim0[24], stim0[26], stim0[8], stim0[18], stim0[28], stim0[16], stim0[19], stim0[23], stim0[1], stim0[6], stim0[29], stim0[2], stim0[11], stim0[31], stim0[21], stim0[0], stim0[3], stim0[17], stim0[27], stim0[12], stim0[13]}; else sr2 <= {sr2[22:0], sr2[23]};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) if (stim0[5] & stim0[14]) sr3 <= {stim0[22], stim0[30], stim0[10], stim1[16], stim1[2], stim1[20], stim1[13], stim1[15], stim1[25], stim1[17], stim1[24], stim1[29], stim1[4], stim1[8], stim1[7], stim1[9], stim1[14], stim1[0], stim1[12], stim1[18], stim1[23], stim1[28], stim1[19], stim1[3]}; else sr3 <= {sr3[22:0], stim1[10]};
always @(posedge clk) y_q <= (^sr1) ^ (^sr2) ^ (^sr3);
assign y = y_q;
endmodule
