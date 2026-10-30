module top (
  input clk,
  output y
);
reg [31:0] stim0;
reg [30:0] stim1;
wire [1:0] sel1 = {stim1[8], stim1[22]};
reg [3:0] mx2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) mx2 <= (sel1 == 2'd0) ? {(stim0[2] ^ stim0[9]), (stim0[19] ^ stim0[0]), (stim0[8] ^ stim0[20]), (stim0[31] ^ stim0[21])} : (sel1 == 2'd1) ? {(stim0[30] ^ stim0[13]), (stim0[18] ^ stim0[15]), (stim0[26] ^ stim0[10]), (stim0[23] ^ stim0[11])} : (sel1 == 2'd2) ? {(stim0[7] ^ stim0[22]), (stim0[24] ^ stim0[3]), (stim0[14] ^ stim0[16]), (stim0[25] ^ stim0[27])} : {(stim0[1] ^ stim0[5]), (stim0[6] ^ stim0[29]), (stim0[17] ^ stim0[4]), (stim0[28] ^ stim0[12])};
always @(posedge clk) y_q <= (^mx2);
assign y = y_q;
endmodule
