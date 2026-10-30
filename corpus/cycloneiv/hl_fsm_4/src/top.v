module top (
  input clk,
  output y
);
reg [31:0] stim0;
reg [30:0] stim1;
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
localparam [3:0] ST1_14 = 4'd14;
localparam [3:0] ST1_15 = 4'd15;
reg [3:0] st1;
reg [1:0] fo2;
reg [29:0] stim2;
localparam [4:0] ST3_0 = 5'd0;
localparam [4:0] ST3_1 = 5'd1;
localparam [4:0] ST3_2 = 5'd3;
localparam [4:0] ST3_3 = 5'd2;
localparam [4:0] ST3_4 = 5'd6;
localparam [4:0] ST3_5 = 5'd7;
localparam [4:0] ST3_6 = 5'd5;
localparam [4:0] ST3_7 = 5'd4;
localparam [4:0] ST3_8 = 5'd12;
localparam [4:0] ST3_9 = 5'd13;
localparam [4:0] ST3_10 = 5'd15;
localparam [4:0] ST3_11 = 5'd14;
localparam [4:0] ST3_12 = 5'd10;
localparam [4:0] ST3_13 = 5'd11;
localparam [4:0] ST3_14 = 5'd9;
localparam [4:0] ST3_15 = 5'd8;
localparam [4:0] ST3_16 = 5'd24;
localparam [4:0] ST3_17 = 5'd25;
localparam [4:0] ST3_18 = 5'd27;
localparam [4:0] ST3_19 = 5'd26;
localparam [4:0] ST3_20 = 5'd30;
localparam [4:0] ST3_21 = 5'd31;
localparam [4:0] ST3_22 = 5'd29;
localparam [4:0] ST3_23 = 5'd28;
reg [4:0] st3;
reg [1:0] fo4;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
 if (stim1[27] & stim1[16] & stim1[7]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[12] ? ST1_1 : ST1_7;
  ST1_1: st1 <= stim0[4] ? ST1_2 : ST1_10;
  ST1_2: st1 <= stim0[15] ? ST1_3 : ST1_14;
  ST1_3: st1 <= stim0[27] ? ST1_4 : ST1_0;
  ST1_4: st1 <= stim0[29] ? ST1_5 : ST1_6;
  ST1_5: st1 <= stim0[25] ? ST1_6 : ST1_11;
  ST1_6: st1 <= stim0[1] ? ST1_7 : ST1_0;
  ST1_7: st1 <= stim0[20] ? ST1_8 : ST1_8;
  ST1_8: st1 <= stim0[9] ? ST1_9 : stim0[22] ? ST1_5 : ST1_1;
  ST1_9: st1 <= stim0[23] ? ST1_10 : stim0[16] ? ST1_14 : ST1_5;
  ST1_10: st1 <= stim0[14] ? ST1_11 : ST1_2;
  ST1_11: st1 <= stim0[28] ? ST1_12 : stim0[13] ? ST1_0 : ST1_4;
  ST1_12: st1 <= stim0[18] ? ST1_13 : stim0[8] ? ST1_3 : ST1_7;
  ST1_13: st1 <= stim0[31] ? ST1_14 : ST1_4;
  ST1_14: st1 <= stim0[11] ? ST1_15 : stim0[5] ? ST1_4 : ST1_15;
  ST1_15: st1 <= stim0[24] ? ST1_0 : ST1_9;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_10 | st1 == ST1_14 | st1 == ST1_2 | st1 == ST1_11 | st1 == ST1_15 | st1 == ST1_5 | st1 == ST1_6 | st1 == ST1_8), (st1 == ST1_3 | st1 == ST1_1 | st1 == ST1_15 | st1 == ST1_0)};
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin
 if (stim2[2] & stim2[0] & stim2[13]) st3 <= ST3_0;
 else case (st3)
  ST3_0: st3 <= stim1[12] ? ST3_1 : stim1[19] ? ST3_19 : ST3_16;
  ST3_1: st3 <= stim1[26] ? ST3_2 : ST3_2;
  ST3_2: st3 <= stim1[22] ? ST3_3 : ST3_3;
  ST3_3: st3 <= stim1[20] ? ST3_4 : stim1[11] ? ST3_10 : ST3_21;
  ST3_4: st3 <= stim1[9] ? ST3_5 : stim1[3] ? ST3_19 : ST3_19;
  ST3_5: st3 <= stim1[14] ? ST3_6 : ST3_17;
  ST3_6: st3 <= stim1[18] ? ST3_7 : stim1[17] ? ST3_21 : ST3_19;
  ST3_7: st3 <= stim1[25] ? ST3_8 : stim1[0] ? ST3_22 : ST3_4;
  ST3_8: st3 <= stim1[8] ? ST3_9 : ST3_10;
  ST3_9: st3 <= stim1[4] ? ST3_10 : ST3_8;
  ST3_10: st3 <= stim1[10] ? ST3_11 : ST3_0;
  ST3_11: st3 <= stim1[30] ? ST3_12 : stim1[24] ? ST3_11 : ST3_18;
  ST3_12: st3 <= stim1[6] ? ST3_13 : stim1[21] ? ST3_2 : ST3_8;
  ST3_13: st3 <= stim1[28] ? ST3_14 : ST3_15;
  ST3_14: st3 <= stim2[17] ? ST3_15 : ST3_15;
  ST3_15: st3 <= stim2[15] ? ST3_16 : stim2[19] ? ST3_1 : ST3_16;
  ST3_16: st3 <= stim2[7] ? ST3_17 : stim2[23] ? ST3_16 : ST3_16;
  ST3_17: st3 <= stim2[1] ? ST3_18 : ST3_10;
  ST3_18: st3 <= stim2[22] ? ST3_19 : stim2[12] ? ST3_13 : ST3_8;
  ST3_19: st3 <= stim2[20] ? ST3_20 : ST3_23;
  ST3_20: st3 <= stim2[26] ? ST3_21 : ST3_5;
  ST3_21: st3 <= stim2[24] ? ST3_22 : ST3_14;
  ST3_22: st3 <= stim2[10] ? ST3_23 : stim2[4] ? ST3_22 : ST3_7;
  ST3_23: st3 <= stim2[5] ? ST3_0 : ST3_13;
  default: st3 <= ST3_0;
 endcase
end
always @(posedge clk) fo4 <= {(st3 == ST3_23 | st3 == ST3_17 | st3 == ST3_7 | st3 == ST3_2), (st3 == ST3_17 | st3 == ST3_14 | st3 == ST3_19 | st3 == ST3_6 | st3 == ST3_3 | st3 == ST3_11 | st3 == ST3_13 | st3 == ST3_8 | st3 == ST3_9 | st3 == ST3_22)};
always @(posedge clk) y_q <= (^st1) ^ (^fo2) ^ (^st3) ^ (^fo4);
assign y = y_q;
endmodule
