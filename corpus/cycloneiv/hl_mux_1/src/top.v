module top (
  input clk,
  output y
);
reg [31:0] stim0;
wire [2:0] sel1 = {stim0[23], stim0[27], stim0[31]};
reg [0:0] mx2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) mx2 <= (sel1 == 3'd0) ? {(stim0[0] ^ stim0[29])} : (sel1 == 3'd1) ? {(stim0[21] ^ stim0[1])} : (sel1 == 3'd2) ? {(stim0[24] ^ stim0[10])} : (sel1 == 3'd3) ? {(stim0[9] ^ stim0[30])} : (sel1 == 3'd4) ? {(stim0[13] ^ stim0[14])} : (sel1 == 3'd5) ? {(stim0[28] ^ stim0[11])} : (sel1 == 3'd6) ? {(stim0[8] ^ stim0[20])} : {(stim0[26] ^ stim0[22])};
always @(posedge clk) y_q <= mx2;
assign y = y_q;
endmodule
