module top (
  input clk,
  output y
);
reg signed [8:0] ma1;
reg signed [8:0] mb2;
reg signed [17:0] mp3;
reg [31:0] stim0;
reg [30:0] stim1;
reg signed [21:0] acc4;
reg [7:0] cnt5;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin ma1 <= {(stim0[27] ^ stim0[22]), (stim0[17] ^ stim0[29]), (stim0[13] ^ stim0[31]), (stim0[28] ^ stim0[26]), (stim0[5] ^ stim0[15]), (stim0[18] ^ stim0[25]), (stim0[21] ^ stim0[11]), (stim0[7] ^ stim0[0]), (stim0[4] ^ stim0[14])}; mb2 <= {(stim0[6] ^ stim0[8]), (stim0[30] ^ stim0[1]), (stim0[2] ^ stim0[19]), (stim0[20] ^ stim0[24]), (stim0[3] ^ stim0[12]), (stim0[16] ^ stim0[10]), (stim0[9] ^ stim0[23]), (stim1[10] ^ stim1[25]), (stim1[17] ^ stim1[12])}; end
always @(posedge clk) mp3 <= ma1 * mb2;
always @(posedge clk) acc4 <= acc4 + mp3;
always @(posedge clk) begin
  cnt5 <= cnt5 - 8'd1;
end
always @(posedge clk) y_q <= (^mp3) ^ (^cnt5) ^ (^acc4);
assign y = y_q;
endmodule
