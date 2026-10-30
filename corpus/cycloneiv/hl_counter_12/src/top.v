module top (
  input clk,
  output y
);
reg [3:0] cnt1;
reg [31:0] stim0;
reg [15:0] cnt2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[24] & stim0[21] & stim0[5]) cnt1 <= {4{1'b0}};
  else if (stim0[9]) cnt1 <= cnt1 - 4'd1;
end
always @(posedge clk) begin
  if (stim0[8] & stim0[10]) cnt2 <= {stim0[19], stim0[29], stim0[28], stim0[31], stim0[20], stim0[13], stim0[17], stim0[0], stim0[16], stim0[7], stim0[30], stim0[15], stim0[2], stim0[4], stim0[27], stim0[18]};
  else if (stim0[26]) cnt2 <= cnt2 - 16'd5;
end
always @(posedge clk) y_q <= (^cnt1) ^ (^cnt2);
assign y = y_q;
endmodule
