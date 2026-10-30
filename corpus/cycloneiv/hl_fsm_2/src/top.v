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
reg [3:0] st1;
reg [0:0] fo2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
 if (stim0[21] & stim0[28] & stim0[2]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[9] ? ST1_1 : ST1_4;
  ST1_1: st1 <= stim0[17] ? ST1_2 : stim0[25] ? ST1_3 : ST1_5;
  ST1_2: st1 <= stim0[6] ? ST1_3 : ST1_8;
  ST1_3: st1 <= stim0[24] ? ST1_4 : stim0[4] ? ST1_3 : ST1_9;
  ST1_4: st1 <= stim0[23] ? ST1_5 : ST1_9;
  ST1_5: st1 <= stim0[0] ? ST1_6 : stim0[8] ? ST1_6 : ST1_4;
  ST1_6: st1 <= stim0[19] ? ST1_7 : stim0[15] ? ST1_8 : ST1_4;
  ST1_7: st1 <= stim0[11] ? ST1_8 : stim0[14] ? ST1_0 : ST1_10;
  ST1_8: st1 <= stim0[26] ? ST1_9 : stim0[10] ? ST1_9 : ST1_4;
  ST1_9: st1 <= stim0[7] ? ST1_10 : stim0[13] ? ST1_3 : ST1_6;
  ST1_10: st1 <= stim0[12] ? ST1_0 : stim0[5] ? ST1_2 : ST1_7;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_3 | st1 == ST1_7 | st1 == ST1_1 | st1 == ST1_8)};
always @(posedge clk) y_q <= (^st1) ^ fo2;
assign y = y_q;
endmodule
