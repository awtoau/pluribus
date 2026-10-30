module top (
  input clk,
  output y
);
reg [31:0] stim0;
reg [30:0] stim1;
wire [2:0] sel1 = {stim1[15], stim1[11], stim1[10]};
reg [1:0] mx2;
reg [29:0] stim2;
wire [3:0] sel3 = {stim2[0], stim2[8], stim2[13], stim2[6]};
reg [0:0] mx4;
wire [15:0] mv5 = {{(stim2[25] ^ stim2[15])}, {(stim2[16] ^ stim2[11])}, {(stim1[4] ^ stim1[1])}, {(stim1[3] ^ stim1[29])}, {(stim1[16] ^ stim1[30])}, {(stim1[8] ^ stim1[7])}, {(stim1[27] ^ stim1[21])}, {(stim1[25] ^ stim1[28])}, {(stim1[12] ^ stim1[24])}, {(stim1[14] ^ stim1[19])}, {(stim1[6] ^ stim1[17])}, {(stim1[5] ^ stim1[26])}, {(stim1[9] ^ stim1[23])}, {(stim1[20] ^ stim1[13])}, {(stim1[22] ^ stim1[18])}, {(stim1[2] ^ stim1[0])}};
reg [28:0] stim3;
wire [0:0] sel6 = stim3[9];
reg [7:0] mx7;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) mx2 <= (sel1 == 3'd0) ? {(stim0[1] ^ stim0[13]), (stim0[10] ^ stim0[12])} : (sel1 == 3'd1) ? {(stim0[18] ^ stim0[31]), (stim0[21] ^ stim0[14])} : (sel1 == 3'd2) ? {(stim0[2] ^ stim0[25]), (stim0[29] ^ stim0[6])} : (sel1 == 3'd3) ? {(stim0[28] ^ stim0[0]), (stim0[30] ^ stim0[3])} : (sel1 == 3'd4) ? {(stim0[23] ^ stim0[19]), (stim0[8] ^ stim0[11])} : (sel1 == 3'd5) ? {(stim0[22] ^ stim0[9]), (stim0[24] ^ stim0[27])} : (sel1 == 3'd6) ? {(stim0[16] ^ stim0[20]), (stim0[26] ^ stim0[17])} : {(stim0[5] ^ stim0[15]), (stim0[7] ^ stim0[4])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) mx4 <= mv5[sel3 * 1 +: 1];
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) case (sel6)
  1'd0: mx7 <= {(stim2[7] ^ stim2[2]), (stim2[26] ^ stim2[28]), (stim2[24] ^ stim2[12]), (stim2[22] ^ stim2[27]), (stim2[3] ^ stim2[14]), (stim2[21] ^ stim2[1]), (stim2[23] ^ stim2[9]), (stim2[20] ^ stim2[5])};
  1'd1: mx7 <= {(stim2[10] ^ stim2[18]), (stim2[4] ^ stim2[29]), (stim2[19] ^ stim2[17]), (stim3[2] ^ stim3[0]), (stim3[14] ^ stim3[8]), (stim3[28] ^ stim3[23]), (stim3[12] ^ stim3[7]), (stim3[10] ^ stim3[24])};
  default: mx7 <= {8{1'b0}};
endcase
always @(posedge clk) y_q <= (^mx2) ^ mx4 ^ (^mx7);
assign y = y_q;
endmodule
