module top (
  input clk,
  output y
);
reg [31:0] stim0;
localparam [6:0] ST1_0 = 7'd1;
localparam [6:0] ST1_1 = 7'd2;
localparam [6:0] ST1_2 = 7'd4;
localparam [6:0] ST1_3 = 7'd8;
localparam [6:0] ST1_4 = 7'd16;
localparam [6:0] ST1_5 = 7'd32;
localparam [6:0] ST1_6 = 7'd64;
reg [6:0] st1;
reg [1:0] fo2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
 if (stim0[15] & stim0[31] & stim0[28]) st1 <= ST1_0;
 else case (st1)
  ST1_0: st1 <= stim0[4] ? ST1_1 : stim0[9] ? ST1_4 : ST1_2;
  ST1_1: st1 <= stim0[3] ? ST1_2 : stim0[6] ? ST1_0 : ST1_6;
  ST1_2: st1 <= stim0[13] ? ST1_3 : stim0[8] ? ST1_4 : ST1_2;
  ST1_3: st1 <= stim0[26] ? ST1_4 : ST1_2;
  ST1_4: st1 <= stim0[11] ? ST1_5 : ST1_0;
  ST1_5: st1 <= stim0[24] ? ST1_6 : ST1_2;
  ST1_6: st1 <= stim0[2] ? ST1_0 : stim0[22] ? ST1_1 : ST1_3;
  default: st1 <= ST1_0;
 endcase
end
always @(posedge clk) fo2 <= {(st1 == ST1_3 | st1 == ST1_5 | st1 == ST1_1), (st1 == ST1_6 | st1 == ST1_0)};
always @(posedge clk) y_q <= (^st1) ^ (^fo2);
assign y = y_q;
endmodule
