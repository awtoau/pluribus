module top (
  input clk,
  output y
);
reg [15:0] cnt1;
reg [31:0] stim0;
reg [11:0] cnt2;
reg [7:0] cnt3;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  cnt1 <= stim0[25] ? cnt1 + 16'd1 : cnt1 - 16'd1;
end
always @(posedge clk) begin
  if (stim0[11] & stim0[16] & stim0[14]) cnt2 <= {12{1'b0}};
  else if (stim0[20] & stim0[7]) cnt2 <= {stim0[3], stim0[10], stim0[18], stim0[12], stim0[28], stim0[4], stim0[13], stim0[23], stim0[1], stim0[9], stim0[30], stim0[31]};
  else if (stim0[26]) cnt2 <= stim0[19] ? cnt2 + 12'd1 : cnt2 - 12'd1;
end
always @(posedge clk) begin
  if (stim0[17]) cnt3 <= cnt3 - 8'd1;
end
always @(posedge clk) y_q <= (^cnt1) ^ (^cnt2) ^ (^cnt3);
assign y = y_q;
endmodule
