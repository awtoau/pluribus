module top (
  input clk,
  output y
);
reg [15:0] a1, b2;
reg [31:0] stim0;
reg [30:0] stim1;
reg [29:0] stim2;
reg f3;
(* ramstyle = "M9K, no_rw_check" *) reg [31:0] fm4 [0:127];
reg [6:0] wp5, rp6;
reg [7:0] fc7;
reg [31:0] fq8;
wire ff9 = (fc7 == 8'd128);
wire fe10 = (fc7 == 8'd0);
wire wr11 = stim2[4] & ~ff9;
wire rd12 = stim2[13] & ~fe10;
reg [28:0] stim3;
reg [31:0] rg13;
reg [27:0] stim4;
reg [26:0] stim5;
reg [25:0] stim6;
reg [24:0] stim7;
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] fm14 [0:15];
reg [3:0] wp15, rp16;
reg [4:0] fc17;
reg [15:0] fq18;
wire ff19 = (fc17 == 5'd16);
wire fe20 = (fc17 == 5'd0);
wire wr21 = stim1[28] & ~ff19;
wire rd22 = stim2[10] & ~fe20;
reg [47:0] sr23;
reg [15:0] crc24;
function [15:0] crcf25(input [15:0] cc, input [7:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[15] ^ x[7 - i]) ? ((rr << 1) ^ 16'h8005) : (rr << 1);
    crcf25 = rr;
  end
endfunction
reg signed [15:0] ma26;
reg signed [7:0] mb27;
reg signed [23:0] mp28;
localparam [4:0] ST29_0 = 5'd0;
localparam [4:0] ST29_1 = 5'd1;
localparam [4:0] ST29_2 = 5'd2;
localparam [4:0] ST29_3 = 5'd3;
localparam [4:0] ST29_4 = 5'd4;
localparam [4:0] ST29_5 = 5'd5;
localparam [4:0] ST29_6 = 5'd6;
localparam [4:0] ST29_7 = 5'd7;
localparam [4:0] ST29_8 = 5'd8;
localparam [4:0] ST29_9 = 5'd9;
localparam [4:0] ST29_10 = 5'd10;
localparam [4:0] ST29_11 = 5'd11;
localparam [4:0] ST29_12 = 5'd12;
localparam [4:0] ST29_13 = 5'd13;
localparam [4:0] ST29_14 = 5'd14;
localparam [4:0] ST29_15 = 5'd15;
localparam [4:0] ST29_16 = 5'd16;
reg [4:0] st29;
reg [1:0] fo30;
reg [23:0] rg31;
reg [15:0] cnt32, lim33;
reg cmp34;
localparam [1:0] RUN = 2'd0, HOLD = 2'd1, CLR = 2'd2, WAIT = 2'd3;
reg [1:0] st35;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin a1 <= {(stim0[11] ^ stim0[25]), (stim0[5] ^ stim0[24]), (stim0[18] ^ stim0[8]), (stim0[7] ^ stim0[31]), (stim0[26] ^ stim0[17]), (stim0[2] ^ stim0[3]), (stim0[1] ^ stim0[21]), (stim0[19] ^ stim0[29]), (stim0[27] ^ stim0[14]), (stim0[22] ^ stim0[0]), (stim0[16] ^ stim0[6]), (stim0[20] ^ stim0[28]), (stim0[4] ^ stim0[10]), (stim0[23] ^ stim0[9]), (stim0[15] ^ stim0[12]), (stim0[13] ^ stim0[30])}; b2 <= {(stim1[28] ^ stim1[14]), (stim1[26] ^ stim1[21]), (stim1[0] ^ stim1[4]), (stim1[24] ^ stim1[16]), (stim1[9] ^ stim1[22]), (stim1[27] ^ stim1[19]), (stim1[23] ^ stim1[2]), (stim1[1] ^ stim1[29]), (stim1[18] ^ stim1[10]), (stim1[20] ^ stim1[13]), (stim1[11] ^ stim1[15]), (stim1[17] ^ stim1[3]), (stim1[6] ^ stim1[5]), (stim1[7] ^ stim1[25]), (stim1[12] ^ stim1[8]), (stim1[30] ^ stim2[10])}; end
always @(posedge clk) f3 <= a1 > b2;
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) begin
  if (wr11) begin fm4[wp5] <= {stim2[24], stim2[21], stim2[29], stim2[22], stim2[3], stim2[16], stim2[0], stim2[27], stim2[11], stim2[17], stim2[8], stim2[15], stim2[5], stim2[7], stim2[28], stim2[18], stim2[6], stim2[12], stim2[14], stim2[9], stim2[20], stim2[2], stim2[23], stim2[19], stim2[25], stim2[1], stim2[26], stim3[24], stim3[15], stim3[4], stim3[7], stim3[20]}; wp5 <= wp5 + 7'd1; end
  if (rd12) begin fq8 <= fm4[rp6]; rp6 <= rp6 + 7'd1; end
  fc7 <= fc7 + {{7{1'b0}}, wr11} - {{7{1'b0}}, rd12};
end
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) stim6 <= {stim6[24:0], ~(stim6[25] ^ stim6[5] ^ stim6[1] ^ stim6[0])};
always @(posedge clk) stim7 <= {stim7[23:0], ~(stim7[24] ^ stim7[21])};
always @(posedge clk) begin
  if (stim3[17] & stim3[16]) rg13 <= {(stim3[11] ^ stim3[3]), (stim3[1] ^ stim3[12]), (stim3[22] ^ stim3[2]), (stim3[27] ^ stim3[23]), (stim3[6] ^ stim3[0]), (stim3[10] ^ stim3[18]), (stim3[9] ^ stim3[14]), (stim3[13] ^ stim3[8]), (stim3[28] ^ stim3[21]), (stim3[26] ^ stim3[5]), (stim3[25] ^ stim3[19]), (stim4[9] ^ stim4[20]), (stim4[25] ^ stim4[23]), (stim4[3] ^ stim4[21]), (stim4[14] ^ stim4[26]), (stim4[5] ^ stim4[2]), (stim4[24] ^ stim4[22]), (stim4[17] ^ stim4[15]), (stim4[6] ^ stim4[27]), (stim4[1] ^ stim4[19]), (stim4[11] ^ stim4[4]), (stim4[0] ^ stim4[18]), (stim4[12] ^ stim4[16]), (stim4[13] ^ stim4[7]), (stim4[8] ^ stim4[10]), (stim5[20] ^ stim5[11]), (stim5[0] ^ stim5[9]), (stim5[14] ^ stim5[23]), (stim5[2] ^ stim5[24]), (stim5[5] ^ stim5[18]), (stim5[25] ^ stim5[3]), (stim5[16] ^ stim5[21])};
  else rg13 <= {(stim5[6] ^ stim5[8]), (stim5[12] ^ stim5[22]), (stim5[19] ^ stim5[1]), (stim5[13] ^ stim5[26]), (stim5[4] ^ stim5[17]), (stim5[15] ^ stim5[7]), (stim5[10] ^ stim6[5]), (stim6[15] ^ stim6[25]), (stim6[10] ^ stim6[7]), (stim6[11] ^ stim6[2]), (stim6[17] ^ stim6[13]), (stim6[0] ^ stim6[14]), (stim6[24] ^ stim6[9]), (stim6[23] ^ stim6[21]), (stim6[20] ^ stim6[8]), (stim6[16] ^ stim6[6]), (stim6[12] ^ stim6[22]), (stim6[18] ^ stim6[1]), (stim6[3] ^ stim6[19]), (stim6[4] ^ stim7[0]), (stim7[3] ^ stim7[20]), (stim7[24] ^ stim7[18]), (stim7[6] ^ stim7[8]), (stim7[11] ^ stim7[1]), (stim7[14] ^ stim7[21]), (stim7[16] ^ stim7[10]), (stim7[9] ^ stim7[7]), (stim7[17] ^ stim7[15]), (stim7[4] ^ stim7[22]), (stim7[5] ^ stim7[2]), (stim7[19] ^ stim7[13]), (stim7[23] ^ stim7[12])};
end
always @(posedge clk) begin
  if (wr21) begin fm14[wp15] <= {stim1[14], stim4[9], stim4[20], stim7[0], stim0[11], stim1[26], stim2[4], stim6[5], stim2[13], stim6[15], stim4[25], stim1[21], stim5[20], stim1[0], stim6[25], stim1[4]}; wp15 <= wp15 + 4'd1; end
  if (rd22) begin fq18 <= fm14[rp16]; rp16 <= rp16 + 4'd1; end
  fc17 <= fc17 + {{4{1'b0}}, wr21} - {{4{1'b0}}, rd22};
end
always @(posedge clk) if (stim2[24] & stim7[3]) sr23 <= {stim3[24], stim4[23], stim5[11], stim2[21], stim3[15], stim3[4], stim7[20], stim0[25], stim6[10], stim7[24], stim3[7], stim6[7], stim1[24], stim6[11], stim7[18], stim7[6], stim7[8], stim2[29], stim3[20], stim4[3], stim0[5], stim5[0], stim2[22], stim5[9], stim6[2], stim5[14], stim0[24], stim7[11], stim6[17], stim1[16], stim4[21], stim0[18], stim3[17], stim7[1], stim3[16], stim5[23], stim2[3], stim7[14], stim6[13], stim5[2], stim3[11], stim4[14], stim2[16], stim3[3], stim2[0], stim1[9], stim5[24], stim3[1]}; else sr23 <= {sr23[46:0], stim4[26]};
always @(posedge clk) if (stim5[5] & stim3[12] & stim5[18]) crc24 <= {16{1'b1}}; else if (stim1[22]) crc24 <= crcf25(crc24, {stim4[5], stim3[22], stim4[2], stim3[2], stim2[27], stim4[24], stim2[11], stim1[27]});
always @(posedge clk) begin ma26 <= {(stim0[8] ^ stim0[7]), (stim2[17] ^ stim3[27]), (stim2[8] ^ stim1[19]), (stim6[24] ^ stim1[23]), (stim5[25] ^ stim3[23]), (stim0[31] ^ stim5[3]), (stim4[22] ^ stim3[6]), (stim0[26] ^ stim6[9]), (stim2[15] ^ stim0[17]), (stim6[20] ^ stim2[5]), (stim7[21] ^ stim7[16]), (stim3[0] ^ stim4[17]), (stim0[2] ^ stim2[7]), (stim4[15] ^ stim2[28]), (stim7[10] ^ stim3[10]), (stim7[9] ^ stim4[6])}; mb27 <= {(stim7[7] ^ stim7[17]), (stim1[2] ^ stim7[15]), (stim2[18] ^ stim6[8]), (stim4[27] ^ stim0[3]), (stim7[4] ^ stim6[16]), (stim6[6] ^ stim2[6]), (stim2[12] ^ stim0[1]), (stim5[6] ^ stim0[21])}; end
always @(posedge clk) mp28 <= mp28 + ma26 * mb27;
always @(posedge clk) begin
 if (stim3[5] & stim2[2] & stim4[11]) st29 <= ST29_0;
 else case (st29)
  ST29_0: st29 <= stim2[14] ? ST29_1 : ST29_15;
  ST29_1: st29 <= stim1[1] ? ST29_2 : ST29_13;
  ST29_2: st29 <= stim7[22] ? ST29_3 : stim2[9] ? ST29_6 : ST29_10;
  ST29_3: st29 <= stim2[20] ? ST29_4 : ST29_14;
  ST29_4: st29 <= stim1[29] ? ST29_5 : ST29_4;
  ST29_5: st29 <= stim5[8] ? ST29_6 : stim1[18] ? ST29_8 : ST29_10;
  ST29_6: st29 <= stim1[10] ? ST29_7 : ST29_13;
  ST29_7: st29 <= stim4[1] ? ST29_8 : stim0[29] ? ST29_13 : ST29_4;
  ST29_8: st29 <= stim3[14] ? ST29_9 : ST29_12;
  ST29_9: st29 <= stim7[2] ? ST29_10 : ST29_1;
  ST29_10: st29 <= stim3[13] ? ST29_11 : stim4[19] ? ST29_8 : ST29_1;
  ST29_11: st29 <= stim7[19] ? ST29_12 : ST29_7;
  ST29_12: st29 <= stim3[8] ? ST29_13 : stim3[28] ? ST29_14 : ST29_16;
  ST29_13: st29 <= stim1[13] ? ST29_14 : ST29_7;
  ST29_14: st29 <= stim6[1] ? ST29_15 : ST29_8;
  ST29_15: st29 <= stim0[14] ? ST29_16 : ST29_1;
  ST29_16: st29 <= stim1[11] ? ST29_0 : stim1[15] ? ST29_8 : ST29_7;
  default: st29 <= ST29_0;
 endcase
end
always @(posedge clk) fo30 <= {(st29 == ST29_1 | st29 == ST29_12), (st29 == ST29_2 | st29 == ST29_10 | st29 == ST29_13)};
always @(posedge clk) begin
  if (stim2[23]) rg31 <= {(stim2[19] ^ stim7[13]), (stim3[25] ^ stim2[25]), (stim6[3] ^ stim7[23]), (stim5[12] ^ stim4[4]), (stim1[17] ^ stim3[19]), (stim7[12] ^ stim1[3]), (stim2[1] ^ stim4[0]), (stim4[18] ^ stim7[0]), (stim3[24] ^ stim2[26]), (stim4[12] ^ stim1[6]), (stim5[22] ^ stim0[22]), (stim1[5] ^ stim0[0]), (stim1[7] ^ stim5[19]), (stim6[19] ^ stim1[25]), (stim3[15] ^ stim5[1]), (stim3[4] ^ stim4[16]), (stim5[13] ^ stim4[13]), (stim6[4] ^ stim0[16]), (stim4[7] ^ stim4[8]), (stim3[7] ^ stim4[10]), (stim5[26] ^ stim3[20]), (stim4[9] ^ stim1[30]), (stim2[10] ^ stim6[5]), (stim2[4] ^ stim6[15])};
end
always @(posedge clk) lim33 <= {(stim7[3] ^ stim6[25]), (stim4[20] ^ stim7[20]), (stim1[28] ^ stim7[24]), (stim7[18] ^ stim2[13]), (stim2[24] ^ stim0[6]), (stim7[6] ^ stim5[4]), (stim4[25] ^ stim2[21]), (stim0[20] ^ stim6[10]), (stim1[14] ^ stim0[28]), (stim2[29] ^ stim5[17]), (stim1[26] ^ stim2[22]), (stim4[23] ^ stim7[8]), (stim5[15] ^ stim4[3]), (stim3[17] ^ stim5[7]), (stim0[4] ^ stim4[21]), (stim1[21] ^ stim5[10])};
always @(posedge clk) cmp34 <= cnt32 >= lim33;
always @(posedge clk) case (st35)
  RUN: st35 <= cmp34 ? HOLD : RUN;
  HOLD: st35 <= stim1[0] ? CLR : WAIT;
  CLR: st35 <= RUN;
  WAIT: st35 <= stim7[14] ? RUN : WAIT;
endcase
always @(posedge clk) if (st35 == CLR) cnt32 <= {16{1'b0}}; else if (st35 == RUN) cnt32 <= cnt32 + 16'd1;
always @(posedge clk) y_q <= f3 ^ (^fq8) ^ (^fc7) ^ (^wp5) ^ (^rp6) ^ (^rg13) ^ (^fq18) ^ (^fc17) ^ (^wp15) ^ (^rp16) ^ (^sr23) ^ (^crc24) ^ (^mp28) ^ (^st29) ^ (^fo30) ^ (^rg31) ^ (^cnt32) ^ (^st35) ^ cmp34;
assign y = y_q;
endmodule
