module top (
  input clk,
  output y
);
reg [31:0] stim0;
wire [3:0] pi1 = {(stim0[21] ^ stim0[23]), (stim0[2] ^ stim0[31]), (stim0[20] ^ stim0[28]), (stim0[19] ^ stim0[4])};
reg [3:0] pp2;
reg [3:0] pp3;
reg [3:0] pp4;
reg [3:0] pp5;
reg [3:0] pp6;
reg [3:0] pp7;
reg [30:0] stim1;
reg [29:0] stim2;
wire [31:0] pi8 = {(stim0[0] ^ stim0[13]), (stim0[8] ^ stim0[25]), (stim0[18] ^ stim0[9]), (stim0[26] ^ stim0[16]), (stim0[14] ^ stim0[24]), (stim0[3] ^ stim0[1]), (stim0[22] ^ stim0[15]), (stim0[6] ^ stim0[17]), (stim0[7] ^ stim0[10]), (stim0[5] ^ stim0[29]), (stim0[12] ^ stim0[30]), (stim0[27] ^ stim0[11]), (stim1[3] ^ stim1[25]), (stim1[6] ^ stim1[13]), (stim1[17] ^ stim1[26]), (stim1[29] ^ stim1[4]), (stim1[2] ^ stim1[0]), (stim1[23] ^ stim1[21]), (stim1[24] ^ stim1[22]), (stim1[20] ^ stim1[30]), (stim1[15] ^ stim1[28]), (stim1[12] ^ stim1[9]), (stim1[16] ^ stim1[18]), (stim1[14] ^ stim1[19]), (stim1[7] ^ stim1[11]), (stim1[27] ^ stim1[10]), (stim1[5] ^ stim1[8]), (stim1[1] ^ stim2[18]), (stim2[5] ^ stim2[8]), (stim2[22] ^ stim2[27]), (stim2[4] ^ stim2[1]), (stim2[0] ^ stim2[14])};
reg [31:0] pp9;
reg [31:0] pp10;
reg [31:0] pp11;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) pp2 <= pi1 + 4'd7;
always @(posedge clk) pp3 <= pp2 ^ {pp2[2:0], pp2[3]} ^ {pp2[1:0], pp2[3:2]};
always @(posedge clk) pp4 <= pp3 ^ 4'hF;
always @(posedge clk) pp5 <= pp4 ^ {pp4[2:0], pp4[3]} ^ {pp4[1:0], pp4[3:2]};
always @(posedge clk) pp6 <= pp5 ^ {pp5[2:0], pp5[3]} ^ {pp5[1:0], pp5[3:2]};
always @(posedge clk) pp7 <= pp6 ^ {pp6[2:0], pp6[3]} ^ {pp6[1:0], pp6[3:2]};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) pp9 <= ~pi8;
always @(posedge clk) pp10 <= {pp9[30:0], pp9[31]};
always @(posedge clk) pp11 <= pp10 ^ 32'hBA45E6BF;
always @(posedge clk) y_q <= (^pp7) ^ (^pp11);
assign y = y_q;
endmodule
