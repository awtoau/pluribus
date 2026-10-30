module top (
  input clk,
  output y
);
reg [23:0] cnt1;
reg [31:0] stim0;
reg [11:0] cnt2;
reg [3:0] cnt3;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[20] & stim0[1] & stim0[4]) cnt1 <= {24{1'b0}};
  else if (stim0[19]) cnt1 <= cnt1 + 24'd1;
end
always @(posedge clk) begin
  if (stim0[2] & stim0[13]) cnt2 <= {stim0[31], stim0[30], stim0[24], stim0[9], stim0[0], stim0[6], stim0[5], stim0[12], stim0[17], stim0[10], stim0[22], stim0[18]};
  else cnt2 <= cnt2 + 12'd1;
end
always @(posedge clk) begin
  cnt3 <= stim0[29] ? cnt3 + 4'd1 : cnt3 - 4'd1;
end
always @(posedge clk) y_q <= (^cnt1) ^ (^cnt2) ^ (^cnt3);
assign y = y_q;
endmodule
