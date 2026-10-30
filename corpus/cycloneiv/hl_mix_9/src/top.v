module top (
  input clk,
  output y
);
reg [31:0] crc1;
function [31:0] crcf2(input [31:0] cc, input [7:0] x);
  integer i; reg [31:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[31] ^ x[7 - i]) ? ((rr << 1) ^ 32'h4C11DB7) : (rr << 1);
    crcf2 = rr;
  end
endfunction
reg [31:0] stim0;
(* ramstyle = "M9K, no_rw_check" *) reg [7:0] ram3 [0:255];
reg [7:0] ad4;
reg [7:0] ad5;
reg [7:0] rqa6, rqb7;
reg signed [8:0] ma8;
reg signed [15:0] mb9;
reg signed [24:0] mp10;
reg [30:0] stim1;
reg [29:0] stim2;
reg [28:0] stim3;
localparam [3:0] ST11_0 = 4'd0;
localparam [3:0] ST11_1 = 4'd1;
localparam [3:0] ST11_2 = 4'd2;
localparam [3:0] ST11_3 = 4'd3;
localparam [3:0] ST11_4 = 4'd4;
localparam [3:0] ST11_5 = 4'd5;
localparam [3:0] ST11_6 = 4'd6;
localparam [3:0] ST11_7 = 4'd7;
localparam [3:0] ST11_8 = 4'd8;
reg [3:0] st11;
reg [1:0] fo12;
(* ramstyle = "M9K, no_rw_check" *) reg [31:0] ram13 [0:255];
reg [7:0] ad14;
reg [7:0] ad15;
reg [31:0] rqa16, rqb17;
reg [27:0] stim4;
reg [26:0] stim5;
reg [31:0] a18, b19;
reg [25:0] stim6;
reg [24:0] stim7;
reg f20;
reg [7:0] cnt21;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[18] & stim0[30] & stim0[15]) crc1 <= {32{1'b1}}; else if (stim0[21]) crc1 <= crcf2(crc1, {stim0[25], stim0[5], stim0[19], stim0[23], stim0[14], stim0[31], stim0[6], stim0[10]});
always @(posedge clk) ad4 <= ad4 + 8'd1;
always @(posedge clk) ad5 <= ad5 + 8'd1;
always @(posedge clk) begin
  if (stim0[1]) ram3[ad4] <= {stim0[16], stim0[9], stim0[3], stim0[22], stim0[12], stim0[4], stim0[2], stim0[26]};
  rqa6 <= ram3[ad4];
end
always @(posedge clk) begin
  if (stim0[24]) ram3[ad5] <= {stim0[8], stim0[0], stim0[13], stim0[29], stim0[27], stim0[11], stim0[17], stim0[20]};
  rqb7 <= ram3[ad5];
end
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin ma8 <= {(stim0[7] ^ stim0[28]), (stim1[19] ^ stim1[13]), (stim1[5] ^ stim1[20]), (stim1[2] ^ stim1[26]), (stim1[29] ^ stim1[21]), (stim1[17] ^ stim1[16]), (stim1[27] ^ stim1[23]), (stim1[7] ^ stim1[0]), (stim1[18] ^ stim1[6])}; mb9 <= {(stim1[9] ^ stim1[4]), (stim1[14] ^ stim1[15]), (stim1[11] ^ stim1[24]), (stim1[12] ^ stim1[25]), (stim1[28] ^ stim1[1]), (stim1[8] ^ stim1[22]), (stim1[10] ^ stim1[30]), (stim1[3] ^ stim2[25]), (stim2[11] ^ stim2[12]), (stim2[24] ^ stim2[27]), (stim2[26] ^ stim2[18]), (stim2[9] ^ stim2[22]), (stim2[10] ^ stim2[13]), (stim2[17] ^ stim2[7]), (stim2[0] ^ stim2[19]), (stim2[29] ^ stim2[1])}; end
always @(posedge clk) mp10 <= mp10 + ma8 * mb9;
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) begin
 if (stim3[0] & stim3[17] & stim3[23]) st11 <= ST11_0;
 else case (st11)
  ST11_0: st11 <= stim2[8] ? ST11_1 : ST11_5;
  ST11_1: st11 <= stim2[4] ? ST11_2 : stim2[23] ? ST11_1 : ST11_8;
  ST11_2: st11 <= stim2[28] ? ST11_3 : ST11_6;
  ST11_3: st11 <= stim2[14] ? ST11_4 : ST11_5;
  ST11_4: st11 <= stim2[5] ? ST11_5 : stim2[3] ? ST11_5 : ST11_1;
  ST11_5: st11 <= stim2[16] ? ST11_6 : stim2[6] ? ST11_5 : ST11_1;
  ST11_6: st11 <= stim2[21] ? ST11_7 : stim3[18] ? ST11_1 : ST11_4;
  ST11_7: st11 <= stim3[7] ? ST11_8 : stim3[4] ? ST11_6 : ST11_8;
  ST11_8: st11 <= stim3[26] ? ST11_0 : stim3[2] ? ST11_0 : ST11_2;
  default: st11 <= ST11_0;
 endcase
end
always @(posedge clk) fo12 <= {(st11 == ST11_1), (st11 == ST11_3 | st11 == ST11_0 | st11 == ST11_8)};
always @(posedge clk) ad14 <= ad14 + 8'd1;
always @(posedge clk) ad15 <= ad15 + 8'd1;
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) begin
  if (stim3[22]) ram13[ad14] <= {stim3[8], stim3[11], stim3[24], stim3[10], stim3[19], stim3[21], stim3[5], stim3[3], stim3[15], stim3[13], stim3[25], stim3[16], stim3[12], stim3[20], stim3[9], stim3[14], stim3[6], stim3[1], stim3[28], stim3[27], stim4[15], stim4[1], stim4[12], stim4[16], stim4[26], stim4[25], stim4[10], stim4[23], stim4[4], stim4[3], stim4[14], stim4[0]};
  rqa16 <= ram13[ad14];
end
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) begin
  if (stim4[8]) ram13[ad15] <= {stim4[17], stim4[20], stim4[18], stim4[24], stim4[5], stim4[6], stim4[22], stim4[2], stim4[9], stim4[13], stim4[19], stim4[27], stim4[7], stim4[21], stim4[11], stim5[7], stim5[20], stim5[14], stim5[0], stim5[22], stim5[5], stim5[16], stim5[26], stim5[2], stim5[8], stim5[6], stim5[10], stim5[13], stim5[3], stim5[12], stim5[23], stim5[25]};
  rqb17 <= ram13[ad15];
end
always @(posedge clk) stim6 <= {stim6[24:0], ~(stim6[25] ^ stim6[5] ^ stim6[1] ^ stim6[0])};
always @(posedge clk) stim7 <= {stim7[23:0], ~(stim7[24] ^ stim7[21])};
always @(posedge clk) begin a18 <= {(stim5[24] ^ stim5[17]), (stim5[9] ^ stim5[19]), (stim5[1] ^ stim5[15]), (stim5[18] ^ stim5[4]), (stim5[11] ^ stim5[21]), (stim6[2] ^ stim6[4]), (stim6[1] ^ stim6[15]), (stim6[20] ^ stim6[18]), (stim6[3] ^ stim6[8]), (stim6[21] ^ stim6[25]), (stim6[11] ^ stim6[5]), (stim6[24] ^ stim6[22]), (stim6[23] ^ stim6[12]), (stim6[14] ^ stim6[10]), (stim6[0] ^ stim6[19]), (stim6[9] ^ stim6[16]), (stim6[13] ^ stim6[17]), (stim6[7] ^ stim6[6]), (stim7[0] ^ stim7[15]), (stim7[24] ^ stim7[4]), (stim7[12] ^ stim7[17]), (stim7[2] ^ stim7[20]), (stim7[16] ^ stim7[3]), (stim7[8] ^ stim7[1]), (stim7[21] ^ stim7[14]), (stim7[22] ^ stim7[19]), (stim7[5] ^ stim7[7]), (stim7[11] ^ stim7[23]), (stim7[6] ^ stim7[10]), (stim7[13] ^ stim7[18]), (stim7[9] ^ stim4[15]), (stim7[0] ^ stim6[2])}; b19 <= {(stim7[15] ^ stim1[19]), (stim5[7] ^ stim3[18]), (stim2[25] ^ stim3[7]), (stim6[4] ^ stim3[4]), (stim3[26] ^ stim3[2]), (stim3[0] ^ stim6[20]), (stim3[17] ^ stim2[11]), (stim4[1] ^ stim3[23]), (stim7[24] ^ stim5[20]), (stim0[18] ^ stim0[30]), (stim1[13] ^ stim0[15]), (stim7[4] ^ stim4[12]), (stim3[22] ^ stim0[21]), (stim6[18] ^ stim1[5]), (stim2[12] ^ stim5[14]), (stim5[0] ^ stim6[3]), (stim1[20] ^ stim3[8]), (stim4[16] ^ stim4[26]), (stim0[25] ^ stim6[8]), (stim5[22] ^ stim1[2]), (stim6[21] ^ stim1[26]), (stim7[2] ^ stim0[5]), (stim6[25] ^ stim1[29]), (stim5[5] ^ stim1[21]), (stim2[24] ^ stim7[20]), (stim3[11] ^ stim7[16]), (stim4[25] ^ stim6[11]), (stim5[16] ^ stim4[10]), (stim7[3] ^ stim5[26]), (stim7[8] ^ stim5[2]), (stim6[5] ^ stim1[17]), (stim5[8] ^ stim3[24])}; end
always @(posedge clk) f20 <= a18 < b19;
always @(posedge clk) begin
  if (stim6[24] & stim0[19]) cnt21 <= {stim5[6], stim3[10], stim5[10], stim3[19], stim6[22], stim5[13], stim0[23], stim3[21]};
  else if (stim0[14]) cnt21 <= cnt21 + 8'd3;
end
always @(posedge clk) y_q <= (^crc1) ^ (^rqa6) ^ (^rqb7) ^ (^mp10) ^ (^st11) ^ (^fo12) ^ (^rqa16) ^ (^rqb17) ^ f20 ^ (^cnt21);
assign y = y_q;
endmodule
