module top (
  input clk,
  output y
);
reg [3:0] sr1;
reg hit2;
localparam [1:0] A = 2'd0, B = 2'd1, C = 2'd2;
reg [1:0] sd3;
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) sr1 <= {sr1[2:0], stim0[3]};
always @(posedge clk) hit2 <= (sr1 == 4'd11);
always @(posedge clk) case (sd3)
  A: sd3 <= hit2 ? B : A;
  B: sd3 <= hit2 ? C : A;
  C: sd3 <= stim0[10] ? A : C;
  default: sd3 <= A;
endcase
always @(posedge clk) y_q <= (^sr1) ^ hit2 ^ (^sd3);
assign y = y_q;
endmodule
