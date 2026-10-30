module top (
  input clk,
  output y
);
reg [31:0] dc1;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) dc1 <= 32'd1 << {stim0[30], stim0[19], stim0[5], stim0[9], stim0[16]};
always @(posedge clk) y_q <= (^dc1);
assign y = y_q;
endmodule
