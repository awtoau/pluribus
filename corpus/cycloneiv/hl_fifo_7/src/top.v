module top (
  input clk,
  output y
);
reg [31:0] stim0;
(* ramstyle = "M9K, no_rw_check" *) reg [31:0] fm1 [0:63];
reg [5:0] wp2, rp3;
reg [6:0] fc4;
reg [31:0] fq5;
wire ff6 = (fc4 == 7'd64);
wire fe7 = (fc4 == 7'd0);
wire wr8 = stim0[31] & ~ff6;
wire rd9 = stim0[22] & ~fe7;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (wr8) begin fm1[wp2] <= {stim0[4], stim0[3], stim0[15], stim0[16], stim0[11], stim0[14], stim0[1], stim0[13], stim0[29], stim0[9], stim0[20], stim0[27], stim0[24], stim0[23], stim0[17], stim0[21], stim0[5], stim0[18], stim0[28], stim0[19], stim0[8], stim0[2], stim0[6], stim0[30], stim0[25], stim0[7], stim0[12], stim0[0], stim0[10], stim0[26], stim1[27], stim1[24]}; wp2 <= wp2 + 6'd1; end
  if (rd9) begin fq5 <= fm1[rp3]; rp3 <= rp3 + 6'd1; end
  fc4 <= fc4 + {{6{1'b0}}, wr8} - {{6{1'b0}}, rd9};
end
always @(posedge clk) y_q <= (^fq5) ^ (^fc4) ^ (^wp2) ^ (^rp3);
assign y = y_q;
endmodule
