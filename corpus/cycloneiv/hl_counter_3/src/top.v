module top (
  input clk,
  output y
);
reg [9:0] cnt1;
reg [31:0] stim0;
reg [11:0] cnt2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[18] & stim0[9] & stim0[28]) cnt1 <= {10{1'b0}};
  else cnt1 <= cnt1 + 10'd1;
end
always @(posedge clk) begin
  if (stim0[16] & stim0[22] & stim0[12]) cnt2 <= {12{1'b0}};
  else cnt2 <= cnt2 - 12'd1;
end
always @(posedge clk) y_q <= (^cnt1) ^ (^cnt2);
assign y = y_q;
endmodule
