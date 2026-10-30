module top (
  input clk,
  output y
);
reg [23:0] cnt1;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[20] & stim0[25] & stim0[11]) cnt1 <= {24{1'b0}};
  else if (stim0[18] & stim0[13]) cnt1 <= {stim0[9], stim0[3], stim0[1], stim0[16], stim0[2], stim0[24], stim0[23], stim0[21], stim0[12], stim0[27], stim0[28], stim0[26], stim0[22], stim0[15], stim0[6], stim0[14], stim0[8], stim0[30], stim0[31], stim0[17], stim0[0], stim0[4], stim0[10], stim0[7]};
  else if (stim0[5]) cnt1 <= stim0[19] ? cnt1 + 24'd7 : cnt1 - 24'd7;
end
always @(posedge clk) y_q <= (^cnt1);
assign y = y_q;
endmodule
