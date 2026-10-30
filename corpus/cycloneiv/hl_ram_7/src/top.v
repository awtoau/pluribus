module top (
  input clk,
  output y
);
(* ramstyle = "M9K, no_rw_check" *) reg [31:0] ram1 [0:1023];
reg [9:0] ad2;
reg [9:0] ad3;
reg [31:0] rqa4, rqb5;
reg [31:0] stim0;
reg [30:0] stim1;
reg [29:0] stim2;
(* ramstyle = "M9K, no_rw_check" *) reg [17:0] ram6 [0:1023];
reg [9:0] ad7;
reg [17:0] rq8;
reg y_q;
always @(posedge clk) ad2 <= ad2 + 10'd1;
always @(posedge clk) ad3 <= ad3 + 10'd1;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[24]) ram1[ad2] <= {stim0[12], stim0[22], stim0[9], stim0[4], stim0[20], stim0[5], stim0[7], stim0[29], stim0[18], stim0[2], stim0[16], stim0[23], stim0[11], stim0[26], stim0[19], stim0[8], stim0[27], stim0[0], stim0[21], stim0[17], stim0[1], stim0[14], stim0[13], stim0[28], stim0[30], stim0[6], stim0[10], stim0[25], stim0[15], stim0[3], stim0[31], stim1[26]};
  rqa4 <= ram1[ad2];
end
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin
  if (stim1[5]) ram1[ad3] <= {stim1[11], stim1[30], stim1[24], stim1[3], stim1[7], stim1[18], stim1[22], stim1[9], stim1[29], stim1[4], stim1[8], stim1[15], stim1[19], stim1[28], stim1[0], stim1[1], stim1[6], stim1[2], stim1[27], stim1[12], stim1[10], stim1[20], stim1[21], stim1[14], stim1[17], stim1[23], stim1[16], stim1[25], stim1[13], stim2[4], stim2[20], stim2[29]};
  rqb5 <= ram1[ad3];
end
always @(posedge clk) ad7 <= ad7 + 10'd1;
always @(posedge clk) begin
  if (stim2[17]) ram6[ad7] <= {stim2[14], stim2[26], stim2[24], stim2[11], stim2[13], stim2[1], stim2[8], stim2[27], stim2[12], stim2[7], stim2[10], stim2[6], stim2[16], stim2[22], stim2[28], stim2[2], stim2[18], stim2[23]};
  rq8 <= ram6[ad7];
end
always @(posedge clk) y_q <= (^rqa4) ^ (^rqb5) ^ (^rq8);
assign y = y_q;
endmodule
