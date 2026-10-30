module top (
  input clk,
  output y
);
reg [31:0] stim0;
wire [3:0] pi1 = {(stim0[21] ^ stim0[11]), (stim0[4] ^ stim0[7]), (stim0[24] ^ stim0[6]), (stim0[17] ^ stim0[22])};
reg [3:0] pp2;
reg [3:0] pp3;
reg [3:0] pp4;
reg [3:0] pp5;
reg [3:0] pp6;
reg [15:0] lf7;
reg [15:0] acc8;
reg lt9;
reg [8:0] ma10;
reg [11:0] mb11;
reg [20:0] mp12;
reg [30:0] stim1;
reg [23:0] lf13;
reg [23:0] acc14;
reg lt15;
reg [15:0] crc16;
function [15:0] crcf17(input [15:0] cc, input [0:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 1; i = i + 1) rr = (rr[15] ^ x[0 - i]) ? ((rr << 1) ^ 16'h1021) : (rr << 1);
    crcf17 = rr;
  end
endfunction
reg [15:0] cnt18, lim19;
reg cmp20;
localparam [1:0] RUN = 2'd0, HOLD = 2'd1, CLR = 2'd2, WAIT = 2'd3;
reg [1:0] st21;
reg [29:0] stim2;
reg [8:0] ma22;
reg [17:0] mb23;
reg [26:0] mp24;
reg [28:0] stim3;
reg [27:0] stim4;
reg [8:0] ma25;
reg [17:0] mb26;
reg [26:0] stim5;
reg [25:0] stim6;
reg [17:0] ma27;
reg [7:0] mb28;
reg [25:0] mp29;
reg [24:0] stim7;
reg [17:0] ma30;
reg [7:0] mb31;
reg [7:0] sr32;
reg [23:0] lf33;
reg [23:0] acc34;
reg lt35;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) pp2 <= ~pi1;
always @(posedge clk) pp3 <= pp2 ^ 4'hF;
always @(posedge clk) pp4 <= pp3 + 4'd12;
always @(posedge clk) pp5 <= pp4 ^ 4'h6;
always @(posedge clk) pp6 <= {pp5[2:0], pp5[3]};
always @(posedge clk) lf7 <= {lf7[14:0], ~(lf7[15] ^ lf7[14] ^ lf7[12] ^ lf7[3])};
always @(posedge clk) acc8 <= acc8 + lf7;
always @(posedge clk) lt9 <= acc8 < lf7;
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin ma10 <= {(stim0[16] ^ stim0[9]), (stim0[18] ^ stim0[23]), (stim0[30] ^ stim0[27]), (stim0[1] ^ stim0[19]), (stim0[8] ^ stim0[3]), (stim0[13] ^ stim0[25]), (stim0[2] ^ stim0[26]), (stim0[15] ^ stim0[0]), (stim0[31] ^ stim0[28])}; mb11 <= {(stim0[5] ^ stim0[12]), (stim0[29] ^ stim0[20]), (stim0[14] ^ stim0[10]), (stim1[4] ^ stim1[2]), (stim1[8] ^ stim1[16]), (stim1[15] ^ stim1[6]), (stim1[23] ^ stim1[18]), (stim1[24] ^ stim1[19]), (stim1[12] ^ stim1[26]), (stim1[9] ^ stim1[10]), (stim1[21] ^ stim1[30]), (stim1[1] ^ stim1[3])}; end
always @(posedge clk) mp12 <= ma10 * mb11;
always @(posedge clk) lf13 <= {lf13[22:0], ~(lf13[23] ^ lf13[22] ^ lf13[21] ^ lf13[16])};
always @(posedge clk) acc14 <= acc14 + lf13;
always @(posedge clk) lt15 <= acc14 < lf13;
always @(posedge clk) if (stim1[28] & stim1[0] & stim1[29]) crc16 <= {16{1'b1}}; else if (stim1[7]) crc16 <= crcf17(crc16, stim1[5]);
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) lim19 <= {(stim1[14] ^ stim1[20]), (stim1[13] ^ stim1[17]), (stim1[25] ^ stim1[22]), (stim1[27] ^ stim1[11]), (stim2[15] ^ stim2[28]), (stim2[9] ^ stim2[26]), (stim2[0] ^ stim2[7]), (stim2[5] ^ stim2[25]), (stim2[10] ^ stim2[19]), (stim2[17] ^ stim2[6]), (stim2[8] ^ stim2[13]), (stim2[21] ^ stim2[14]), (stim2[16] ^ stim2[11]), (stim2[12] ^ stim2[2]), (stim2[18] ^ stim2[3]), (stim2[20] ^ stim2[27])};
always @(posedge clk) cmp20 <= cnt18 >= lim19;
always @(posedge clk) case (st21)
  RUN: st21 <= cmp20 ? HOLD : RUN;
  HOLD: st21 <= stim2[22] ? CLR : WAIT;
  CLR: st21 <= RUN;
  WAIT: st21 <= stim2[4] ? RUN : WAIT;
endcase
always @(posedge clk) if (st21 == CLR) cnt18 <= {16{1'b0}}; else if (st21 == RUN) cnt18 <= cnt18 + 16'd1;
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) begin ma22 <= {(stim2[1] ^ stim2[23]), (stim2[29] ^ stim2[24]), (stim3[23] ^ stim3[9]), (stim3[5] ^ stim3[14]), (stim3[20] ^ stim3[21]), (stim3[12] ^ stim3[19]), (stim3[10] ^ stim3[17]), (stim3[4] ^ stim3[24]), (stim3[26] ^ stim3[25])}; mb23 <= {(stim3[6] ^ stim3[3]), (stim3[7] ^ stim3[2]), (stim3[16] ^ stim3[11]), (stim3[15] ^ stim3[27]), (stim3[22] ^ stim3[0]), (stim3[13] ^ stim3[18]), (stim3[28] ^ stim3[1]), (stim3[8] ^ stim4[17]), (stim4[6] ^ stim4[7]), (stim4[2] ^ stim4[26]), (stim4[21] ^ stim4[5]), (stim4[20] ^ stim4[25]), (stim4[12] ^ stim4[4]), (stim4[22] ^ stim4[24]), (stim4[0] ^ stim4[8]), (stim4[1] ^ stim4[10]), (stim4[13] ^ stim4[15]), (stim4[11] ^ stim4[19])}; end
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) stim6 <= {stim6[24:0], ~(stim6[25] ^ stim6[5] ^ stim6[1] ^ stim6[0])};
always @(posedge clk) begin ma25 <= {(stim4[23] ^ stim4[14]), (stim4[9] ^ stim4[18]), (stim4[3] ^ stim4[27]), (stim4[16] ^ stim5[22]), (stim5[1] ^ stim5[25]), (stim5[11] ^ stim5[24]), (stim5[9] ^ stim5[5]), (stim5[14] ^ stim5[15]), (stim5[4] ^ stim5[23])}; mb26 <= {(stim5[12] ^ stim5[2]), (stim5[3] ^ stim5[16]), (stim5[8] ^ stim5[17]), (stim5[13] ^ stim5[26]), (stim5[19] ^ stim5[10]), (stim5[18] ^ stim5[6]), (stim5[7] ^ stim5[0]), (stim5[21] ^ stim5[20]), (stim6[22] ^ stim6[16]), (stim6[14] ^ stim6[3]), (stim6[11] ^ stim6[24]), (stim6[25] ^ stim6[12]), (stim6[9] ^ stim6[4]), (stim6[0] ^ stim6[17]), (stim6[7] ^ stim6[8]), (stim6[10] ^ stim6[23]), (stim6[20] ^ stim6[13]), (stim6[1] ^ stim6[5])}; mp24 <= ma22 * mb23 + ma25 * mb26; end
always @(posedge clk) stim7 <= {stim7[23:0], ~(stim7[24] ^ stim7[21])};
always @(posedge clk) begin ma27 <= {(stim6[15] ^ stim6[6]), (stim6[18] ^ stim6[19]), (stim6[2] ^ stim6[21]), (stim7[5] ^ stim7[12]), (stim7[7] ^ stim7[23]), (stim7[1] ^ stim7[15]), (stim7[20] ^ stim7[6]), (stim7[16] ^ stim7[9]), (stim7[3] ^ stim7[4]), (stim7[14] ^ stim7[17]), (stim7[21] ^ stim7[24]), (stim7[13] ^ stim7[10]), (stim7[22] ^ stim7[0]), (stim7[2] ^ stim7[18]), (stim7[19] ^ stim7[8]), (stim7[11] ^ stim0[21]), (stim0[11] ^ stim3[23]), (stim1[4] ^ stim0[4])}; mb28 <= {(stim3[9] ^ stim1[2]), (stim7[5] ^ stim3[5]), (stim6[22] ^ stim1[8]), (stim4[17] ^ stim3[14]), (stim2[15] ^ stim6[16]), (stim3[20] ^ stim1[16]), (stim0[7] ^ stim5[22]), (stim5[1] ^ stim1[15])}; end
always @(posedge clk) begin ma30 <= {(stim0[24] ^ stim1[6]), (stim4[6] ^ stim2[28]), (stim0[6] ^ stim3[21]), (stim3[12] ^ stim7[12]), (stim1[23] ^ stim0[17]), (stim0[22] ^ stim6[14]), (stim5[25] ^ stim5[11]), (stim1[18] ^ stim5[24]), (stim6[3] ^ stim3[19]), (stim7[7] ^ stim2[9]), (stim1[24] ^ stim3[10]), (stim3[17] ^ stim4[7]), (stim4[2] ^ stim6[11]), (stim5[9] ^ stim6[24]), (stim0[16] ^ stim2[26]), (stim1[19] ^ stim0[9]), (stim0[18] ^ stim1[12]), (stim1[26] ^ stim2[0])}; mb31 <= {(stim7[23] ^ stim5[5]), (stim1[9] ^ stim7[1]), (stim0[23] ^ stim1[10]), (stim7[15] ^ stim1[21]), (stim1[30] ^ stim6[9]), (stim4[26] ^ stim4[21]), (stim7[20] ^ stim2[7]), (stim3[4] ^ stim6[4])}; mp29 <= ma27 * mb28 + ma30 * mb31; end
always @(posedge clk) sr32 <= {sr32[6:0], stim5[14]};
always @(posedge clk) lf33 <= {lf33[22:0], ~(lf33[23] ^ lf33[22] ^ lf33[21] ^ lf33[16])};
always @(posedge clk) acc34 <= acc34 + lf33;
always @(posedge clk) lt35 <= acc34 < lf33;
always @(posedge clk) y_q <= (^pp6) ^ (^lf7) ^ (^acc8) ^ lt9 ^ (^mp12) ^ (^lf13) ^ (^acc14) ^ lt15 ^ (^crc16) ^ (^cnt18) ^ (^st21) ^ cmp20 ^ (^mp24) ^ (^mp29) ^ (^sr32) ^ (^lf33) ^ (^acc34) ^ lt35;
assign y = y_q;
endmodule
