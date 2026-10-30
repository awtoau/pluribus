module top (
  input clk,
  output y
);
reg [31:0] stim0;
localparam [3:0] ST1_0 = 4'd0;
localparam [3:0] ST1_1 = 4'd1;
localparam [3:0] ST1_2 = 4'd2;
localparam [3:0] ST1_3 = 4'd3;
localparam [3:0] ST1_4 = 4'd4;
localparam [3:0] ST1_5 = 4'd5;
localparam [3:0] ST1_6 = 4'd6;
localparam [3:0] ST1_7 = 4'd7;
localparam [3:0] ST1_8 = 4'd8;
localparam [3:0] ST1_9 = 4'd9;
localparam [3:0] ST1_10 = 4'd10;
localparam [3:0] ST1_11 = 4'd11;
localparam [3:0] ST1_12 = 4'd12;
localparam [3:0] ST1_13 = 4'd13;
reg [3:0] st1;
reg [0:0] fo2;
reg [30:0] stim1;
localparam [3:0] ST3_0 = 4'd0;
localparam [3:0] ST3_1 = 4'd1;
localparam [3:0] ST3_2 = 4'd3;
localparam [3:0] ST3_3 = 4'd2;
localparam [3:0] ST3_4 = 4'd6;
localparam [3:0] ST3_5 = 4'd7;
localparam [3:0] ST3_6 = 4'd5;
localparam [3:0] ST3_7 = 4'd4;
localparam [3:0] ST3_8 = 4'd12;
localparam [3:0] ST3_9 = 4'd13;
localparam [3:0] ST3_10 = 4'd15;
localparam [3:0] ST3_11 = 4'd14;
localparam [3:0] ST3_12 = 4'd10;
reg [3:0] st3;
reg [2:0] fo4;
reg [29:0] stim2;
localparam [9:0] ST5_0 = 10'd1;
localparam [9:0] ST5_1 = 10'd2;
localparam [9:0] ST5_2 = 10'd4;
localparam [9:0] ST5_3 = 10'd8;
localparam [9:0] ST5_4 = 10'd16;
localparam [9:0] ST5_5 = 10'd32;
localparam [9:0] ST5_6 = 10'd64;
localparam [9:0] ST5_7 = 10'd128;
localparam [9:0] ST5_8 = 10'd256;
localparam [9:0] ST5_9 = 10'd512;
reg [9:0] st5;
reg [0:0] fo6;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
 if (stim0[25] & stim0[14] & stim0[31]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[8] ? ST1_1 : stim0[28] ? ST1_3 : ST1_13;
  ST1_1: st1 <= stim0[22] ? ST1_2 : stim0[17] ? ST1_10 : ST1_5;
  ST1_2: st1 <= stim0[6] ? ST1_3 : stim0[24] ? ST1_13 : ST1_12;
  ST1_3: st1 <= stim0[26] ? ST1_4 : stim0[20] ? ST1_0 : ST1_9;
  ST1_4: st1 <= stim0[2] ? ST1_5 : stim0[10] ? ST1_5 : ST1_13;
  ST1_5: st1 <= stim0[1] ? ST1_6 : stim0[7] ? ST1_8 : ST1_4;
  ST1_6: st1 <= stim0[3] ? ST1_7 : ST1_3;
  ST1_7: st1 <= stim0[29] ? ST1_8 : stim0[5] ? ST1_10 : ST1_0;
  ST1_8: st1 <= stim0[19] ? ST1_9 : ST1_10;
  ST1_9: st1 <= stim0[4] ? ST1_10 : stim0[13] ? ST1_9 : ST1_6;
  ST1_10: st1 <= stim0[12] ? ST1_11 : ST1_12;
  ST1_11: st1 <= stim0[27] ? ST1_12 : ST1_1;
  ST1_12: st1 <= stim0[21] ? ST1_13 : stim0[30] ? ST1_10 : ST1_4;
  ST1_13: st1 <= stim0[23] ? ST1_0 : ST1_13;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_3 | st1 == ST1_6 | st1 == ST1_10 | st1 == ST1_11 | st1 == ST1_13)};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
 if (stim1[16] & stim1[4] & stim1[11]) st3 <= ST3_0;
 else case (st3)
  ST3_0: st3 <= stim0[0] ? ST3_1 : ST3_4;
  ST3_1: st3 <= stim1[10] ? ST3_2 : ST3_8;
  ST3_2: st3 <= stim1[21] ? ST3_3 : ST3_2;
  ST3_3: st3 <= stim1[17] ? ST3_4 : ST3_1;
  ST3_4: st3 <= stim1[15] ? ST3_5 : stim1[23] ? ST3_8 : ST3_1;
  ST3_5: st3 <= stim1[2] ? ST3_6 : ST3_0;
  ST3_6: st3 <= stim1[9] ? ST3_7 : stim1[14] ? ST3_6 : ST3_5;
  ST3_7: st3 <= stim1[27] ? ST3_8 : ST3_2;
  ST3_8: st3 <= stim1[8] ? ST3_9 : stim1[29] ? ST3_4 : ST3_9;
  ST3_9: st3 <= stim1[13] ? ST3_10 : ST3_9;
  ST3_10: st3 <= stim1[5] ? ST3_11 : ST3_10;
  ST3_11: st3 <= stim1[18] ? ST3_12 : stim1[0] ? ST3_10 : ST3_10;
  ST3_12: st3 <= stim1[30] ? ST3_0 : ST3_9;
  default: st3 <= ST3_0;
 endcase
end
always @(posedge clk) fo4 <= {(st3 == ST3_9 | st3 == ST3_11 | st3 == ST3_1 | st3 == ST3_4 | st3 == ST3_7), (st3 == ST3_7 | st3 == ST3_12 | st3 == ST3_10 | st3 == ST3_4 | st3 == ST3_6), (st3 == ST3_8)};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin
 if (stim2[15] & stim2[5] & stim2[22]) st5 <= ST5_0;
 else case (st5)
  ST5_0: st5 <= stim1[22] ? ST5_1 : stim1[26] ? ST5_2 : ST5_3;
  ST5_1: st5 <= stim1[7] ? ST5_2 : stim2[23] ? ST5_9 : ST5_0;
  ST5_2: st5 <= stim2[14] ? ST5_3 : stim2[21] ? ST5_6 : ST5_6;
  ST5_3: st5 <= stim2[18] ? ST5_4 : ST5_0;
  ST5_4: st5 <= stim2[3] ? ST5_5 : stim2[25] ? ST5_7 : ST5_8;
  ST5_5: st5 <= stim2[16] ? ST5_6 : ST5_2;
  ST5_6: st5 <= stim2[4] ? ST5_7 : ST5_6;
  ST5_7: st5 <= stim2[20] ? ST5_8 : stim2[12] ? ST5_5 : ST5_6;
  ST5_8: st5 <= stim2[13] ? ST5_9 : ST5_4;
  ST5_9: st5 <= stim2[7] ? ST5_0 : ST5_5;
  default: st5 <= ST5_0;
 endcase
end
always @(posedge clk) fo6 <= {(st5 == ST5_7 | st5 == ST5_6 | st5 == ST5_3)};
always @(posedge clk) y_q <= (^st1) ^ fo2 ^ (^st3) ^ (^fo4) ^ (^st5) ^ fo6;
assign y = y_q;
endmodule
