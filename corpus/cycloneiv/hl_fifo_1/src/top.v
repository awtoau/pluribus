module top (
  input clk,
  output y
);
reg [31:0] stim0;
(* ramstyle = "M9K, no_rw_check" *) reg [31:0] fm1 [0:511];
reg [8:0] wp2, rp3;
reg [9:0] fc4;
reg [31:0] fq5;
wire ff6 = (fc4 == 10'd512);
wire fe7 = (fc4 == 10'd0);
wire wr8 = stim0[26] & ~ff6;
wire rd9 = stim0[30] & ~fe7;
reg [30:0] stim1;
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] fm10 [0:255];
reg [7:0] wp11, rp12;
reg [8:0] fc13;
reg [15:0] fq14;
wire ff15 = (fc13 == 9'd256);
wire fe16 = (fc13 == 9'd0);
wire wr17 = stim1[3] & ~ff15;
wire rd18 = stim1[25] & ~fe16;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (wr8) begin fm1[wp2] <= {stim0[10], stim0[6], stim0[5], stim0[25], stim0[7], stim0[9], stim0[28], stim0[19], stim0[13], stim0[12], stim0[11], stim0[14], stim0[24], stim0[1], stim0[15], stim0[22], stim0[0], stim0[8], stim0[17], stim0[4], stim0[3], stim0[21], stim0[23], stim0[16], stim0[27], stim0[20], stim0[2], stim0[29], stim0[31], stim0[18], stim1[2], stim1[16]}; wp2 <= wp2 + 9'd1; end
  if (rd9) begin fq5 <= fm1[rp3]; rp3 <= rp3 + 9'd1; end
  fc4 <= fc4 + {{9{1'b0}}, wr8} - {{9{1'b0}}, rd9};
end
always @(posedge clk) begin
  if (wr17) begin fm10[wp11] <= {stim1[9], stim1[30], stim1[24], stim1[26], stim1[14], stim1[5], stim1[29], stim1[12], stim1[13], stim1[21], stim1[20], stim1[11], stim1[0], stim1[15], stim1[17], stim1[10]}; wp11 <= wp11 + 8'd1; end
  if (rd18) begin fq14 <= fm10[rp12]; rp12 <= rp12 + 8'd1; end
  fc13 <= fc13 + {{8{1'b0}}, wr17} - {{8{1'b0}}, rd18};
end
always @(posedge clk) y_q <= (^fq5) ^ (^fc4) ^ (^wp2) ^ (^rp3) ^ (^fq14) ^ (^fc13) ^ (^wp11) ^ (^rp12);
assign y = y_q;
endmodule
