module top (
  input clk,
  output y
);
reg [31:0] stim0;
(* ramstyle = "M9K, no_rw_check" *) reg [7:0] fm1 [0:31];
reg [4:0] wp2, rp3;
reg [5:0] fc4;
reg [7:0] fq5;
wire ff6 = (fc4 == 6'd32);
wire fe7 = (fc4 == 6'd0);
wire wr8 = stim0[22] & ~ff6;
wire rd9 = stim0[31] & ~fe7;
(* ramstyle = "M9K, no_rw_check" *) reg [8:0] fm10 [0:255];
reg [7:0] wp11, rp12;
reg [8:0] fc13;
reg [8:0] fq14;
wire ff15 = (fc13 == 9'd256);
wire fe16 = (fc13 == 9'd0);
wire wr17 = stim0[12] & ~ff15;
wire rd18 = stim0[9] & ~fe16;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (wr8) begin fm1[wp2] <= {stim0[30], stim0[17], stim0[25], stim0[7], stim0[23], stim0[5], stim0[20], stim0[4]}; wp2 <= wp2 + 5'd1; end
  if (rd9) begin fq5 <= fm1[rp3]; rp3 <= rp3 + 5'd1; end
  fc4 <= fc4 + {{5{1'b0}}, wr8} - {{5{1'b0}}, rd9};
end
always @(posedge clk) begin
  if (wr17) begin fm10[wp11] <= {stim0[13], stim0[26], stim0[21], stim0[0], stim0[11], stim0[1], stim0[8], stim0[18], stim0[15]}; wp11 <= wp11 + 8'd1; end
  if (rd18) begin fq14 <= fm10[rp12]; rp12 <= rp12 + 8'd1; end
  fc13 <= fc13 + {{8{1'b0}}, wr17} - {{8{1'b0}}, rd18};
end
always @(posedge clk) y_q <= (^fq5) ^ (^fc4) ^ (^wp2) ^ (^rp3) ^ (^fq14) ^ (^fc13) ^ (^wp11) ^ (^rp12);
assign y = y_q;
endmodule
