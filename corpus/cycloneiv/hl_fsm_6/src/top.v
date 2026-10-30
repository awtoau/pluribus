module top (
  input clk,
  output y
);
reg [31:0] stim0;
localparam [2:0] ST1_0 = 3'd0;
localparam [2:0] ST1_1 = 3'd1;
localparam [2:0] ST1_2 = 3'd2;
localparam [2:0] ST1_3 = 3'd3;
localparam [2:0] ST1_4 = 3'd4;
reg [2:0] st1;
reg [0:0] fo2;
reg [30:0] stim1;
localparam [3:0] ST3_0 = 4'd0;
localparam [3:0] ST3_1 = 4'd1;
localparam [3:0] ST3_2 = 4'd2;
localparam [3:0] ST3_3 = 4'd3;
localparam [3:0] ST3_4 = 4'd4;
localparam [3:0] ST3_5 = 4'd5;
localparam [3:0] ST3_6 = 4'd6;
localparam [3:0] ST3_7 = 4'd7;
localparam [3:0] ST3_8 = 4'd8;
reg [3:0] st3;
reg [2:0] fo4;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
 if (stim0[19] & stim0[8] & stim0[3]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[27] ? ST1_1 : stim0[4] ? ST1_0 : ST1_0;
  ST1_1: st1 <= stim0[1] ? ST1_2 : ST1_1;
  ST1_2: st1 <= stim0[11] ? ST1_3 : ST1_1;
  ST1_3: st1 <= stim0[31] ? ST1_4 : ST1_4;
  ST1_4: st1 <= stim0[29] ? ST1_0 : stim0[9] ? ST1_1 : ST1_2;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_4)};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
 if (stim0[16] & stim1[8] & stim1[26]) st3 <= ST3_0;
 else case (st3)
  ST3_0: st3 <= stim0[21] ? ST3_1 : stim0[2] ? ST3_4 : ST3_0;
  ST3_1: st3 <= stim0[7] ? ST3_2 : ST3_3;
  ST3_2: st3 <= stim0[18] ? ST3_3 : ST3_8;
  ST3_3: st3 <= stim0[30] ? ST3_4 : stim0[25] ? ST3_5 : ST3_6;
  ST3_4: st3 <= stim0[12] ? ST3_5 : stim0[10] ? ST3_6 : ST3_3;
  ST3_5: st3 <= stim0[5] ? ST3_6 : ST3_2;
  ST3_6: st3 <= stim0[13] ? ST3_7 : ST3_3;
  ST3_7: st3 <= stim0[20] ? ST3_8 : stim0[26] ? ST3_3 : ST3_6;
  ST3_8: st3 <= stim0[6] ? ST3_0 : ST3_2;
  default: st3 <= ST3_0;
 endcase
end
always @(posedge clk) fo4 <= {(st3 == ST3_0 | st3 == ST3_8 | st3 == ST3_1 | st3 == ST3_5), (st3 == ST3_4 | st3 == ST3_6 | st3 == ST3_2 | st3 == ST3_7), (st3 == ST3_2)};
always @(posedge clk) y_q <= (^st1) ^ fo2 ^ (^st3) ^ (^fo4);
assign y = y_q;
endmodule
