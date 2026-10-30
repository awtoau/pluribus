module top (
  input clk,
  output y
);
reg [11:0] cnt1;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[5] & stim0[11]) cnt1 <= {stim0[27], stim0[26], stim0[23], stim0[2], stim0[17], stim0[7], stim0[21], stim0[25], stim0[20], stim0[12], stim0[15], stim0[28]};
  else cnt1 <= cnt1 - 12'd1;
end
always @(posedge clk) y_q <= (^cnt1);
assign y = y_q;
endmodule
