module top (
  input clk,
  output y
);
reg [7:0] cnt1;
reg [31:0] stim0;
reg [15:0] crc2;
function [15:0] crcf3(input [15:0] cc, input [7:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[15] ^ x[7 - i]) ? ((rr << 1) ^ 16'h1021) : (rr << 1);
    crcf3 = rr;
  end
endfunction
reg [30:0] stim1;
reg [29:0] stim2;
wire [31:0] pi4 = {(stim0[23] ^ stim0[28]), (stim0[16] ^ stim0[18]), (stim0[6] ^ stim0[3]), (stim0[31] ^ stim0[30]), (stim0[11] ^ stim0[12]), (stim0[29] ^ stim0[15]), (stim0[24] ^ stim0[26]), (stim0[22] ^ stim0[0]), (stim0[25] ^ stim0[8]), (stim0[7] ^ stim1[11]), (stim1[23] ^ stim1[27]), (stim1[14] ^ stim1[5]), (stim1[10] ^ stim1[4]), (stim1[19] ^ stim1[13]), (stim1[1] ^ stim1[24]), (stim1[30] ^ stim1[21]), (stim1[17] ^ stim1[12]), (stim1[28] ^ stim1[26]), (stim1[6] ^ stim1[8]), (stim1[7] ^ stim1[9]), (stim1[29] ^ stim1[15]), (stim1[16] ^ stim1[22]), (stim1[25] ^ stim1[18]), (stim1[0] ^ stim1[3]), (stim1[2] ^ stim1[20]), (stim2[18] ^ stim2[29]), (stim2[25] ^ stim2[13]), (stim2[16] ^ stim2[27]), (stim2[24] ^ stim2[23]), (stim2[10] ^ stim2[28]), (stim2[15] ^ stim2[19]), (stim2[6] ^ stim2[14])};
reg [31:0] pp5;
reg [31:0] pp6;
reg [31:0] pp7;
reg [31:0] pp8;
reg [31:0] pp9;
reg [7:0] cnt10;
reg [15:0] crc11;
function [15:0] crcf12(input [15:0] cc, input [7:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[15] ^ x[7 - i]) ? ((rr << 1) ^ 16'h1021) : (rr << 1);
    crcf12 = rr;
  end
endfunction
reg [63:0] lf13;
(* ramstyle = "M9K, no_rw_check" *) reg [17:0] fm14 [0:63];
reg [5:0] wp15, rp16;
reg [6:0] fc17;
reg [17:0] fq18;
wire ff19 = (fc17 == 7'd64);
wire fe20 = (fc17 == 7'd0);
wire wr21 = stim2[8] & ~ff19;
wire rd22 = stim2[22] & ~fe20;
reg [28:0] stim3;
(* ramstyle = "M9K, no_rw_check" *) reg [17:0] ram23 [0:511];
reg [8:0] ad24;
reg [8:0] ad25;
reg [17:0] rq26;
reg [27:0] stim4;
reg [26:0] stim5;
localparam [3:0] ST27_0 = 4'd0;
localparam [3:0] ST27_1 = 4'd1;
localparam [3:0] ST27_2 = 4'd2;
localparam [3:0] ST27_3 = 4'd3;
localparam [3:0] ST27_4 = 4'd4;
localparam [3:0] ST27_5 = 4'd5;
localparam [3:0] ST27_6 = 4'd6;
localparam [3:0] ST27_7 = 4'd7;
localparam [3:0] ST27_8 = 4'd8;
localparam [3:0] ST27_9 = 4'd9;
localparam [3:0] ST27_10 = 4'd10;
localparam [3:0] ST27_11 = 4'd11;
localparam [3:0] ST27_12 = 4'd12;
localparam [3:0] ST27_13 = 4'd13;
reg [3:0] st27;
reg [0:0] fo28;
reg [15:0] a29, b30;
reg [25:0] stim6;
reg [24:0] stim7;
reg f31;
reg [7:0] rg32;
wire [2:0] sel33 = {stim0[14], stim4[25], stim6[2]};
reg [1:0] mx34;
reg [15:0] lf35;
reg [15:0] acc36;
reg lt37;
reg [31:0] lf38;
reg [31:0] acc39;
reg lt40;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  cnt1 <= cnt1 + 8'd1;
end
always @(posedge clk) if (stim0[5] & stim0[10] & stim0[4]) crc2 <= {16{1'b1}}; else if (stim0[20]) crc2 <= crcf3(crc2, {stim0[21], stim0[1], stim0[19], stim0[13], stim0[9], stim0[27], stim0[17], stim0[14]});
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) pp5 <= pi4 ^ 32'h31F6959B;
always @(posedge clk) pp6 <= ~pp5;
always @(posedge clk) pp7 <= {pp6[30:0], pp6[31]};
always @(posedge clk) pp8 <= pp7 ^ 32'hB09F8D96;
always @(posedge clk) pp9 <= pp8 ^ {pp8[30:0], pp8[31]} ^ {pp8[29:0], pp8[31:30]};
always @(posedge clk) begin
  cnt10 <= cnt10 + 8'd1;
end
always @(posedge clk) if (stim2[5] & stim2[20] & stim2[26]) crc11 <= {16{1'b1}}; else if (stim2[4]) crc11 <= crcf12(crc11, {stim2[3], stim2[2], stim2[12], stim2[7], stim2[9], stim2[1], stim2[11], stim2[17]});
always @(posedge clk) lf13 <= {lf13[62:0], ~(lf13[63] ^ lf13[62] ^ lf13[60] ^ lf13[59])};
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) begin
  if (wr21) begin fm14[wp15] <= {stim2[0], stim3[24], stim3[23], stim3[2], stim3[9], stim3[25], stim3[11], stim3[19], stim3[6], stim3[12], stim3[1], stim3[17], stim3[0], stim3[13], stim3[22], stim3[14], stim3[3], stim3[15]}; wp15 <= wp15 + 6'd1; end
  if (rd22) begin fq18 <= fm14[rp16]; rp16 <= rp16 + 6'd1; end
  fc17 <= fc17 + {{6{1'b0}}, wr21} - {{6{1'b0}}, rd22};
end
always @(posedge clk) ad24 <= ad24 + 9'd1;
always @(posedge clk) ad25 <= ad25 + 9'd1;
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) begin
  if (stim3[20]) ram23[ad24] <= {stim3[28], stim3[10], stim3[16], stim3[7], stim3[27], stim3[5], stim3[21], stim3[4], stim3[18], stim3[26], stim3[8], stim4[16], stim4[8], stim4[2], stim4[0], stim4[25], stim4[24], stim4[26]};
  rq26 <= ram23[ad25];
end
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) begin
 if (stim5[18] & stim5[5] & stim5[2]) st27 <= ST27_0;
 else case (st27)
  ST27_0: st27 <= stim4[19] ? ST27_1 : stim4[4] ? ST27_3 : ST27_3;
  ST27_1: st27 <= stim4[1] ? ST27_2 : stim4[20] ? ST27_0 : ST27_12;
  ST27_2: st27 <= stim4[7] ? ST27_3 : ST27_7;
  ST27_3: st27 <= stim4[18] ? ST27_4 : ST27_11;
  ST27_4: st27 <= stim4[23] ? ST27_5 : stim4[12] ? ST27_1 : ST27_2;
  ST27_5: st27 <= stim4[22] ? ST27_6 : stim4[14] ? ST27_1 : ST27_9;
  ST27_6: st27 <= stim4[10] ? ST27_7 : stim4[13] ? ST27_7 : ST27_12;
  ST27_7: st27 <= stim4[11] ? ST27_8 : ST27_0;
  ST27_8: st27 <= stim4[21] ? ST27_9 : stim4[3] ? ST27_0 : ST27_5;
  ST27_9: st27 <= stim4[5] ? ST27_10 : stim4[27] ? ST27_8 : ST27_6;
  ST27_10: st27 <= stim4[17] ? ST27_11 : ST27_8;
  ST27_11: st27 <= stim5[17] ? ST27_12 : stim5[3] ? ST27_7 : ST27_2;
  ST27_12: st27 <= stim5[1] ? ST27_13 : stim5[24] ? ST27_5 : ST27_10;
  ST27_13: st27 <= stim5[6] ? ST27_0 : stim5[10] ? ST27_2 : ST27_12;
  default: st27 <= ST27_0;
 endcase
end
always @(posedge clk) fo28 <= {(st27 == ST27_12 | st27 == ST27_5 | st27 == ST27_11 | st27 == ST27_10 | st27 == ST27_3)};
always @(posedge clk) stim6 <= {stim6[24:0], ~(stim6[25] ^ stim6[5] ^ stim6[1] ^ stim6[0])};
always @(posedge clk) stim7 <= {stim7[23:0], ~(stim7[24] ^ stim7[21])};
always @(posedge clk) begin a29 <= {(stim5[0] ^ stim5[16]), (stim5[23] ^ stim5[15]), (stim5[21] ^ stim5[20]), (stim5[13] ^ stim5[8]), (stim5[19] ^ stim5[26]), (stim5[7] ^ stim5[9]), (stim5[11] ^ stim5[12]), (stim5[25] ^ stim5[14]), (stim5[4] ^ stim6[6]), (stim6[3] ^ stim6[15]), (stim6[21] ^ stim6[14]), (stim6[20] ^ stim6[2]), (stim6[9] ^ stim6[17]), (stim6[12] ^ stim6[4]), (stim6[25] ^ stim6[24]), (stim6[22] ^ stim6[8])}; b30 <= {(stim6[23] ^ stim6[5]), (stim6[18] ^ stim6[7]), (stim6[1] ^ stim6[0]), (stim6[13] ^ stim6[11]), (stim6[16] ^ stim6[10]), (stim6[19] ^ stim7[5]), (stim7[11] ^ stim7[19]), (stim7[21] ^ stim7[17]), (stim7[10] ^ stim7[22]), (stim7[8] ^ stim7[6]), (stim7[14] ^ stim7[4]), (stim7[18] ^ stim7[7]), (stim7[24] ^ stim7[16]), (stim7[1] ^ stim7[23]), (stim7[3] ^ stim7[12]), (stim7[2] ^ stim7[20])}; end
always @(posedge clk) f31 <= a29 <= b30;
always @(posedge clk) begin
  if (stim7[0] & stim7[13]) rg32 <= {(stim7[9] ^ stim7[15]), (stim3[24] ^ stim3[23]), (stim0[2] ^ stim2[18]), (stim3[2] ^ stim4[16]), (stim5[22] ^ stim5[17]), (stim5[3] ^ stim0[5]), (stim2[29] ^ stim7[5]), (stim0[10] ^ stim2[25])};
  else if (stim3[9]) rg32 <= {(stim0[4] ^ stim3[25]), (stim5[1] ^ stim3[11]), (stim3[19] ^ stim0[20]), (stim7[11] ^ stim6[6]), (stim7[19] ^ stim2[13]), (stim0[21] ^ stim2[16]), (stim1[11] ^ stim1[23]), (stim6[3] ^ stim1[27])};
end
always @(posedge clk) case (sel33)
  3'd0: mx34 <= {(stim6[15] ^ stim1[14]), (stim3[6] ^ stim7[21])};
  3'd1: mx34 <= {(stim6[21] ^ stim3[12]), (stim0[1] ^ stim5[24])};
  3'd2: mx34 <= {(stim0[19] ^ stim6[14]), (stim0[13] ^ stim7[17])};
  3'd3: mx34 <= {(stim1[5] ^ stim5[6]), (stim7[10] ^ stim5[10])};
  3'd4: mx34 <= {(stim7[22] ^ stim3[1]), (stim5[18] ^ stim7[8])};
  3'd5: mx34 <= {(stim6[20] ^ stim0[9]), (stim4[8] ^ stim3[17])};
  3'd6: mx34 <= {(stim0[27] ^ stim2[27]), (stim0[17] ^ stim4[2])};
  3'd7: mx34 <= {(stim4[0] ^ stim7[6]), (stim1[10] ^ stim2[24])};
  default: mx34 <= {2{1'b0}};
endcase
always @(posedge clk) lf35 <= {lf35[14:0], ~(lf35[15] ^ lf35[14] ^ lf35[12] ^ lf35[3])};
always @(posedge clk) acc36 <= acc36 + lf35;
always @(posedge clk) lt37 <= acc36 < lf35;
always @(posedge clk) lf38 <= {lf38[30:0], ~(lf38[31] ^ lf38[21] ^ lf38[1] ^ lf38[0])};
always @(posedge clk) acc39 <= acc39 + lf38;
always @(posedge clk) lt40 <= acc39 < lf38;
always @(posedge clk) y_q <= (^cnt1) ^ (^crc2) ^ (^pp9) ^ (^cnt10) ^ (^crc11) ^ (^lf13) ^ (^fq18) ^ (^fc17) ^ (^wp15) ^ (^rp16) ^ (^rq26) ^ (^st27) ^ fo28 ^ f31 ^ (^rg32) ^ (^mx34) ^ (^lf35) ^ (^acc36) ^ lt37 ^ (^lf38) ^ (^acc39) ^ lt40;
assign y = y_q;
endmodule
