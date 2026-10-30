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
reg [15:0] a4, b5;
reg [30:0] stim1;
reg [29:0] stim2;
reg f6;
reg [15:0] a7, b8;
reg [28:0] stim3;
reg [27:0] stim4;
reg [16:0] s9;
reg [26:0] stim5;
reg [25:0] stim6;
reg [24:0] stim7;
wire [2:0] sel10 = {stim6[0], stim4[8], stim6[15]};
reg [7:0] mx11;
wire [63:0] mv12 = {{(stim4[0] ^ stim2[15]), (stim4[18] ^ stim3[3]), (stim3[26] ^ stim6[8]), (stim7[3] ^ stim6[10]), (stim0[5] ^ stim6[18]), (stim6[14] ^ stim3[10]), (stim6[1] ^ stim2[28]), (stim7[20] ^ stim1[6])}, {(stim2[21] ^ stim6[5]), (stim6[3] ^ stim6[6]), (stim1[12] ^ stim3[7]), (stim4[16] ^ stim2[14]), (stim1[8] ^ stim7[22]), (stim3[6] ^ stim6[21]), (stim2[24] ^ stim1[23]), (stim6[25] ^ stim1[24])}, {(stim7[24] ^ stim7[1]), (stim7[11] ^ stim7[6]), (stim7[17] ^ stim7[5]), (stim4[20] ^ stim4[9]), (stim7[7] ^ stim5[8]), (stim3[14] ^ stim2[23]), (stim4[12] ^ stim2[19]), (stim6[23] ^ stim4[15])}, {(stim7[20] ^ stim7[15]), (stim7[16] ^ stim7[13]), (stim7[4] ^ stim7[18]), (stim7[0] ^ stim7[12]), (stim7[10] ^ stim7[14]), (stim7[23] ^ stim7[8]), (stim7[2] ^ stim7[9]), (stim7[21] ^ stim7[19])}, {(stim6[17] ^ stim6[22]), (stim6[24] ^ stim6[20]), (stim6[19] ^ stim6[9]), (stim6[4] ^ stim6[16]), (stim6[13] ^ stim6[12]), (stim6[2] ^ stim6[11]), (stim6[7] ^ stim7[7]), (stim7[22] ^ stim7[3])}, {(stim5[21] ^ stim5[24]), (stim5[3] ^ stim6[23]), (stim6[5] ^ stim6[3]), (stim6[6] ^ stim6[21]), (stim6[25] ^ stim6[8]), (stim6[10] ^ stim6[18]), (stim6[14] ^ stim6[1]), (stim6[0] ^ stim6[15])}, {(stim5[2] ^ stim5[17]), (stim5[15] ^ stim5[12]), (stim5[26] ^ stim5[11]), (stim5[13] ^ stim5[9]), (stim5[23] ^ stim5[19]), (stim5[0] ^ stim5[18]), (stim5[7] ^ stim5[10]), (stim5[5] ^ stim5[20])}, {(stim4[17] ^ stim4[27]), (stim4[24] ^ stim4[1]), (stim4[5] ^ stim4[10]), (stim4[11] ^ stim4[7]), (stim5[8] ^ stim5[25]), (stim5[14] ^ stim5[4]), (stim5[6] ^ stim5[16]), (stim5[1] ^ stim5[22])}};
reg signed [8:0] ma13;
reg signed [8:0] mb14;
reg signed [17:0] mp15;
reg signed [21:0] acc16;
reg [7:0] cnt17;
reg [31:0] sr18;
reg [15:0] sr19;
reg [7:0] crc20;
function [7:0] crcf21(input [7:0] cc, input [7:0] x);
  integer i; reg [7:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[7] ^ x[7 - i]) ? ((rr << 1) ^ 8'h7) : (rr << 1);
    crcf21 = rr;
  end
endfunction
reg [15:0] cnt22;
reg [23:0] a23, b24;
reg [24:0] s25;
(* ramstyle = "M9K, no_rw_check" *) reg [7:0] ram26 [0:255];
reg [7:0] ad27;
reg [7:0] ad28;
reg [7:0] rq29;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  cnt1 <= cnt1 + 8'd1;
end
always @(posedge clk) if (stim0[21] & stim0[0] & stim0[23]) crc2 <= {16{1'b1}}; else if (stim0[6]) crc2 <= crcf3(crc2, {stim0[15], stim0[1], stim0[11], stim0[17], stim0[16], stim0[8], stim0[12], stim0[30]});
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin a4 <= {(stim0[2] ^ stim0[10]), (stim0[28] ^ stim0[29]), (stim0[24] ^ stim0[4]), (stim0[20] ^ stim0[9]), (stim0[31] ^ stim0[22]), (stim0[27] ^ stim0[26]), (stim0[3] ^ stim0[19]), (stim0[7] ^ stim0[14]), (stim0[25] ^ stim0[18]), (stim0[13] ^ stim1[12]), (stim1[8] ^ stim1[23]), (stim1[24] ^ stim1[6]), (stim1[29] ^ stim1[2]), (stim1[1] ^ stim1[22]), (stim1[10] ^ stim1[19]), (stim1[14] ^ stim1[20])}; b5 <= {(stim1[17] ^ stim1[11]), (stim1[28] ^ stim1[18]), (stim1[21] ^ stim1[3]), (stim1[4] ^ stim1[30]), (stim1[25] ^ stim1[15]), (stim1[9] ^ stim1[13]), (stim1[5] ^ stim1[16]), (stim1[27] ^ stim1[7]), (stim1[0] ^ stim1[26]), (stim2[23] ^ stim2[19]), (stim2[21] ^ stim2[14]), (stim2[7] ^ stim2[4]), (stim2[24] ^ stim2[15]), (stim2[28] ^ stim2[17]), (stim2[5] ^ stim2[8]), (stim2[20] ^ stim2[25])}; end
always @(posedge clk) f6 <= a4 != b5;
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) begin a7 <= {(stim2[26] ^ stim2[11]), (stim2[1] ^ stim2[18]), (stim2[29] ^ stim2[9]), (stim2[0] ^ stim2[22]), (stim2[13] ^ stim2[10]), (stim2[2] ^ stim2[3]), (stim2[27] ^ stim2[16]), (stim2[6] ^ stim2[12]), (stim3[14] ^ stim3[7]), (stim3[6] ^ stim3[3]), (stim3[26] ^ stim3[10]), (stim3[2] ^ stim3[15]), (stim3[12] ^ stim3[22]), (stim3[13] ^ stim3[23]), (stim3[0] ^ stim3[21]), (stim3[11] ^ stim3[28])}; b8 <= {(stim3[8] ^ stim3[18]), (stim3[20] ^ stim3[17]), (stim3[16] ^ stim3[25]), (stim3[4] ^ stim3[19]), (stim3[1] ^ stim3[9]), (stim3[24] ^ stim3[27]), (stim3[5] ^ stim4[20]), (stim4[9] ^ stim4[12]), (stim4[15] ^ stim4[16]), (stim4[0] ^ stim4[18]), (stim4[8] ^ stim4[21]), (stim4[22] ^ stim4[19]), (stim4[14] ^ stim4[13]), (stim4[2] ^ stim4[3]), (stim4[23] ^ stim4[26]), (stim4[25] ^ stim4[6])}; end
always @(posedge clk) s9 <= a7 + b8 + stim4[4];
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) stim6 <= {stim6[24:0], ~(stim6[25] ^ stim6[5] ^ stim6[1] ^ stim6[0])};
always @(posedge clk) stim7 <= {stim7[23:0], ~(stim7[24] ^ stim7[21])};
always @(posedge clk) mx11 <= mv12[sel10 * 8 +: 8];
always @(posedge clk) begin ma13 <= {(stim3[2] ^ stim7[15]), (stim7[16] ^ stim6[17]), (stim0[21] ^ stim2[17]), (stim2[5] ^ stim6[22]), (stim5[25] ^ stim2[8]), (stim2[20] ^ stim1[29]), (stim0[0] ^ stim2[25]), (stim1[2] ^ stim5[14]), (stim2[26] ^ stim3[15])}; mb14 <= {(stim5[4] ^ stim6[24]), (stim4[21] ^ stim1[1]), (stim1[22] ^ stim0[23]), (stim4[22] ^ stim3[12]), (stim0[6] ^ stim7[13]), (stim7[4] ^ stim6[20]), (stim6[19] ^ stim7[18]), (stim6[9] ^ stim6[4]), (stim0[15] ^ stim1[10])}; end
always @(posedge clk) mp15 <= ma13 * mb14;
always @(posedge clk) acc16 <= acc16 + mp15;
always @(posedge clk) begin
  cnt17 <= cnt17 - 8'd1;
end
always @(posedge clk) sr18 <= {sr18[30:0], stim0[1]};
always @(posedge clk) sr19 <= {sr19[14:0], stim2[11]};
always @(posedge clk) if (stim2[1] & stim2[18] & stim3[22]) crc20 <= {8{1'b1}}; else if (stim4[14]) crc20 <= crcf21(crc20, {stim3[13], stim0[11], stim5[6], stim1[19], stim1[14], stim4[13], stim1[20], stim3[23]});
always @(posedge clk) begin
  if (stim1[17] & stim7[0]) cnt22 <= {stim1[11], stim3[0], stim6[16], stim3[21], stim1[28], stim2[29], stim2[9], stim3[11], stim1[18], stim6[13], stim0[16], stim3[28], stim0[8], stim2[0], stim6[12], stim4[2]};
  else if (stim3[8]) cnt22 <= stim0[17] ? cnt22 + 16'd1 : cnt22 - 16'd1;
end
always @(posedge clk) begin a23 <= {(stim0[12] ^ stim5[16]), (stim3[18] ^ stim6[2]), (stim5[1] ^ stim1[21]), (stim3[20] ^ stim2[22]), (stim0[30] ^ stim6[11]), (stim2[13] ^ stim1[3]), (stim1[4] ^ stim5[22]), (stim6[7] ^ stim6[23]), (stim0[28] ^ stim1[30]), (stim4[3] ^ stim7[12]), (stim0[29] ^ stim7[10]), (stim3[17] ^ stim2[10]), (stim7[14] ^ stim1[25]), (stim3[16] ^ stim1[15]), (stim5[2] ^ stim2[2]), (stim7[23] ^ stim3[25]), (stim1[9] ^ stim4[25]), (stim1[13] ^ stim5[17]), (stim6[6] ^ stim3[4]), (stim6[21] ^ stim2[3]), (stim5[15] ^ stim3[19]), (stim2[27] ^ stim0[20]), (stim3[1] ^ stim0[9]), (stim3[9] ^ stim6[25])}; b24 <= {(stim0[31] ^ stim5[12]), (stim3[24] ^ stim4[6]), (stim4[4] ^ stim6[8]), (stim0[22] ^ stim6[10]), (stim4[17] ^ stim0[27]), (stim6[18] ^ stim3[27]), (stim7[8] ^ stim4[27]), (stim4[24] ^ stim7[2]), (stim7[9] ^ stim2[16]), (stim5[26] ^ stim0[26]), (stim7[21] ^ stim5[11]), (stim5[13] ^ stim0[3]), (stim7[19] ^ stim3[5]), (stim4[1] ^ stim6[0]), (stim1[0] ^ stim4[5]), (stim2[6] ^ stim5[9]), (stim1[26] ^ stim6[15]), (stim5[0] ^ stim4[10]), (stim3[14] ^ stim2[12]), (stim4[11] ^ stim3[7]), (stim1[12] ^ stim6[17]), (stim5[18] ^ stim0[19]), (stim5[7] ^ stim2[23]), (stim1[8] ^ stim4[7])}; end
always @(posedge clk) s25 <= a23 + 25'd2246095;
always @(posedge clk) ad27 <= ad27 + 8'd1;
always @(posedge clk) ad28 <= ad28 + 8'd1;
always @(posedge clk) begin
  if (stim5[10]) ram26[ad27] <= {stim4[20], stim4[9], stim5[5], stim3[26], stim2[19], stim2[21], stim0[7], stim3[10]};
  rq29 <= ram26[ad28];
end
always @(posedge clk) y_q <= (^cnt1) ^ (^crc2) ^ f6 ^ (^s9) ^ (^mx11) ^ (^mp15) ^ (^cnt17) ^ (^acc16) ^ (^sr18) ^ (^sr19) ^ (^crc20) ^ (^cnt22) ^ (^s25) ^ (^rq29);
assign y = y_q;
endmodule
