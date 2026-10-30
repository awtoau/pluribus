module top (
  input clk,
  output y
);
reg [17:0] ma1;
reg [8:0] mb2;
reg [26:0] mp3;
reg [31:0] stim0;
reg [30:0] stim1;
reg [17:0] ma4;
reg [8:0] mb5;
reg [29:0] stim2;
reg [28:0] stim3;
reg signed [17:0] ma6;
reg signed [15:0] mb7;
reg signed [33:0] mp8;
reg [27:0] stim4;
reg [26:0] stim5;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin ma1 <= {(stim0[1] ^ stim0[29]), (stim0[7] ^ stim0[4]), (stim0[28] ^ stim0[8]), (stim0[18] ^ stim0[13]), (stim0[26] ^ stim0[27]), (stim0[21] ^ stim0[6]), (stim0[10] ^ stim0[20]), (stim0[22] ^ stim0[23]), (stim0[11] ^ stim0[5]), (stim0[9] ^ stim0[3]), (stim0[16] ^ stim0[17]), (stim0[14] ^ stim0[2]), (stim0[0] ^ stim0[15]), (stim0[30] ^ stim0[19]), (stim0[31] ^ stim0[12]), (stim0[25] ^ stim0[24]), (stim1[30] ^ stim1[11]), (stim1[8] ^ stim1[3])}; mb2 <= {(stim1[7] ^ stim1[6]), (stim1[13] ^ stim1[9]), (stim1[21] ^ stim1[17]), (stim1[22] ^ stim1[15]), (stim1[24] ^ stim1[19]), (stim1[2] ^ stim1[18]), (stim1[23] ^ stim1[26]), (stim1[20] ^ stim1[10]), (stim1[4] ^ stim1[0])}; end
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) begin ma4 <= {(stim1[14] ^ stim1[27]), (stim1[16] ^ stim1[28]), (stim1[25] ^ stim1[1]), (stim1[5] ^ stim1[29]), (stim1[12] ^ stim2[26]), (stim2[15] ^ stim2[21]), (stim2[8] ^ stim2[12]), (stim2[6] ^ stim2[17]), (stim2[2] ^ stim2[13]), (stim2[24] ^ stim2[29]), (stim2[18] ^ stim2[9]), (stim2[5] ^ stim2[19]), (stim2[1] ^ stim2[20]), (stim2[3] ^ stim2[23]), (stim2[11] ^ stim2[10]), (stim2[25] ^ stim2[7]), (stim2[4] ^ stim2[22]), (stim2[14] ^ stim2[27])}; mb5 <= {(stim2[0] ^ stim2[16]), (stim2[28] ^ stim3[19]), (stim3[15] ^ stim3[11]), (stim3[13] ^ stim3[14]), (stim3[6] ^ stim3[10]), (stim3[7] ^ stim3[1]), (stim3[23] ^ stim3[16]), (stim3[27] ^ stim3[24]), (stim3[22] ^ stim3[17])}; mp3 <= ma1 * mb2 + ma4 * mb5; end
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) begin ma6 <= {(stim3[28] ^ stim3[0]), (stim3[3] ^ stim3[2]), (stim3[18] ^ stim3[9]), (stim3[12] ^ stim3[21]), (stim3[8] ^ stim3[20]), (stim3[4] ^ stim3[5]), (stim3[26] ^ stim3[25]), (stim4[8] ^ stim4[22]), (stim4[18] ^ stim4[19]), (stim4[11] ^ stim4[0]), (stim4[21] ^ stim4[7]), (stim4[14] ^ stim4[4]), (stim4[3] ^ stim4[26]), (stim4[16] ^ stim4[1]), (stim4[25] ^ stim4[27]), (stim4[15] ^ stim4[9]), (stim4[12] ^ stim4[10]), (stim4[24] ^ stim4[23])}; mb7 <= {(stim4[5] ^ stim4[17]), (stim4[2] ^ stim4[20]), (stim4[13] ^ stim4[6]), (stim5[7] ^ stim5[2]), (stim5[3] ^ stim5[20]), (stim5[5] ^ stim5[12]), (stim5[22] ^ stim5[16]), (stim5[25] ^ stim5[11]), (stim5[21] ^ stim5[6]), (stim5[10] ^ stim5[9]), (stim5[19] ^ stim5[4]), (stim5[18] ^ stim5[15]), (stim5[0] ^ stim5[14]), (stim5[23] ^ stim5[13]), (stim5[26] ^ stim5[17]), (stim5[8] ^ stim5[24])}; end
always @(posedge clk) mp8 <= mp8 + ma6 * mb7;
always @(posedge clk) y_q <= (^mp3) ^ (^mp8);
assign y = y_q;
endmodule
