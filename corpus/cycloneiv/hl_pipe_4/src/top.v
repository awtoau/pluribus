module top (
  input clk,
  output y
);
reg [31:0] stim0;
wire [3:0] pi1 = {(stim0[25] ^ stim0[2]), (stim0[28] ^ stim0[20]), (stim0[12] ^ stim0[30]), (stim0[16] ^ stim0[31])};
reg [3:0] pp2;
reg [3:0] pp3;
reg [3:0] pp4;
reg [3:0] pp5;
reg [3:0] pp6;
reg [3:0] pp7;
wire [3:0] pi8 = {(stim0[9] ^ stim0[21]), (stim0[5] ^ stim0[3]), (stim0[27] ^ stim0[15]), (stim0[22] ^ stim0[26])};
reg [3:0] pp9;
reg [3:0] pp10;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) pp2 <= pi1 ^ {pi1[2:0], pi1[3]} ^ {pi1[1:0], pi1[3:2]};
always @(posedge clk) pp3 <= ~pp2;
always @(posedge clk) pp4 <= pp3 ^ {pp3[2:0], pp3[3]} ^ {pp3[1:0], pp3[3:2]};
always @(posedge clk) pp5 <= {pp4[2:0], pp4[3]};
always @(posedge clk) pp6 <= pp5 ^ 4'h8;
always @(posedge clk) pp7 <= pp6 ^ {pp6[2:0], pp6[3]} ^ {pp6[1:0], pp6[3:2]};
always @(posedge clk) pp9 <= pi8 ^ 4'hB;
always @(posedge clk) pp10 <= {pp9[2:0], pp9[3]};
always @(posedge clk) y_q <= (^pp7) ^ (^pp10);
assign y = y_q;
endmodule
