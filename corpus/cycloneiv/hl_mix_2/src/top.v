module top (
  input clk,
  output y
);
reg [5:0] sr1;
reg hit2;
localparam [1:0] A = 2'd0, B = 2'd1, C = 2'd2;
reg [1:0] sd3;
reg [31:0] stim0;
reg [23:0] cnt4;
reg [3:0] sr5;
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] ram6 [0:255];
reg [7:0] ad7;
reg [7:0] ad8;
reg [15:0] rq9;
reg [30:0] stim1;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) sr1 <= {sr1[4:0], stim0[14]};
always @(posedge clk) hit2 <= (sr1 == 6'd61);
always @(posedge clk) case (sd3)
  A: sd3 <= hit2 ? B : A;
  B: sd3 <= hit2 ? C : A;
  C: sd3 <= stim0[10] ? A : C;
  default: sd3 <= A;
endcase
always @(posedge clk) begin
  if (stim0[16] & stim0[15]) cnt4 <= {stim0[23], stim0[7], stim0[21], stim0[5], stim0[19], stim0[22], stim0[25], stim0[2], stim0[31], stim0[29], stim0[24], stim0[9], stim0[20], stim0[28], stim0[6], stim0[18], stim0[3], stim0[1], stim0[30], stim0[17], stim0[11], stim0[13], stim0[27], stim0[8]};
  else cnt4 <= cnt4 + 24'd5;
end
always @(posedge clk) sr5 <= {sr5[2:0], stim0[4]};
always @(posedge clk) ad7 <= ad7 + 8'd1;
always @(posedge clk) ad8 <= ad8 + 8'd1;
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) begin
  if (stim0[12]) ram6[ad7] <= {stim0[26], stim1[0], stim1[4], stim1[3], stim1[23], stim1[17], stim1[13], stim1[21], stim1[25], stim1[1], stim1[9], stim1[10], stim1[20], stim1[18], stim1[22], stim1[11]};
  rq9 <= ram6[ad8];
end
always @(posedge clk) y_q <= (^sr1) ^ hit2 ^ (^sd3) ^ (^cnt4) ^ (^sr5) ^ (^rq9);
assign y = y_q;
endmodule
