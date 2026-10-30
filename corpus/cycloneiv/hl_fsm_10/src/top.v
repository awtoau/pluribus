module top (
  input clk,
  output y
);
reg [31:0] stim0;
localparam [1:0] ST1_0 = 2'd0;
localparam [1:0] ST1_1 = 2'd1;
localparam [1:0] ST1_2 = 2'd2;
localparam [1:0] ST1_3 = 2'd3;
reg [1:0] st1;
reg [1:0] fo2;
localparam [7:0] ST3_0 = 8'd1;
localparam [7:0] ST3_1 = 8'd2;
localparam [7:0] ST3_2 = 8'd4;
localparam [7:0] ST3_3 = 8'd8;
localparam [7:0] ST3_4 = 8'd16;
localparam [7:0] ST3_5 = 8'd32;
localparam [7:0] ST3_6 = 8'd64;
localparam [7:0] ST3_7 = 8'd128;
reg [7:0] st3;
reg [2:0] fo4;
reg [30:0] stim1;
localparam [3:0] ST5_0 = 4'd0;
localparam [3:0] ST5_1 = 4'd1;
localparam [3:0] ST5_2 = 4'd3;
localparam [3:0] ST5_3 = 4'd2;
localparam [3:0] ST5_4 = 4'd6;
localparam [3:0] ST5_5 = 4'd7;
localparam [3:0] ST5_6 = 4'd5;
localparam [3:0] ST5_7 = 4'd4;
localparam [3:0] ST5_8 = 4'd12;
localparam [3:0] ST5_9 = 4'd13;
localparam [3:0] ST5_10 = 4'd15;
localparam [3:0] ST5_11 = 4'd14;
localparam [3:0] ST5_12 = 4'd10;
localparam [3:0] ST5_13 = 4'd11;
reg [3:0] st5;
reg [0:0] fo6;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
 if (stim0[21] & stim0[6] & stim0[25]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[5] ? ST1_1 : stim0[2] ? ST1_1 : ST1_2;
  ST1_1: st1 <= stim0[9] ? ST1_2 : ST1_3;
  ST1_2: st1 <= stim0[24] ? ST1_3 : stim0[22] ? ST1_2 : ST1_1;
  ST1_3: st1 <= stim0[20] ? ST1_0 : ST1_1;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_1), (st1 == ST1_3)};
always @(posedge clk) begin
 if (stim0[3] & stim0[26] & stim0[28]) st3 <= ST3_0;
 else case (st3)
  ST3_0: st3 <= stim0[31] ? ST3_1 : ST3_1;
  ST3_1: st3 <= stim0[10] ? ST3_2 : stim0[23] ? ST3_6 : ST3_5;
  ST3_2: st3 <= stim0[17] ? ST3_3 : ST3_4;
  ST3_3: st3 <= stim0[27] ? ST3_4 : ST3_5;
  ST3_4: st3 <= stim0[16] ? ST3_5 : stim0[1] ? ST3_7 : ST3_6;
  ST3_5: st3 <= stim0[13] ? ST3_6 : stim0[4] ? ST3_1 : ST3_0;
  ST3_6: st3 <= stim0[19] ? ST3_7 : stim0[15] ? ST3_5 : ST3_0;
  ST3_7: st3 <= stim0[11] ? ST3_0 : ST3_4;
  default: st3 <= ST3_0;
 endcase
end
always @(posedge clk) fo4 <= {(st3 == ST3_5 | st3 == ST3_6 | st3 == ST3_4 | st3 == ST3_3), (st3 == ST3_6 | st3 == ST3_3 | st3 == ST3_4), (st3 == ST3_2)};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
 if (stim1[4] & stim1[27] & stim1[1]) st5 <= ST5_0;
 else case (st5)
  ST5_0: st5 <= stim0[8] ? ST5_1 : stim0[12] ? ST5_2 : ST5_1;
  ST5_1: st5 <= stim1[8] ? ST5_2 : stim1[10] ? ST5_10 : ST5_3;
  ST5_2: st5 <= stim1[22] ? ST5_3 : ST5_4;
  ST5_3: st5 <= stim1[21] ? ST5_4 : stim1[9] ? ST5_10 : ST5_8;
  ST5_4: st5 <= stim1[7] ? ST5_5 : ST5_3;
  ST5_5: st5 <= stim1[3] ? ST5_6 : ST5_0;
  ST5_6: st5 <= stim1[12] ? ST5_7 : stim1[26] ? ST5_6 : ST5_12;
  ST5_7: st5 <= stim1[16] ? ST5_8 : ST5_13;
  ST5_8: st5 <= stim1[20] ? ST5_9 : ST5_1;
  ST5_9: st5 <= stim1[29] ? ST5_10 : stim1[5] ? ST5_2 : ST5_5;
  ST5_10: st5 <= stim1[11] ? ST5_11 : ST5_8;
  ST5_11: st5 <= stim1[19] ? ST5_12 : stim1[23] ? ST5_10 : ST5_5;
  ST5_12: st5 <= stim1[6] ? ST5_13 : stim1[24] ? ST5_10 : ST5_10;
  ST5_13: st5 <= stim1[28] ? ST5_0 : stim1[13] ? ST5_8 : ST5_1;
  default: st5 <= ST5_0;
 endcase
end
always @(posedge clk) fo6 <= {(st5 == ST5_7 | st5 == ST5_4 | st5 == ST5_10)};
always @(posedge clk) y_q <= (^st1) ^ (^fo2) ^ (^st3) ^ (^fo4) ^ (^st5) ^ fo6;
assign y = y_q;
endmodule
