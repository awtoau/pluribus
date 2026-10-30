module top (
  input clk,
  output y
);
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] ram1 [0:511];
reg [8:0] ad2;
reg [8:0] ad3;
reg [15:0] rqa4, rqb5;
reg [31:0] stim0;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) ad2 <= ad2 + 9'd1;
always @(posedge clk) ad3 <= ad3 + 9'd1;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[15]) ram1[ad2] <= {stim0[5], stim0[9], stim0[16], stim0[23], stim0[7], stim0[2], stim0[27], stim0[12], stim0[17], stim0[22], stim0[24], stim0[0], stim0[4], stim0[8], stim0[31], stim0[13]};
  rqa4 <= ram1[ad2];
end
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[18]) ram1[ad3] <= {stim0[6], stim0[25], stim0[3], stim0[21], stim0[26], stim0[11], stim0[29], stim0[30], stim0[14], stim0[10], stim0[1], stim0[20], stim0[19], stim0[28], stim1[6], stim1[3]};
  rqb5 <= ram1[ad3];
end
always @(posedge clk) y_q <= (^rqa4) ^ (^rqb5);
assign y = y_q;
endmodule
