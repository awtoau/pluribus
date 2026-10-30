module top (
  input clk,
  output y
);
reg [19:0] lf1;
reg [31:0] stim0;
reg [7:0] cnt2;
(* ramstyle = "M9K, no_rw_check" *) reg [7:0] fm3 [0:63];
reg [5:0] wp4, rp5;
reg [6:0] fc6;
reg [7:0] fq7;
wire ff8 = (fc6 == 7'd64);
wire fe9 = (fc6 == 7'd0);
wire wr10 = stim0[3] & ~ff8;
wire rd11 = stim0[15] & ~fe9;
reg [11:0] sum12;
reg [7:0] cnt13;
reg [15:0] crc14;
function [15:0] crcf15(input [15:0] cc, input [7:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[15] ^ x[7 - i]) ? ((rr << 1) ^ 16'h1021) : (rr << 1);
    crcf15 = rr;
  end
endfunction
reg [5:0] cnt16;
reg [30:0] stim1;
reg [15:0] lf17;
reg [15:0] acc18;
reg lt19;
(* ramstyle = "M9K, no_rw_check" *) reg [17:0] fm20 [0:15];
reg [3:0] wp21, rp22;
reg [4:0] fc23;
reg [17:0] fq24;
wire ff25 = (fc23 == 5'd16);
wire fe26 = (fc23 == 5'd0);
wire wr27 = stim1[27] & ~ff25;
wire rd28 = stim1[26] & ~fe26;
reg [11:0] a29, b30;
reg [29:0] stim2;
reg [28:0] stim3;
reg f31;
reg [7:0] sr32;
reg [8:0] ma33;
reg [11:0] mb34;
reg [20:0] mp35;
reg [27:0] stim4;
reg [26:0] stim5;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) lf1 <= {lf1[18:0], ~(lf1[19] ^ lf1[16] ^ stim0[31])};
always @(posedge clk) begin
  cnt2 <= cnt2 + 8'd1;
end
always @(posedge clk) begin
  if (wr10) begin fm3[wp4] <= {stim0[5], stim0[29], stim0[28], stim0[23], stim0[9], stim0[25], stim0[0], stim0[12]}; wp4 <= wp4 + 6'd1; end
  if (rd11) begin fq7 <= fm3[rp5]; rp5 <= rp5 + 6'd1; end
  fc6 <= fc6 + {{6{1'b0}}, wr10} - {{6{1'b0}}, rd11};
end
always @(posedge clk) sum12 <= sum12 + fq7;
always @(posedge clk) begin
  cnt13 <= cnt13 + 8'd1;
end
always @(posedge clk) if (stim0[20] & stim0[19] & stim0[11]) crc14 <= {16{1'b1}}; else if (stim0[21]) crc14 <= crcf15(crc14, {stim0[7], stim0[13], stim0[16], stim0[26], stim0[2], stim0[22], stim0[18], stim0[4]});
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[27] & stim0[10]) cnt16 <= {stim0[30], stim0[17], stim0[14], stim0[8], stim1[6], stim1[20]};
  else cnt16 <= cnt16 + 6'd1;
end
always @(posedge clk) lf17 <= {lf17[14:0], ~(lf17[15] ^ lf17[14] ^ lf17[12] ^ lf17[3])};
always @(posedge clk) acc18 <= acc18 + lf17;
always @(posedge clk) lt19 <= acc18 < lf17;
always @(posedge clk) begin
  if (wr27) begin fm20[wp21] <= {stim1[2], stim1[14], stim1[8], stim1[25], stim1[18], stim1[21], stim1[7], stim1[19], stim1[29], stim1[17], stim1[0], stim1[12], stim1[10], stim1[23], stim1[22], stim1[5], stim1[15], stim1[16]}; wp21 <= wp21 + 4'd1; end
  if (rd28) begin fq24 <= fm20[rp22]; rp22 <= rp22 + 4'd1; end
  fc23 <= fc23 + {{4{1'b0}}, wr27} - {{4{1'b0}}, rd28};
end
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) begin a29 <= {(stim1[9] ^ stim1[11]), (stim1[13] ^ stim1[4]), (stim1[1] ^ stim1[24]), (stim1[28] ^ stim1[3]), (stim1[30] ^ stim2[14]), (stim2[17] ^ stim2[21]), (stim2[26] ^ stim2[22]), (stim2[2] ^ stim2[3]), (stim2[15] ^ stim2[29]), (stim2[5] ^ stim2[0]), (stim2[25] ^ stim2[19]), (stim2[8] ^ stim2[28])}; b30 <= {(stim2[12] ^ stim2[4]), (stim2[10] ^ stim2[6]), (stim2[27] ^ stim2[18]), (stim2[1] ^ stim2[13]), (stim2[16] ^ stim2[23]), (stim2[20] ^ stim2[7]), (stim2[11] ^ stim2[24]), (stim2[9] ^ stim3[5]), (stim3[8] ^ stim3[3]), (stim3[25] ^ stim3[7]), (stim3[10] ^ stim3[24]), (stim3[15] ^ stim3[13])}; end
always @(posedge clk) f31 <= a29 >= b30;
always @(posedge clk) if (stim3[22] & stim3[20]) sr32 <= {stim3[11], stim3[16], stim3[19], stim3[28], stim3[0], stim3[27], stim3[18], stim3[1]}; else sr32 <= {sr32[6:0], stim3[21]};
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) begin ma33 <= {(stim3[14] ^ stim3[6]), (stim3[23] ^ stim3[2]), (stim3[9] ^ stim3[17]), (stim3[26] ^ stim3[12]), (stim3[4] ^ stim4[1]), (stim4[12] ^ stim4[24]), (stim4[15] ^ stim4[16]), (stim4[21] ^ stim4[4]), (stim4[14] ^ stim4[17])}; mb34 <= {(stim4[6] ^ stim4[11]), (stim4[5] ^ stim4[7]), (stim4[2] ^ stim4[18]), (stim4[22] ^ stim4[27]), (stim4[9] ^ stim4[19]), (stim4[0] ^ stim4[26]), (stim4[23] ^ stim4[20]), (stim4[10] ^ stim4[8]), (stim4[25] ^ stim4[13]), (stim4[3] ^ stim5[25]), (stim5[26] ^ stim5[14]), (stim5[18] ^ stim5[2])}; end
always @(posedge clk) mp35 <= ma33 * mb34;
always @(posedge clk) y_q <= (^lf1) ^ (^cnt2) ^ (^fq7) ^ (^fc6) ^ (^wp4) ^ (^rp5) ^ (^sum12) ^ (^cnt13) ^ (^crc14) ^ (^cnt16) ^ (^lf17) ^ (^acc18) ^ lt19 ^ (^fq24) ^ (^fc23) ^ (^wp21) ^ (^rp22) ^ f31 ^ (^sr32) ^ (^mp35);
assign y = y_q;
endmodule
