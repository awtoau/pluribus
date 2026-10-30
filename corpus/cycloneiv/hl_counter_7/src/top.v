module top (
  input clk,
  output y
);
reg [3:0] cnt1;
reg [31:0] stim0;
reg [7:0] cnt2;
reg [31:0] cnt3;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[20] & stim0[15]) cnt1 <= {stim0[16], stim0[22], stim0[0], stim0[11]};
  else if (stim0[6]) cnt1 <= cnt1 + 4'd1;
end
always @(posedge clk) begin
  if (stim0[24]) cnt2 <= cnt2 + 8'd1;
end
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[3] & stim0[26]) cnt3 <= {stim0[18], stim0[14], stim0[27], stim0[13], stim0[4], stim0[28], stim0[30], stim0[29], stim0[1], stim0[5], stim0[7], stim0[8], stim0[9], stim0[12], stim0[23], stim0[2], stim0[17], stim0[31], stim0[19], stim1[11], stim1[18], stim1[10], stim1[28], stim1[6], stim1[22], stim1[21], stim1[25], stim1[8], stim1[15], stim1[9], stim1[30], stim1[12]};
  else if (stim1[5]) cnt3 <= cnt3 - 32'd1;
end
always @(posedge clk) y_q <= (^cnt1) ^ (^cnt2) ^ (^cnt3);
assign y = y_q;
endmodule
