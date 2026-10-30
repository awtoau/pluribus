module top (
  input clk,
  output y
);
reg [7:0] a1, b2;
reg [31:0] stim0;
reg [8:0] s3;
reg [7:0] a4, b5;
reg [30:0] stim1;
reg [29:0] stim2;
reg [8:0] s6;
reg [3:0] a7, b8;
reg [4:0] s9;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin a1 <= {(stim0[8] ^ stim0[14]), (stim0[24] ^ stim0[1]), (stim0[0] ^ stim0[10]), (stim0[6] ^ stim0[23]), (stim0[21] ^ stim0[19]), (stim0[18] ^ stim0[30]), (stim0[5] ^ stim0[20]), (stim0[16] ^ stim0[27])}; b2 <= {(stim0[26] ^ stim0[9]), (stim0[3] ^ stim0[15]), (stim0[17] ^ stim0[13]), (stim0[12] ^ stim0[28]), (stim0[31] ^ stim0[7]), (stim0[4] ^ stim0[11]), (stim0[22] ^ stim0[25]), (stim0[2] ^ stim0[29])}; end
always @(posedge clk) s3 <= a1 + b2;
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin a4 <= {(stim1[26] ^ stim1[15]), (stim1[23] ^ stim1[6]), (stim1[28] ^ stim1[14]), (stim1[2] ^ stim1[10]), (stim1[17] ^ stim1[19]), (stim1[12] ^ stim1[7]), (stim1[29] ^ stim1[4]), (stim1[11] ^ stim1[0])}; b5 <= {(stim1[9] ^ stim1[21]), (stim1[3] ^ stim1[30]), (stim1[1] ^ stim1[16]), (stim1[20] ^ stim1[27]), (stim1[25] ^ stim1[24]), (stim1[13] ^ stim1[18]), (stim1[8] ^ stim1[22]), (stim1[5] ^ stim2[13])}; end
always @(posedge clk) s6 <= a4 + 9'd207;
always @(posedge clk) begin a7 <= {(stim2[12] ^ stim2[19]), (stim2[21] ^ stim2[24]), (stim2[3] ^ stim2[18]), (stim2[23] ^ stim2[6])}; b8 <= {(stim2[25] ^ stim2[5]), (stim2[17] ^ stim2[27]), (stim2[11] ^ stim2[10]), (stim2[28] ^ stim2[20])}; end
always @(posedge clk) s9 <= a7 + b8;
always @(posedge clk) y_q <= (^s3) ^ (^s6) ^ (^s9);
assign y = y_q;
endmodule
