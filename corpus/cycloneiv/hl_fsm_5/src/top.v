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
reg [3:0] st1;
reg [0:0] fo2;
reg [30:0] stim1;
localparam [4:0] ST3_0 = 5'd0;
localparam [4:0] ST3_1 = 5'd1;
localparam [4:0] ST3_2 = 5'd2;
localparam [4:0] ST3_3 = 5'd3;
localparam [4:0] ST3_4 = 5'd4;
localparam [4:0] ST3_5 = 5'd5;
localparam [4:0] ST3_6 = 5'd6;
localparam [4:0] ST3_7 = 5'd7;
localparam [4:0] ST3_8 = 5'd8;
localparam [4:0] ST3_9 = 5'd9;
localparam [4:0] ST3_10 = 5'd10;
localparam [4:0] ST3_11 = 5'd11;
localparam [4:0] ST3_12 = 5'd12;
localparam [4:0] ST3_13 = 5'd13;
localparam [4:0] ST3_14 = 5'd14;
localparam [4:0] ST3_15 = 5'd15;
localparam [4:0] ST3_16 = 5'd16;
localparam [4:0] ST3_17 = 5'd17;
reg [4:0] st3;
reg [1:0] fo4;
reg [29:0] stim2;
localparam [6:0] ST5_0 = 7'd1;
localparam [6:0] ST5_1 = 7'd2;
localparam [6:0] ST5_2 = 7'd4;
localparam [6:0] ST5_3 = 7'd8;
localparam [6:0] ST5_4 = 7'd16;
localparam [6:0] ST5_5 = 7'd32;
localparam [6:0] ST5_6 = 7'd64;
reg [6:0] st5;
reg [2:0] fo6;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
 if (stim0[10] & stim0[16] & stim0[22]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[3] ? ST1_1 : ST1_8;
  ST1_1: st1 <= stim0[24] ? ST1_2 : stim0[6] ? ST1_5 : ST1_0;
  ST1_2: st1 <= stim0[25] ? ST1_3 : stim0[14] ? ST1_1 : ST1_5;
  ST1_3: st1 <= stim0[27] ? ST1_4 : stim0[26] ? ST1_4 : ST1_5;
  ST1_4: st1 <= stim0[7] ? ST1_5 : ST1_3;
  ST1_5: st1 <= stim0[1] ? ST1_6 : ST1_7;
  ST1_6: st1 <= stim0[17] ? ST1_7 : stim0[18] ? ST1_5 : ST1_4;
  ST1_7: st1 <= stim0[15] ? ST1_8 : ST1_3;
  ST1_8: st1 <= stim0[20] ? ST1_9 : ST1_6;
  ST1_9: st1 <= stim0[30] ? ST1_0 : ST1_3;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_0 | st1 == ST1_1)};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
 if (stim1[24] & stim1[19] & stim1[29]) st3 <= ST3_0;
 else case (st3)
  ST3_0: st3 <= stim0[5] ? ST3_1 : ST3_4;
  ST3_1: st3 <= stim0[0] ? ST3_2 : stim0[29] ? ST3_15 : ST3_4;
  ST3_2: st3 <= stim0[9] ? ST3_3 : stim0[19] ? ST3_6 : ST3_9;
  ST3_3: st3 <= stim0[13] ? ST3_4 : stim0[28] ? ST3_4 : ST3_8;
  ST3_4: st3 <= stim0[8] ? ST3_5 : stim1[4] ? ST3_10 : ST3_12;
  ST3_5: st3 <= stim1[18] ? ST3_6 : ST3_12;
  ST3_6: st3 <= stim1[9] ? ST3_7 : stim1[0] ? ST3_13 : ST3_16;
  ST3_7: st3 <= stim1[17] ? ST3_8 : stim1[11] ? ST3_9 : ST3_4;
  ST3_8: st3 <= stim1[10] ? ST3_9 : ST3_13;
  ST3_9: st3 <= stim1[12] ? ST3_10 : stim1[22] ? ST3_1 : ST3_4;
  ST3_10: st3 <= stim1[21] ? ST3_11 : stim1[6] ? ST3_0 : ST3_15;
  ST3_11: st3 <= stim1[16] ? ST3_12 : ST3_4;
  ST3_12: st3 <= stim1[27] ? ST3_13 : ST3_12;
  ST3_13: st3 <= stim1[28] ? ST3_14 : stim1[13] ? ST3_7 : ST3_9;
  ST3_14: st3 <= stim1[26] ? ST3_15 : stim1[1] ? ST3_7 : ST3_3;
  ST3_15: st3 <= stim1[3] ? ST3_16 : stim1[14] ? ST3_6 : ST3_12;
  ST3_16: st3 <= stim1[15] ? ST3_17 : ST3_15;
  ST3_17: st3 <= stim1[2] ? ST3_0 : ST3_12;
  default: st3 <= ST3_0;
 endcase
end
always @(posedge clk) fo4 <= {(st3 == ST3_6 | st3 == ST3_1 | st3 == ST3_5 | st3 == ST3_17 | st3 == ST3_4 | st3 == ST3_14), (st3 == ST3_2 | st3 == ST3_4 | st3 == ST3_7 | st3 == ST3_8 | st3 == ST3_13 | st3 == ST3_3 | st3 == ST3_10 | st3 == ST3_17 | st3 == ST3_0)};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin
 if (stim2[10] & stim2[6] & stim2[13]) st5 <= ST5_0;
 else case (st5)
  ST5_0: st5 <= stim1[8] ? ST5_1 : ST5_2;
  ST5_1: st5 <= stim2[15] ? ST5_2 : ST5_4;
  ST5_2: st5 <= stim2[0] ? ST5_3 : ST5_4;
  ST5_3: st5 <= stim2[23] ? ST5_4 : stim2[3] ? ST5_2 : ST5_4;
  ST5_4: st5 <= stim2[11] ? ST5_5 : ST5_3;
  ST5_5: st5 <= stim2[5] ? ST5_6 : ST5_4;
  ST5_6: st5 <= stim2[14] ? ST5_0 : stim2[1] ? ST5_1 : ST5_2;
  default: st5 <= ST5_0;
 endcase
end
always @(posedge clk) fo6 <= {(st5 == ST5_0), (st5 == ST5_2 | st5 == ST5_3 | st5 == ST5_6), (st5 == ST5_1 | st5 == ST5_0)};
always @(posedge clk) y_q <= (^st1) ^ fo2 ^ (^st3) ^ (^fo4) ^ (^st5) ^ (^fo6);
assign y = y_q;
endmodule
