module top (
  input clk,
  output y
);
reg [23:0] cnt1;
reg [31:0] stim0;
reg [5:0] cnt2;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[10] & stim0[26]) cnt1 <= {stim0[29], stim0[5], stim0[4], stim0[1], stim0[8], stim0[17], stim0[28], stim0[2], stim0[20], stim0[6], stim0[11], stim0[18], stim0[19], stim0[27], stim0[0], stim0[30], stim0[13], stim0[22], stim0[31], stim0[3], stim0[9], stim0[16], stim0[14], stim0[24]};
  else cnt1 <= stim0[7] ? cnt1 + 24'd1 : cnt1 - 24'd1;
end
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[21] & stim0[25]) cnt2 <= {stim0[15], stim0[23], stim1[27], stim1[2], stim1[15], stim1[29]};
  else cnt2 <= cnt2 - 6'd1;
end
always @(posedge clk) y_q <= (^cnt1) ^ (^cnt2);
assign y = y_q;
endmodule
