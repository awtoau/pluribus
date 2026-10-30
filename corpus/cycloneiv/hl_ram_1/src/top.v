module top (
  input clk,
  output y
);
(* ramstyle = "M9K, no_rw_check" *) reg [7:0] ram1 [0:1023];
reg [9:0] ad2;
reg [7:0] rq3;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) ad2 <= ad2 + 10'd1;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[2]) ram1[ad2] <= {stim0[28], stim0[16], stim0[6], stim0[3], stim0[24], stim0[10], stim0[27], stim0[21]};
  rq3 <= ram1[ad2];
end
always @(posedge clk) y_q <= (^rq3);
assign y = y_q;
endmodule
