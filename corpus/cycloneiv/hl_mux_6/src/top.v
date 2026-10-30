module top (
  input clk,
  output y
);
reg [31:0] stim0;
wire [1:0] sel1 = {stim0[4], stim0[5]};
reg [0:0] mx2;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) case (sel1)
  2'd0: mx2 <= {(stim0[8] ^ stim0[18])};
  2'd1: mx2 <= {(stim0[21] ^ stim0[20])};
  2'd2: mx2 <= {(stim0[28] ^ stim0[6])};
  2'd3: mx2 <= {(stim0[26] ^ stim0[9])};
  default: mx2 <= {1{1'b0}};
endcase
always @(posedge clk) y_q <= mx2;
assign y = y_q;
endmodule
