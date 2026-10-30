module top (
  input clk,
  output y
);
reg [7:0] a1, b2;
reg [31:0] stim0;
reg [7:0] c4;
reg [30:0] stim1;
reg [9:0] s3;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin a1 <= {(stim0[30] ^ stim0[6]), (stim0[10] ^ stim0[8]), (stim0[4] ^ stim0[27]), (stim0[14] ^ stim0[1]), (stim0[23] ^ stim0[22]), (stim0[15] ^ stim0[29]), (stim0[3] ^ stim0[0]), (stim0[12] ^ stim0[7])}; b2 <= {(stim0[28] ^ stim0[19]), (stim0[5] ^ stim0[18]), (stim0[16] ^ stim0[21]), (stim0[17] ^ stim0[25]), (stim0[9] ^ stim0[13]), (stim0[2] ^ stim0[20]), (stim0[31] ^ stim0[26]), (stim0[24] ^ stim0[11])}; end
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) c4 <= {(stim1[17] ^ stim1[25]), (stim1[28] ^ stim1[2]), (stim1[10] ^ stim1[26]), (stim1[3] ^ stim1[12]), (stim1[27] ^ stim1[8]), (stim1[30] ^ stim1[9]), (stim1[4] ^ stim1[6]), (stim1[29] ^ stim1[23])};
always @(posedge clk) s3 <= a1 + b2 + c4;
always @(posedge clk) y_q <= (^s3);
assign y = y_q;
endmodule
