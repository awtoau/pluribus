module top (
  input clk,
  output y
);
reg [7:0] a1, b2;
reg [31:0] stim0;
reg f3;
reg [30:0] stim1;
reg [29:0] stim2;
wire [3:0] sel4 = {stim2[16], stim2[24], stim2[28], stim2[14]};
reg [0:0] mx5;
reg [7:0] cnt6;
reg [7:0] crc7;
function [7:0] crcf8(input [7:0] cc, input [7:0] x);
  integer i; reg [7:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[7] ^ x[7 - i]) ? ((rr << 1) ^ 8'h7) : (rr << 1);
    crcf8 = rr;
  end
endfunction
reg [11:0] a9, b10;
reg [28:0] stim3;
reg [27:0] stim4;
reg [12:0] s11;
reg [31:0] cnt12;
reg [26:0] stim5;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin a1 <= {(stim0[13] ^ stim0[2]), (stim0[1] ^ stim0[11]), (stim0[9] ^ stim0[3]), (stim0[0] ^ stim0[7]), (stim0[19] ^ stim0[31]), (stim0[18] ^ stim0[27]), (stim0[15] ^ stim0[25]), (stim0[28] ^ stim0[20])}; b2 <= {(stim0[6] ^ stim0[10]), (stim0[23] ^ stim0[12]), (stim0[22] ^ stim0[5]), (stim0[26] ^ stim0[21]), (stim0[24] ^ stim0[17]), (stim0[14] ^ stim0[8]), (stim0[4] ^ stim0[30]), (stim0[16] ^ stim0[29])}; end
always @(posedge clk) f3 <= a1 >= b2;
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) mx5 <= (sel4 == 4'd0) ? {(stim1[1] ^ stim1[4])} : (sel4 == 4'd1) ? {(stim1[20] ^ stim1[19])} : (sel4 == 4'd2) ? {(stim1[8] ^ stim1[16])} : (sel4 == 4'd3) ? {(stim1[22] ^ stim1[28])} : (sel4 == 4'd4) ? {(stim1[17] ^ stim1[6])} : (sel4 == 4'd5) ? {(stim1[27] ^ stim1[5])} : (sel4 == 4'd6) ? {(stim1[7] ^ stim1[21])} : (sel4 == 4'd7) ? {(stim1[26] ^ stim1[2])} : (sel4 == 4'd8) ? {(stim1[3] ^ stim1[11])} : (sel4 == 4'd9) ? {(stim1[29] ^ stim1[14])} : (sel4 == 4'd10) ? {(stim1[18] ^ stim1[24])} : (sel4 == 4'd11) ? {(stim1[13] ^ stim1[23])} : (sel4 == 4'd12) ? {(stim1[25] ^ stim1[10])} : (sel4 == 4'd13) ? {(stim1[15] ^ stim1[0])} : (sel4 == 4'd14) ? {(stim1[30] ^ stim1[12])} : {(stim1[9] ^ stim2[12])};
always @(posedge clk) begin
  cnt6 <= cnt6 + 8'd1;
end
always @(posedge clk) if (stim2[10] & stim2[4] & stim2[17]) crc7 <= {8{1'b1}}; else if (stim2[22]) crc7 <= crcf8(crc7, {stim2[7], stim2[5], stim2[8], stim2[2], stim2[11], stim2[9], stim2[0], stim2[19]});
always @(posedge clk) stim3 <= {stim3[27:0], ~(stim3[28] ^ stim3[26])};
always @(posedge clk) stim4 <= {stim4[26:0], ~(stim4[27] ^ stim4[24])};
always @(posedge clk) begin a9 <= {(stim2[25] ^ stim2[1]), (stim2[29] ^ stim2[21]), (stim2[20] ^ stim2[3]), (stim2[13] ^ stim2[18]), (stim2[23] ^ stim2[26]), (stim2[15] ^ stim2[6]), (stim3[2] ^ stim3[8]), (stim3[11] ^ stim3[9]), (stim3[0] ^ stim3[13]), (stim3[23] ^ stim3[14]), (stim3[26] ^ stim3[24]), (stim3[16] ^ stim3[20])}; b10 <= {(stim3[22] ^ stim3[12]), (stim3[6] ^ stim3[21]), (stim3[28] ^ stim3[1]), (stim3[5] ^ stim3[27]), (stim3[25] ^ stim3[17]), (stim3[15] ^ stim3[10]), (stim3[18] ^ stim3[19]), (stim3[3] ^ stim3[4]), (stim3[7] ^ stim4[19]), (stim4[25] ^ stim4[8]), (stim4[14] ^ stim4[10]), (stim4[0] ^ stim4[4])}; end
always @(posedge clk) s11 <= a9 + b10 + stim4[26];
always @(posedge clk) stim5 <= {stim5[25:0], ~(stim5[26] ^ stim5[4] ^ stim5[1] ^ stim5[0])};
always @(posedge clk) begin
  if (stim4[24] & stim4[22]) cnt12 <= {stim4[18], stim4[11], stim4[1], stim4[12], stim4[5], stim4[21], stim4[13], stim4[6], stim4[3], stim4[9], stim4[23], stim4[17], stim4[20], stim4[27], stim4[7], stim4[15], stim4[2], stim5[5], stim5[8], stim5[16], stim5[9], stim5[22], stim5[24], stim5[7], stim5[13], stim5[23], stim5[14], stim5[25], stim5[1], stim5[20], stim5[12], stim5[11]};
  else if (stim5[17]) cnt12 <= stim4[16] ? cnt12 + 32'd3 : cnt12 - 32'd3;
end
always @(posedge clk) y_q <= f3 ^ mx5 ^ (^cnt6) ^ (^crc7) ^ (^s11) ^ (^cnt12);
assign y = y_q;
endmodule
