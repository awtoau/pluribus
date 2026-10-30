module top (
  input clk,
  output y
);
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] ram1 [0:1023];
reg [9:0] ad2;
reg [15:0] rq3;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) ad2 <= ad2 + 10'd1;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[7]) ram1[ad2] <= {stim0[1], stim0[2], stim0[19], stim0[8], stim0[28], stim0[14], stim0[9], stim0[5], stim0[3], stim0[18], stim0[13], stim0[11], stim0[20], stim0[0], stim0[10], stim0[16]};
  rq3 <= ram1[ad2];
end
always @(posedge clk) y_q <= (^rq3);
assign y = y_q;
endmodule
