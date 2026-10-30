module top (
  input clk,
  output y
);
reg [31:0] stim0;
wire [3:0] pi1 = {(stim0[26] ^ stim0[21]), (stim0[3] ^ stim0[14]), (stim0[9] ^ stim0[22]), (stim0[15] ^ stim0[7])};
reg [3:0] pp2;
reg [3:0] pp3;
reg [3:0] pp4;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) pp2 <= ~pi1;
always @(posedge clk) pp3 <= ~pp2;
always @(posedge clk) pp4 <= pp3 ^ {pp3[2:0], pp3[3]} ^ {pp3[1:0], pp3[3:2]};
always @(posedge clk) y_q <= (^pp4);
assign y = y_q;
endmodule
