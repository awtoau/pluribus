module top (
  input clk,
  output y
);
reg [3:0] sr1;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[18] & stim0[27]) sr1 <= {stim0[21], stim0[1], stim0[11], stim0[14]}; else sr1 <= {sr1[2:0], stim0[15]};
always @(posedge clk) y_q <= (^sr1);
assign y = y_q;
endmodule
