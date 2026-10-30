module top (
  input clk,
  output y
);
reg [3:0] rg1;
reg [31:0] stim0;
reg [15:0] rg2;
reg [30:0] stim1;
wire ar3 = stim1[26] & stim1[29] & stim1[15] & stim1[19];
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  if (stim0[28] & stim0[8]) rg1 <= {4{1'b0}};
  else if (stim0[31]) rg1 <= {(stim0[0] ^ stim0[5]), (stim0[1] ^ stim0[15]), (stim0[30] ^ stim0[2]), (stim0[27] ^ stim0[26])};
end
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk or posedge ar3) begin
  if (ar3) rg2 <= {16{1'b0}};
  else begin
    if (stim0[19] & stim0[11]) rg2 <= {16{1'b0}};
    else rg2 <= {(stim0[4] ^ stim0[17]), (stim0[14] ^ stim0[7]), (stim0[10] ^ stim0[16]), (stim0[29] ^ stim0[6]), (stim0[22] ^ stim0[23]), (stim0[24] ^ stim0[3]), (stim0[9] ^ stim0[21]), (stim0[20] ^ stim0[25]), (stim0[18] ^ stim0[13]), (stim0[12] ^ stim1[3]), (stim1[9] ^ stim1[2]), (stim1[20] ^ stim1[22]), (stim1[27] ^ stim1[18]), (stim1[8] ^ stim1[14]), (stim1[0] ^ stim1[7]), (stim1[16] ^ stim1[11])};
  end
end
always @(posedge clk) y_q <= (^rg1) ^ (^rg2);
assign y = y_q;
endmodule
