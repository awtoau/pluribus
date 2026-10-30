module top (
  input clk,
  output y
);
reg [23:0] cnt1;
reg [31:0] stim0;
reg [5:0] cnt2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[31]) cnt1 <= cnt1 - 24'd7;
end
always @(posedge clk) begin
  if (stim0[20] & stim0[8] & stim0[2]) cnt2 <= {6{1'b0}};
  else if (stim0[19] & stim0[6]) cnt2 <= {stim0[11], stim0[1], stim0[26], stim0[12], stim0[0], stim0[29]};
  else if (stim0[10]) cnt2 <= stim0[21] ? cnt2 + 6'd1 : cnt2 - 6'd1;
end
always @(posedge clk) y_q <= (^cnt1) ^ (^cnt2);
assign y = y_q;
endmodule
