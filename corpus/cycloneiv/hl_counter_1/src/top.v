module top (
  input clk,
  output y
);
reg [19:0] cnt1;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) begin
  cnt1 <= cnt1 - 20'd1;
end
always @(posedge clk) y_q <= (^cnt1);
assign y = y_q;
endmodule
