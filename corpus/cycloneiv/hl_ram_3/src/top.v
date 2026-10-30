module top (
  input clk,
  output y
);
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] ram1 [0:127];
reg [6:0] ad2;
reg [15:0] rq3;
reg [31:0] stim0;
(* ramstyle = "M9K, no_rw_check" *) reg [17:0] ram4 [0:1023];
reg [9:0] ad5;
reg [17:0] rq6;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) ad2 <= ad2 + 7'd1;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[17]) ram1[ad2] <= {stim0[20], stim0[22], stim0[27], stim0[7], stim0[10], stim0[24], stim0[5], stim0[18], stim0[31], stim0[1], stim0[15], stim0[2], stim0[0], stim0[8], stim0[11], stim0[4]};
  rq3 <= ram1[ad2];
end
always @(posedge clk) ad5 <= ad5 + 10'd1;
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[3]) ram4[ad5] <= {stim0[29], stim0[26], stim0[25], stim0[19], stim0[13], stim0[16], stim0[14], stim0[21], stim0[28], stim0[12], stim0[23], stim0[6], stim0[9], stim0[30], stim1[25], stim1[2], stim1[8], stim1[28]};
  rq6 <= ram4[ad5];
end
always @(posedge clk) y_q <= (^rq3) ^ (^rq6);
assign y = y_q;
endmodule
