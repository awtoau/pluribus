module top (
  input clk,
  output y
);
reg [15:0] cnt1;
reg [31:0] stim0;
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] fm2 [0:63];
reg [5:0] wp3, rp4;
reg [6:0] fc5;
reg [15:0] fq6;
wire ff7 = (fc5 == 7'd64);
wire fe8 = (fc5 == 7'd0);
wire wr9 = stim0[0] & ~ff7;
wire rd10 = stim0[25] & ~fe8;
reg [19:0] sum11;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  cnt1 <= cnt1 + 16'd1;
end
always @(posedge clk) begin
  if (wr9) begin fm2[wp3] <= {stim0[26], stim0[23], stim0[17], stim0[19], stim0[15], stim0[18], stim0[21], stim0[4], stim0[30], stim0[16], stim0[3], stim0[28], stim0[1], stim0[5], stim0[10], stim0[2]}; wp3 <= wp3 + 6'd1; end
  if (rd10) begin fq6 <= fm2[rp4]; rp4 <= rp4 + 6'd1; end
  fc5 <= fc5 + {{6{1'b0}}, wr9} - {{6{1'b0}}, rd10};
end
always @(posedge clk) sum11 <= sum11 + fq6;
always @(posedge clk) y_q <= (^cnt1) ^ (^fq6) ^ (^fc5) ^ (^wp3) ^ (^rp4) ^ (^sum11);
assign y = y_q;
endmodule
