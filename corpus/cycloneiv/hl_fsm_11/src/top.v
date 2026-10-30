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
localparam [4:0] ST1_17 = 5'd25;
localparam [4:0] ST1_18 = 5'd27;
localparam [4:0] ST1_19 = 5'd26;
reg [4:0] st1;
reg [1:0] fo2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
 if (stim1[26] & stim1[11] & stim1[21]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[8] ? ST1_1 : ST1_18;
  ST1_1: st1 <= stim0[6] ? ST1_2 : stim0[0] ? ST1_18 : ST1_12;
  ST1_2: st1 <= stim0[9] ? ST1_3 : stim0[4] ? ST1_13 : ST1_14;
  ST1_3: st1 <= stim0[14] ? ST1_4 : stim0[19] ? ST1_17 : ST1_11;
  ST1_4: st1 <= stim0[5] ? ST1_5 : stim0[29] ? ST1_5 : ST1_12;
  ST1_5: st1 <= stim0[25] ? ST1_6 : ST1_14;
  ST1_6: st1 <= stim0[3] ? ST1_7 : ST1_14;
  ST1_7: st1 <= stim0[23] ? ST1_8 : stim0[11] ? ST1_19 : ST1_0;
  ST1_8: st1 <= stim0[1] ? ST1_9 : ST1_14;
  ST1_9: st1 <= stim0[21] ? ST1_10 : ST1_14;
  ST1_10: st1 <= stim0[31] ? ST1_11 : stim0[30] ? ST1_8 : ST1_0;
  ST1_11: st1 <= stim0[12] ? ST1_12 : stim0[18] ? ST1_0 : ST1_0;
  ST1_12: st1 <= stim0[15] ? ST1_13 : stim0[10] ? ST1_17 : ST1_5;
  ST1_13: st1 <= stim0[7] ? ST1_14 : ST1_0;
  ST1_14: st1 <= stim0[26] ? ST1_15 : ST1_17;
  ST1_15: st1 <= stim0[28] ? ST1_16 : ST1_11;
  ST1_16: st1 <= stim1[10] ? ST1_17 : ST1_9;
  ST1_17: st1 <= stim1[6] ? ST1_18 : stim1[30] ? ST1_19 : ST1_12;
  ST1_18: st1 <= stim1[5] ? ST1_19 : ST1_13;
  ST1_19: st1 <= stim1[20] ? ST1_0 : stim1[13] ? ST1_15 : ST1_5;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_2 | st1 == ST1_6 | st1 == ST1_1 | st1 == ST1_3 | st1 == ST1_0), (st1 == ST1_2 | st1 == ST1_5 | st1 == ST1_4 | st1 == ST1_8 | st1 == ST1_7 | st1 == ST1_17 | st1 == ST1_14 | st1 == ST1_19 | st1 == ST1_1)};
always @(posedge clk) y_q <= (^st1) ^ (^fo2);
assign y = y_q;
endmodule
