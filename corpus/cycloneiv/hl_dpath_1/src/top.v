module top (
  input clk,
  output y
);
reg [11:0] cnt1, lim2;
reg cmp3;
localparam [1:0] RUN = 2'd0, HOLD = 2'd1, CLR = 2'd2, WAIT = 2'd3;
reg [1:0] st4;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) lim2 <= {(stim0[18] ^ stim0[19]), (stim0[29] ^ stim0[4]), (stim0[8] ^ stim0[24]), (stim0[27] ^ stim0[30]), (stim0[28] ^ stim0[6]), (stim0[20] ^ stim0[7]), (stim0[9] ^ stim0[31]), (stim0[22] ^ stim0[23]), (stim0[26] ^ stim0[3]), (stim0[25] ^ stim0[13]), (stim0[15] ^ stim0[2]), (stim0[16] ^ stim0[1])};
always @(posedge clk) cmp3 <= cnt1 >= lim2;
always @(posedge clk) case (st4)
  RUN: st4 <= cmp3 ? HOLD : RUN;
  HOLD: st4 <= stim0[14] ? CLR : WAIT;
  CLR: st4 <= RUN;
  WAIT: st4 <= stim0[11] ? RUN : WAIT;
endcase
always @(posedge clk) if (st4 == CLR) cnt1 <= {12{1'b0}}; else if (st4 == RUN) cnt1 <= cnt1 + 12'd1;
always @(posedge clk) y_q <= (^cnt1) ^ (^st4) ^ cmp3;
assign y = y_q;
endmodule
