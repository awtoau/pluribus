module top (
  input clk,
  output y
);
reg [31:0] stim0;
wire [3:0] pi1 = {(stim0[12] ^ stim0[9]), (stim0[19] ^ stim0[1]), (stim0[6] ^ stim0[2]), (stim0[22] ^ stim0[29])};
reg [3:0] pp2;
reg [3:0] pp3;
reg [3:0] pp4;
reg [3:0] pp5;
reg [3:0] pp6;
wire [7:0] pi7 = {(stim0[3] ^ stim0[23]), (stim0[21] ^ stim0[30]), (stim0[14] ^ stim0[4]), (stim0[15] ^ stim0[7]), (stim0[0] ^ stim0[27]), (stim0[20] ^ stim0[28]), (stim0[16] ^ stim0[5]), (stim0[18] ^ stim0[13])};
reg [7:0] pp8;
reg [7:0] pp9;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) pp2 <= pi1 ^ {pi1[2:0], pi1[3]} ^ {pi1[1:0], pi1[3:2]};
always @(posedge clk) pp3 <= pp2 ^ {pp2[2:0], pp2[3]} ^ {pp2[1:0], pp2[3:2]};
always @(posedge clk) pp4 <= pp3 ^ {pp3[2:0], pp3[3]} ^ {pp3[1:0], pp3[3:2]};
always @(posedge clk) pp5 <= pp4 + 4'd6;
always @(posedge clk) pp6 <= ~pp5;
always @(posedge clk) pp8 <= pi7 ^ {pi7[6:0], pi7[7]} ^ {pi7[5:0], pi7[7:6]};
always @(posedge clk) pp9 <= ~pp8;
always @(posedge clk) y_q <= (^pp6) ^ (^pp9);
assign y = y_q;
endmodule
