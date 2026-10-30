module top (
  input clk,
  output y
);
reg [15:0] crc1;
function [15:0] crcf2(input [15:0] cc, input [7:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[15] ^ x[7 - i]) ? ((rr << 1) ^ 16'h1021) : (rr << 1);
    crcf2 = rr;
  end
endfunction
reg [31:0] stim0;
reg [15:0] sr3;
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] ram4 [0:127];
reg [6:0] ad5;
reg [6:0] ad6;
reg [15:0] rqa7, rqb8;
reg [30:0] stim1;
reg [29:0] stim2;
reg [28:0] stim3;
reg [27:0] stim4;
reg [26:0] stim5;
reg [25:0] stim6;
wire [2:0] sel9 = {stim6[23], stim6[4], stim6[17]};
reg [7:0] mx10;
reg [24:0] stim7;
wire [3:0] sel11 = {stim1[3], stim0[29], stim6[10], stim7[14]};
reg [7:0] mx12;
localparam [3:0] ST13_0 = 4'd0;
localparam [3:0] ST13_1 = 4'd1;
localparam [3:0] ST13_2 = 4'd2;
localparam [3:0] ST13_3 = 4'd3;
localparam [3:0] ST13_4 = 4'd4;
localparam [3:0] ST13_5 = 4'd5;
localparam [3:0] ST13_6 = 4'd6;
localparam [3:0] ST13_7 = 4'd7;
localparam [3:0] ST13_8 = 4'd8;
localparam [3:0] ST13_9 = 4'd9;
localparam [3:0] ST13_10 = 4'd10;
localparam [3:0] ST13_11 = 4'd11;
reg [3:0] st13;
reg [0:0] fo14;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[11] & stim0[1] & stim0[31]) crc1 <= {16{1'b1}}; else if (stim0[16]) crc1 <= crcf2(crc1, {stim0[5], stim0[13], stim0[28], stim0[22], stim0[6], stim0[15], stim0[18], stim0[19]});
always @(posedge clk) if (stim0[27] & stim0[12]) sr3 <= {stim0[2], stim0[7], stim0[30], stim0[17], stim0[23], stim0[4], stim0[9], stim0[24], stim0[8], stim0[3], stim0[20], stim0[0], stim0[29], stim0[10], stim0[26], stim0[21]}; else sr3 <= {sr3[14:0], sr3[15]};
always @(posedge clk) ad5 <= ad5 + 7'd1;
always @(posedge clk) ad6 <= ad6 + 7'd1;
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[14]) ram4[ad5] <= {stim0[25], stim1[20], stim1[15], stim1[1], stim1[22], stim1[11], stim1[14], stim1[13], stim1[2], stim1[23], stim1[12], stim1[28], stim1[18], stim1[9], stim1[26], stim1[8]};
  rqa7 <= ram4[ad5];
end
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin
  if (stim1[16]) ram4[ad6] <= {stim1[10], stim1[30], stim1[27], stim1[6], stim1[0], stim1[5], stim1[3], stim1[29], stim1[21], stim1[24], stim1[7], stim1[17], stim1[25], stim1[4], stim1[19], stim2[25]};
  rqb8 <= ram4[ad6];
end
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) stim6 <= {stim6[24:0], ~(stim6[25] ^ stim6[5] ^ stim6[1] ^ stim6[0])};
always @(posedge clk) mx10 <= (sel9 == 3'd0) ? {(stim2[15] ^ stim2[29]), (stim2[13] ^ stim2[4]), (stim2[27] ^ stim2[21]), (stim2[10] ^ stim2[22]), (stim2[8] ^ stim2[5]), (stim2[12] ^ stim2[19]), (stim2[24] ^ stim2[23]), (stim2[16] ^ stim2[3])} : (sel9 == 3'd1) ? {(stim2[20] ^ stim2[14]), (stim2[9] ^ stim2[17]), (stim2[26] ^ stim2[18]), (stim2[2] ^ stim2[1]), (stim2[0] ^ stim2[6]), (stim2[7] ^ stim2[28]), (stim2[11] ^ stim3[0]), (stim3[20] ^ stim3[13])} : (sel9 == 3'd2) ? {(stim3[16] ^ stim3[17]), (stim3[23] ^ stim3[4]), (stim3[22] ^ stim3[15]), (stim3[7] ^ stim3[18]), (stim3[1] ^ stim3[19]), (stim3[12] ^ stim3[14]), (stim3[26] ^ stim3[21]), (stim3[11] ^ stim3[28])} : (sel9 == 3'd3) ? {(stim3[2] ^ stim3[9]), (stim3[10] ^ stim3[8]), (stim3[24] ^ stim3[3]), (stim3[5] ^ stim3[27]), (stim3[6] ^ stim3[25]), (stim4[13] ^ stim4[3]), (stim4[18] ^ stim4[20]), (stim4[19] ^ stim4[25])} : (sel9 == 3'd4) ? {(stim4[1] ^ stim4[17]), (stim4[23] ^ stim4[24]), (stim4[5] ^ stim4[11]), (stim4[8] ^ stim4[27]), (stim4[14] ^ stim4[7]), (stim4[12] ^ stim4[10]), (stim4[6] ^ stim4[16]), (stim4[15] ^ stim4[4])} : (sel9 == 3'd5) ? {(stim4[26] ^ stim4[2]), (stim4[21] ^ stim4[22]), (stim4[0] ^ stim4[9]), (stim5[11] ^ stim5[26]), (stim5[24] ^ stim5[2]), (stim5[10] ^ stim5[20]), (stim5[18] ^ stim5[3]), (stim5[25] ^ stim5[23])} : (sel9 == 3'd6) ? {(stim5[9] ^ stim5[6]), (stim5[7] ^ stim5[17]), (stim5[16] ^ stim5[1]), (stim5[15] ^ stim5[22]), (stim5[13] ^ stim5[4]), (stim5[12] ^ stim5[5]), (stim5[0] ^ stim5[8]), (stim5[21] ^ stim5[14])} : {(stim5[19] ^ stim6[20]), (stim6[3] ^ stim6[22]), (stim6[9] ^ stim6[5]), (stim6[12] ^ stim6[2]), (stim6[10] ^ stim6[24]), (stim6[0] ^ stim6[14]), (stim6[6] ^ stim6[16]), (stim6[8] ^ stim6[25])};
always @(posedge clk) stim7 <= {stim7[23:0], ~(stim7[24] ^ stim7[21])};
always @(posedge clk) case (sel11)
  4'd0: mx12 <= {(stim6[13] ^ stim6[15]), (stim6[21] ^ stim6[19]), (stim6[18] ^ stim6[1]), (stim6[7] ^ stim6[11]), (stim7[0] ^ stim7[8]), (stim7[24] ^ stim7[16]), (stim7[12] ^ stim7[14]), (stim7[17] ^ stim7[9])};
  4'd1: mx12 <= {(stim7[6] ^ stim7[3]), (stim7[20] ^ stim7[23]), (stim7[21] ^ stim7[18]), (stim7[15] ^ stim7[11]), (stim7[1] ^ stim7[4]), (stim7[5] ^ stim7[2]), (stim7[22] ^ stim7[13]), (stim7[10] ^ stim7[7])};
  4'd2: mx12 <= {(stim7[19] ^ stim5[11]), (stim4[13] ^ stim0[11]), (stim6[20] ^ stim3[0]), (stim6[9] ^ stim7[0]), (stim7[8] ^ stim4[3]), (stim7[24] ^ stim6[5]), (stim3[20] ^ stim5[26]), (stim5[24] ^ stim7[16])};
  4'd3: mx12 <= {(stim2[25] ^ stim6[12]), (stim1[20] ^ stim1[15]), (stim7[12] ^ stim4[18]), (stim4[20] ^ stim1[1]), (stim6[2] ^ stim4[19]), (stim5[2] ^ stim2[15]), (stim5[10] ^ stim7[14]), (stim6[10] ^ stim4[25])};
  4'd4: mx12 <= {(stim4[1] ^ stim3[13]), (stim2[29] ^ stim5[20]), (stim4[17] ^ stim2[13]), (stim5[18] ^ stim3[16]), (stim3[17] ^ stim4[23]), (stim4[24] ^ stim4[5]), (stim0[1] ^ stim4[11]), (stim4[8] ^ stim6[24])};
  4'd5: mx12 <= {(stim5[3] ^ stim0[31]), (stim0[16] ^ stim1[22]), (stim4[27] ^ stim4[14]), (stim0[5] ^ stim4[7]), (stim7[17] ^ stim5[25]), (stim7[9] ^ stim5[23]), (stim3[22] ^ stim6[0]), (stim7[6] ^ stim4[12])};
  4'd6: mx12 <= {(stim2[4] ^ stim2[27]), (stim7[3] ^ stim6[14]), (stim1[11] ^ stim2[21]), (stim2[10] ^ stim5[9]), (stim1[14] ^ stim0[13]), (stim4[10] ^ stim4[6]), (stim2[22] ^ stim7[20]), (stim4[16] ^ stim5[6])};
  4'd7: mx12 <= {(stim4[15] ^ stim6[6]), (stim2[8] ^ stim4[4]), (stim7[23] ^ stim2[5]), (stim3[15] ^ stim6[16]), (stim6[8] ^ stim7[21]), (stim2[12] ^ stim1[13]), (stim3[7] ^ stim0[28]), (stim4[26] ^ stim5[7])};
  4'd8: mx12 <= {(stim6[25] ^ stim7[18]), (stim7[15] ^ stim1[2]), (stim6[23] ^ stim7[11]), (stim0[22] ^ stim0[6]), (stim2[19] ^ stim6[4]), (stim3[18] ^ stim6[17]), (stim3[1] ^ stim0[15]), (stim5[17] ^ stim3[19])};
  4'd9: mx12 <= {(stim2[24] ^ stim0[18]), (stim1[23] ^ stim6[13]), (stim6[15] ^ stim6[21]), (stim3[12] ^ stim2[23]), (stim6[19] ^ stim0[19]), (stim4[2] ^ stim3[14]), (stim2[20] ^ stim7[1]), (stim6[18] ^ stim0[27])};
  4'd10: mx12 <= {(stim4[21] ^ stim7[4]), (stim4[22] ^ stim3[26]), (stim5[16] ^ stim7[5]), (stim5[1] ^ stim3[21]), (stim7[2] ^ stim4[0]), (stim0[12] ^ stim6[1]), (stim2[14] ^ stim3[11]), (stim3[28] ^ stim0[2])};
  4'd11: mx12 <= {(stim6[7] ^ stim7[22]), (stim3[2] ^ stim7[13]), (stim1[12] ^ stim4[9]), (stim6[11] ^ stim4[13]), (stim7[10] ^ stim4[3]), (stim3[9] ^ stim1[28]), (stim2[9] ^ stim5[15]), (stim5[22] ^ stim5[13])};
  4'd12: mx12 <= {(stim1[18] ^ stim5[4]), (stim7[7] ^ stim4[18]), (stim0[7] ^ stim4[20]), (stim2[17] ^ stim6[20]), (stim0[30] ^ stim0[17]), (stim1[9] ^ stim1[26]), (stim5[12] ^ stim7[19]), (stim6[3] ^ stim1[8])};
  4'd13: mx12 <= {(stim0[23] ^ stim3[24]), (stim1[16] ^ stim5[5]), (stim6[22] ^ stim4[19]), (stim0[4] ^ stim5[0]), (stim7[0] ^ stim6[9]), (stim3[3] ^ stim4[25]), (stim5[8] ^ stim4[1]), (stim6[5] ^ stim5[21])};
  4'd14: mx12 <= {(stim3[5] ^ stim1[10]), (stim4[17] ^ stim1[30]), (stim3[27] ^ stim7[8]), (stim3[6] ^ stim5[14]), (stim2[0] ^ stim1[27]), (stim5[19] ^ stim7[24]), (stim0[9] ^ stim1[6]), (stim0[24] ^ stim3[25])};
  4'd15: mx12 <= {(stim0[8] ^ stim3[0]), (stim7[16] ^ stim0[3]), (stim1[0] ^ stim2[6]), (stim7[12] ^ stim6[12]), (stim5[24] ^ stim1[5]), (stim2[7] ^ stim6[2]), (stim0[20] ^ stim4[23]), (stim0[0] ^ stim2[28])};
  default: mx12 <= {8{1'b0}};
endcase
always @(posedge clk) begin
 if (stim6[25] & stim4[8] & stim0[26]) st13 <= ST13_0;
 else case (st13)
  ST13_0: st13 <= stim3[20] ? ST13_1 : stim1[29] ? ST13_2 : ST13_7;
  ST13_1: st13 <= stim7[17] ? ST13_2 : stim3[13] ? ST13_1 : ST13_3;
  ST13_2: st13 <= stim6[24] ? ST13_3 : ST13_11;
  ST13_3: st13 <= stim0[10] ? ST13_4 : ST13_3;
  ST13_4: st13 <= stim4[24] ? ST13_5 : ST13_1;
  ST13_5: st13 <= stim6[0] ? ST13_6 : ST13_8;
  ST13_6: st13 <= stim6[14] ? ST13_7 : ST13_4;
  ST13_7: st13 <= stim6[6] ? ST13_8 : stim4[11] ? ST13_2 : ST13_7;
  ST13_8: st13 <= stim6[16] ? ST13_9 : ST13_5;
  ST13_9: st13 <= stim5[10] ? ST13_10 : stim6[8] ? ST13_11 : ST13_10;
  ST13_10: st13 <= stim3[17] ? ST13_11 : stim2[29] ? ST13_3 : ST13_4;
  ST13_11: st13 <= stim7[9] ? ST13_0 : ST13_4;
  default: st13 <= ST13_0;
 endcase
end
always @(posedge clk) fo14 <= {(st13 == ST13_0 | st13 == ST13_11)};
always @(posedge clk) y_q <= (^crc1) ^ (^sr3) ^ (^rqa7) ^ (^rqb8) ^ (^mx10) ^ (^mx12) ^ (^st13) ^ fo14;
assign y = y_q;
endmodule
