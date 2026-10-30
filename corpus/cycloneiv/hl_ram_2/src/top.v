module top (
  input clk,
  output y
);
(* ramstyle = "M9K, no_rw_check" *) reg [7:0] ram1 [0:255];
reg [7:0] ad2;
reg [7:0] rq3;
reg [31:0] stim0;
(* ramstyle = "M9K, no_rw_check" *) reg [31:0] ram4 [0:1023];
reg [9:0] ad5;
reg [9:0] ad6;
reg [31:0] rq7;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) ad2 <= ad2 + 8'd1;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[17]) ram1[ad2] <= {stim0[9], stim0[31], stim0[13], stim0[29], stim0[4], stim0[23], stim0[2], stim0[12]};
  rq3 <= ram1[ad2];
end
always @(posedge clk) ad5 <= ad5 + 10'd1;
always @(posedge clk) ad6 <= ad6 + 10'd1;
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[14]) ram4[ad5] <= {stim0[25], stim0[5], stim0[18], stim0[27], stim0[20], stim0[22], stim0[0], stim0[10], stim0[26], stim0[21], stim0[11], stim0[28], stim0[1], stim0[19], stim0[16], stim0[7], stim0[24], stim0[8], stim0[3], stim0[30], stim0[15], stim0[6], stim1[3], stim1[7], stim1[24], stim1[21], stim1[4], stim1[23], stim1[9], stim1[28], stim1[16], stim1[20]};
  rq7 <= ram4[ad6];
end
always @(posedge clk) y_q <= (^rq3) ^ (^rq7);
assign y = y_q;
endmodule
