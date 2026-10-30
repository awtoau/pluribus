module top (
  input clk,
  output y
);
reg [8:0] lf1;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) lf1 <= {lf1[7:0], ~(lf1[8] ^ lf1[4] ^ stim0[26])};
always @(posedge clk) y_q <= (^lf1);
assign y = y_q;
endmodule
