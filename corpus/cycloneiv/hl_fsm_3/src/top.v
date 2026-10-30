module top (
  input clk,
  output y
);
reg [31:0] stim0;
reg [30:0] stim1;
localparam [4:0] ST1_0 = 5'd0;
localparam [4:0] ST1_1 = 5'd1;
localparam [4:0] ST1_2 = 5'd3;
localparam [4:0] ST1_3 = 5'd2;
localparam [4:0] ST1_4 = 5'd6;
localparam [4:0] ST1_5 = 5'd7;
localparam [4:0] ST1_6 = 5'd5;
localparam [4:0] ST1_7 = 5'd4;
localparam [4:0] ST1_8 = 5'd12;
localparam [4:0] ST1_9 = 5'd13;
localparam [4:0] ST1_10 = 5'd15;
localparam [4:0] ST1_11 = 5'd14;
localparam [4:0] ST1_12 = 5'd10;
localparam [4:0] ST1_13 = 5'd11;
localparam [4:0] ST1_14 = 5'd9;
localparam [4:0] ST1_15 = 5'd8;
localparam [4:0] ST1_16 = 5'd24;
reg [4:0] st1;
reg [1:0] fo2;
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
reg [3:0] st3;
reg [0:0] fo4;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
 if (stim1[3] & stim1[4] & stim1[25]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[20] ? ST1_1 : stim0[9] ? ST1_8 : ST1_12;
  ST1_1: st1 <= stim0[17] ? ST1_2 : ST1_6;
  ST1_2: st1 <= stim0[6] ? ST1_3 : ST1_10;
  ST1_3: st1 <= stim0[14] ? ST1_4 : ST1_8;
  ST1_4: st1 <= stim0[13] ? ST1_5 : stim0[16] ? ST1_6 : ST1_11;
  ST1_5: st1 <= stim0[24] ? ST1_6 : ST1_4;
  ST1_6: st1 <= stim0[7] ? ST1_7 : ST1_3;
  ST1_7: st1 <= stim0[0] ? ST1_8 : ST1_4;
  ST1_8: st1 <= stim0[23] ? ST1_9 : stim0[30] ? ST1_14 : ST1_3;
  ST1_9: st1 <= stim0[28] ? ST1_10 : stim0[5] ? ST1_3 : ST1_5;
  ST1_10: st1 <= stim0[26] ? ST1_11 : stim0[19] ? ST1_3 : ST1_13;
  ST1_11: st1 <= stim0[31] ? ST1_12 : stim0[22] ? ST1_13 : ST1_10;
  ST1_12: st1 <= stim0[10] ? ST1_13 : ST1_14;
  ST1_13: st1 <= stim0[2] ? ST1_14 : stim0[12] ? ST1_0 : ST1_1;
  ST1_14: st1 <= stim0[18] ? ST1_15 : ST1_8;
  ST1_15: st1 <= stim0[25] ? ST1_16 : ST1_5;
  ST1_16: st1 <= stim1[24] ? ST1_0 : ST1_1;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_10), (st1 == ST1_15)};
always @(posedge clk) begin
 if (stim1[20] & stim1[7] & stim1[10]) st3 <= ST3_0;
 else case (st3)
  ST3_0: st3 <= stim1[17] ? ST3_1 : ST3_8;
  ST3_1: st3 <= stim1[30] ? ST3_2 : ST3_9;
  ST3_2: st3 <= stim1[9] ? ST3_3 : ST3_1;
  ST3_3: st3 <= stim1[6] ? ST3_4 : ST3_0;
  ST3_4: st3 <= stim1[2] ? ST3_5 : ST3_1;
  ST3_5: st3 <= stim1[0] ? ST3_6 : ST3_10;
  ST3_6: st3 <= stim1[13] ? ST3_7 : ST3_2;
  ST3_7: st3 <= stim1[14] ? ST3_8 : stim1[12] ? ST3_8 : ST3_2;
  ST3_8: st3 <= stim1[19] ? ST3_9 : ST3_4;
  ST3_9: st3 <= stim1[5] ? ST3_10 : ST3_8;
  ST3_10: st3 <= stim1[23] ? ST3_0 : stim1[22] ? ST3_10 : ST3_10;
  default: st3 <= ST3_0;
 endcase
end
always @(posedge clk) fo4 <= {(st3 == ST3_10 | st3 == ST3_6)};
always @(posedge clk) y_q <= (^st1) ^ (^fo2) ^ (^st3) ^ fo4;
assign y = y_q;
endmodule
