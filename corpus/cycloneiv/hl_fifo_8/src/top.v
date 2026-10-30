module top (
  input clk,
  output y
);
reg [31:0] stim0;
(* ramstyle = "M9K, no_rw_check" *) reg [17:0] fm1 [0:31];
reg [4:0] wp2, rp3;
reg [5:0] fc4;
reg [17:0] fq5;
wire ff6 = (fc4 == 6'd32);
wire fe7 = (fc4 == 6'd0);
wire wr8 = stim0[28] & ~ff6;
wire rd9 = stim0[11] & ~fe7;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (wr8) begin fm1[wp2] <= {stim0[22], stim0[23], stim0[12], stim0[3], stim0[25], stim0[6], stim0[16], stim0[2], stim0[0], stim0[30], stim0[15], stim0[10], stim0[5], stim0[18], stim0[26], stim0[7], stim0[20], stim0[4]}; wp2 <= wp2 + 5'd1; end
  if (rd9) begin fq5 <= fm1[rp3]; rp3 <= rp3 + 5'd1; end
  fc4 <= fc4 + {{5{1'b0}}, wr8} - {{5{1'b0}}, rd9};
end
always @(posedge clk) y_q <= (^fq5) ^ (^fc4) ^ (^wp2) ^ (^rp3);
assign y = y_q;
endmodule
