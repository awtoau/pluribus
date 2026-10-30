module top (
  input clk,
  output y
);
reg [31:0] sr1;
reg [31:0] stim0;
reg [15:0] sr2;
reg [15:0] sr3;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[12]) sr1 <= {sr1[30:0], stim0[16]};
always @(posedge clk) if (stim0[19] & stim0[24]) sr2 <= {stim0[31], stim0[9], stim0[27], stim0[26], stim0[2], stim0[21], stim0[29], stim0[28], stim0[30], stim0[1], stim0[22], stim0[0], stim0[10], stim0[20], stim0[13], stim0[14]}; else sr2 <= {sr2[14:0], stim0[4]};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) if (stim0[25] & stim0[7]) sr3 <= {stim0[5], stim0[8], stim0[3], stim0[6], stim0[18], stim0[15], stim0[11], stim0[23], stim0[17], stim1[12], stim1[29], stim1[15], stim1[11], stim1[23], stim1[16], stim1[28]}; else sr3 <= {sr3[14:0], stim1[22]};
always @(posedge clk) y_q <= (^sr1) ^ (^sr2) ^ (^sr3);
assign y = y_q;
endmodule
