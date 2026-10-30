module top (
  input clk,
  output y
);
reg [31:0] a1, b2;
reg [31:0] stim0;
reg [30:0] stim1;
reg [29:0] stim2;
reg [28:0] stim3;
reg [27:0] stim4;
reg [32:0] s3;
reg [15:0] lf4;
(* ramstyle = "M9K, no_rw_check" *) reg [31:0] ram5 [0:255];
reg [7:0] ad6;
reg [7:0] ad7;
reg [31:0] rq8;
reg [26:0] stim5;
reg [25:0] stim6;
reg [24:0] stim7;
wire [31:0] pi9 = {(stim5[14] ^ stim5[0]), (stim5[2] ^ stim5[24]), (stim5[4] ^ stim5[9]), (stim5[6] ^ stim5[11]), (stim5[8] ^ stim5[1]), (stim5[10] ^ stim5[16]), (stim5[19] ^ stim5[3]), (stim5[5] ^ stim6[11]), (stim6[6] ^ stim6[3]), (stim6[7] ^ stim6[12]), (stim6[5] ^ stim6[15]), (stim6[23] ^ stim6[0]), (stim6[9] ^ stim6[21]), (stim6[25] ^ stim6[2]), (stim6[19] ^ stim6[4]), (stim6[1] ^ stim6[8]), (stim6[17] ^ stim6[18]), (stim6[13] ^ stim6[16]), (stim6[14] ^ stim6[22]), (stim6[24] ^ stim6[20]), (stim6[10] ^ stim7[19]), (stim7[9] ^ stim7[0]), (stim7[10] ^ stim7[13]), (stim7[1] ^ stim7[4]), (stim7[16] ^ stim7[24]), (stim7[17] ^ stim7[12]), (stim7[6] ^ stim7[18]), (stim7[22] ^ stim7[11]), (stim7[20] ^ stim7[23]), (stim7[8] ^ stim7[21]), (stim7[5] ^ stim7[3]), (stim7[15] ^ stim7[14])};
reg [31:0] pp10;
reg [31:0] pp11;
reg [31:0] pp12;
reg [31:0] pp13;
reg [31:0] pp14;
reg [31:0] pp15;
reg [31:0] pp16;
reg [7:0] cnt17;
reg [23:0] sr18;
reg [7:0] cnt19;
(* ramstyle = "M9K, no_rw_check" *) reg [7:0] fm20 [0:63];
reg [5:0] wp21, rp22;
reg [6:0] fc23;
reg [7:0] fq24;
wire ff25 = (fc23 == 7'd64);
wire fe26 = (fc23 == 7'd0);
wire wr27 = stim1[5] & ~ff25;
wire rd28 = stim6[3] & ~fe26;
reg [11:0] sum29;
(* ramstyle = "M9K, no_rw_check" *) reg [8:0] fm30 [0:63];
reg [5:0] wp31, rp32;
reg [6:0] fc33;
reg [8:0] fq34;
wire ff35 = (fc33 == 7'd64);
wire fe36 = (fc33 == 7'd0);
wire wr37 = stim5[22] & ~ff35;
wire rd38 = stim4[4] & ~fe36;
wire [1:0] sel39 = {stim3[12], stim0[13]};
reg [0:0] mx40;
wire [3:0] mv41 = {{(stim1[20] ^ stim3[13])}, {(stim5[23] ^ stim6[15])}, {(stim0[7] ^ stim6[5])}, {(stim6[12] ^ stim3[18])}};
wire [15:0] pi42 = {(stim0[18] ^ stim7[17]), (stim6[23] ^ stim5[26]), (stim0[22] ^ stim4[5]), (stim6[0] ^ stim7[12]), (stim0[0] ^ stim4[17]), (stim6[9] ^ stim2[2]), (stim0[6] ^ stim7[6]), (stim7[18] ^ stim3[5]), (stim5[20] ^ stim2[8]), (stim5[14] ^ stim4[12]), (stim6[21] ^ stim7[22]), (stim0[26] ^ stim7[11]), (stim4[10] ^ stim7[20]), (stim0[4] ^ stim1[25]), (stim7[23] ^ stim4[13]), (stim5[0] ^ stim4[23])};
reg [15:0] pp43;
reg [15:0] pp44;
reg [15:0] pp45;
reg [31:0] a46, b47;
reg [31:0] c49;
reg [33:0] s48;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) begin a1 <= {(stim0[11] ^ stim0[28]), (stim0[12] ^ stim0[30]), (stim0[20] ^ stim0[27]), (stim0[19] ^ stim0[23]), (stim0[7] ^ stim0[13]), (stim0[18] ^ stim0[22]), (stim0[0] ^ stim0[6]), (stim0[26] ^ stim0[4]), (stim0[5] ^ stim0[8]), (stim0[31] ^ stim0[14]), (stim0[25] ^ stim0[16]), (stim0[2] ^ stim0[29]), (stim0[21] ^ stim0[1]), (stim0[17] ^ stim0[24]), (stim0[15] ^ stim0[3]), (stim0[10] ^ stim0[9]), (stim1[9] ^ stim1[24]), (stim1[15] ^ stim1[17]), (stim1[1] ^ stim1[5]), (stim1[18] ^ stim1[8]), (stim1[20] ^ stim1[25]), (stim1[2] ^ stim1[30]), (stim1[7] ^ stim1[0]), (stim1[16] ^ stim1[4]), (stim1[27] ^ stim1[23]), (stim1[22] ^ stim1[12]), (stim1[3] ^ stim1[13]), (stim1[11] ^ stim1[10]), (stim1[6] ^ stim1[19]), (stim1[26] ^ stim1[29]), (stim1[21] ^ stim1[28]), (stim1[14] ^ stim2[17])}; b2 <= {(stim2[9] ^ stim2[11]), (stim2[29] ^ stim2[26]), (stim2[16] ^ stim2[6]), (stim2[10] ^ stim2[27]), (stim2[2] ^ stim2[8]), (stim2[3] ^ stim2[19]), (stim2[22] ^ stim2[5]), (stim2[24] ^ stim2[12]), (stim2[21] ^ stim2[28]), (stim2[18] ^ stim2[15]), (stim2[0] ^ stim2[13]), (stim2[4] ^ stim2[14]), (stim2[23] ^ stim2[20]), (stim2[7] ^ stim2[25]), (stim2[1] ^ stim3[22]), (stim3[6] ^ stim3[23]), (stim3[4] ^ stim3[11]), (stim3[18] ^ stim3[13]), (stim3[12] ^ stim3[5]), (stim3[1] ^ stim3[9]), (stim3[8] ^ stim3[19]), (stim3[21] ^ stim3[28]), (stim3[2] ^ stim3[16]), (stim3[15] ^ stim3[25]), (stim3[10] ^ stim3[14]), (stim3[17] ^ stim3[7]), (stim3[20] ^ stim3[26]), (stim3[3] ^ stim3[0]), (stim3[24] ^ stim3[27]), (stim4[24] ^ stim4[15]), (stim4[3] ^ stim4[7]), (stim4[4] ^ stim4[25])}; end
always @(posedge clk) s3 <= a1 + b2;
always @(posedge clk) lf4 <= {lf4[14:0], ~(lf4[15] ^ lf4[14] ^ lf4[12] ^ lf4[3] ^ stim4[5])};
always @(posedge clk) ad6 <= ad6 + 8'd1;
always @(posedge clk) ad7 <= ad7 + 8'd1;
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) begin
  if (stim4[17]) ram5[ad6] <= {stim4[12], stim4[10], stim4[13], stim4[23], stim4[20], stim4[14], stim4[8], stim4[26], stim4[27], stim4[21], stim4[6], stim4[16], stim4[9], stim4[18], stim4[1], stim4[2], stim4[11], stim4[0], stim4[22], stim4[19], stim5[17], stim5[18], stim5[12], stim5[25], stim5[7], stim5[15], stim5[21], stim5[13], stim5[22], stim5[23], stim5[26], stim5[20]};
  rq8 <= ram5[ad7];
end
always @(posedge clk) stim6 <= {stim6[24:0], ~(stim6[25] ^ stim6[5] ^ stim6[1] ^ stim6[0])};
always @(posedge clk) stim7 <= {stim7[23:0], ~(stim7[24] ^ stim7[21])};
always @(posedge clk) pp10 <= pi9 ^ {pi9[30:0], pi9[31]} ^ {pi9[29:0], pi9[31:30]};
always @(posedge clk) pp11 <= pp10 + 32'd1016315376;
always @(posedge clk) pp12 <= ~pp11;
always @(posedge clk) pp13 <= {pp12[30:0], pp12[31]};
always @(posedge clk) pp14 <= ~pp13;
always @(posedge clk) pp15 <= ~pp14;
always @(posedge clk) pp16 <= ~pp15;
always @(posedge clk) begin
  if (stim7[2] & stim6[11]) cnt17 <= {stim7[19], stim5[17], stim5[18], stim2[17], stim6[6], stim1[9], stim0[11], stim7[9]};
  else cnt17 <= cnt17 - 8'd5;
end
always @(posedge clk) if (stim0[28] & stim4[24]) sr18 <= {stim4[15], stim5[12], stim7[0], stim2[9], stim4[3], stim2[11], stim1[24], stim1[15], stim1[17], stim0[12], stim2[29], stim3[22], stim2[26], stim5[25], stim0[30], stim0[20], stim7[10], stim4[7], stim7[13], stim0[27], stim1[1], stim5[7], stim2[16], stim7[1]}; else sr18 <= {sr18[22:0], stim5[15]};
always @(posedge clk) begin
  cnt19 <= cnt19 + 8'd1;
end
always @(posedge clk) begin
  if (wr27) begin fm20[wp21] <= {stim1[18], stim3[6], stim7[4], stim5[21], stim5[13], stim7[16], stim7[24], stim1[8]}; wp21 <= wp21 + 6'd1; end
  if (rd28) begin fq24 <= fm20[rp22]; rp22 <= rp22 + 6'd1; end
  fc23 <= fc23 + {{6{1'b0}}, wr27} - {{6{1'b0}}, rd28};
end
always @(posedge clk) sum29 <= sum29 + fq24;
always @(posedge clk) begin
  if (wr37) begin fm30[wp31] <= {stim2[6], stim6[7], stim3[23], stim0[23], stim4[25], stim2[10], stim3[4], stim3[11], stim2[27]}; wp31 <= wp31 + 6'd1; end
  if (rd38) begin fq34 <= fm30[rp32]; rp32 <= rp32 + 6'd1; end
  fc33 <= fc33 + {{6{1'b0}}, wr37} - {{6{1'b0}}, rd38};
end
always @(posedge clk) mx40 <= mv41[sel39 * 1 +: 1];
always @(posedge clk) pp43 <= pi42 ^ 16'h78D7;
always @(posedge clk) pp44 <= {pp43[14:0], pp43[15]};
always @(posedge clk) pp45 <= pp44 + 16'd25147;
always @(posedge clk) begin a46 <= {(stim7[8] ^ stim2[3]), (stim3[1] ^ stim4[20]), (stim5[2] ^ stim6[25]), (stim0[5] ^ stim5[24]), (stim5[4] ^ stim2[19]), (stim0[8] ^ stim6[2]), (stim1[2] ^ stim7[21]), (stim1[30] ^ stim4[14]), (stim5[9] ^ stim5[6]), (stim5[11] ^ stim2[22]), (stim5[8] ^ stim6[19]), (stim5[1] ^ stim6[4]), (stim7[5] ^ stim6[1]), (stim0[31] ^ stim5[10]), (stim0[14] ^ stim4[8]), (stim3[9] ^ stim2[5]), (stim5[16] ^ stim3[8]), (stim1[7] ^ stim3[19]), (stim1[0] ^ stim4[26]), (stim2[24] ^ stim3[21]), (stim4[27] ^ stim1[16]), (stim7[3] ^ stim3[28]), (stim6[8] ^ stim3[2]), (stim2[12] ^ stim5[19]), (stim5[3] ^ stim0[25]), (stim0[16] ^ stim4[21]), (stim7[15] ^ stim3[16]), (stim3[15] ^ stim2[21]), (stim5[5] ^ stim1[4]), (stim2[28] ^ stim2[18]), (stim1[27] ^ stim7[14]), (stim4[6] ^ stim7[7])}; b47 <= {(stim1[23] ^ stim0[2]), (stim6[17] ^ stim7[2]), (stim6[18] ^ stim3[25]), (stim4[16] ^ stim3[10]), (stim5[17] ^ stim6[13]), (stim7[19] ^ stim1[22]), (stim1[12] ^ stim6[16]), (stim5[18] ^ stim0[29]), (stim0[21] ^ stim5[12]), (stim6[14] ^ stim1[3]), (stim1[13] ^ stim5[25]), (stim2[15] ^ stim0[1]), (stim5[7] ^ stim7[9]), (stim7[0] ^ stim4[9]), (stim6[22] ^ stim7[10]), (stim1[11] ^ stim5[15]), (stim5[21] ^ stim6[24]), (stim5[13] ^ stim3[14]), (stim1[10] ^ stim6[20]), (stim4[18] ^ stim2[0]), (stim7[13] ^ stim5[22]), (stim5[23] ^ stim7[1]), (stim1[6] ^ stim5[26]), (stim1[19] ^ stim4[1]), (stim0[17] ^ stim4[2]), (stim7[4] ^ stim3[17]), (stim3[7] ^ stim3[20]), (stim2[13] ^ stim1[26]), (stim6[10] ^ stim2[4]), (stim6[11] ^ stim0[24]), (stim3[26] ^ stim0[15]), (stim5[20] ^ stim4[11])}; end
always @(posedge clk) c49 <= {(stim4[0] ^ stim1[29]), (stim6[6] ^ stim0[3]), (stim6[3] ^ stim5[14]), (stim2[14] ^ stim2[23]), (stim7[17] ^ stim5[0]), (stim3[3] ^ stim1[21]), (stim6[7] ^ stim3[0]), (stim7[12] ^ stim3[24]), (stim1[28] ^ stim2[20]), (stim1[14] ^ stim0[10]), (stim4[22] ^ stim7[6]), (stim7[18] ^ stim5[2]), (stim2[7] ^ stim4[19]), (stim2[25] ^ stim5[24]), (stim4[24] ^ stim0[9]), (stim4[15] ^ stim6[12]), (stim7[22] ^ stim6[5]), (stim6[15] ^ stim7[11]), (stim2[1] ^ stim0[11]), (stim3[27] ^ stim4[3]), (stim5[4] ^ stim2[17]), (stim1[9] ^ stim4[7]), (stim1[24] ^ stim7[20]), (stim4[4] ^ stim0[28]), (stim5[9] ^ stim6[23]), (stim1[1] ^ stim4[25]), (stim5[6] ^ stim7[23]), (stim0[12] ^ stim2[9]), (stim2[11] ^ stim1[5]), (stim1[18] ^ stim2[29]), (stim0[30] ^ stim3[22]), (stim6[0] ^ stim4[5])};
always @(posedge clk) s48 <= a46 + b47 + c49;
always @(posedge clk) y_q <= (^s3) ^ (^lf4) ^ (^rq8) ^ (^pp16) ^ (^cnt17) ^ (^sr18) ^ (^cnt19) ^ (^fq24) ^ (^fc23) ^ (^wp21) ^ (^rp22) ^ (^sum29) ^ (^fq34) ^ (^fc33) ^ (^wp31) ^ (^rp32) ^ mx40 ^ (^pp45) ^ (^s48);
assign y = y_q;
endmodule
