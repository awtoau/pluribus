module top (
  input clk,
  output y
);
reg [5:0] sr1;
reg hit2;
localparam [1:0] A = 2'd0, B = 2'd1, C = 2'd2;
reg [1:0] sd3;
reg [31:0] stim0;
reg [15:0] cnt4, lim5;
reg cmp6;
localparam [1:0] RUN = 2'd0, HOLD = 2'd1, CLR = 2'd2, WAIT = 2'd3;
reg [1:0] st7;
reg [30:0] stim1;
(* ramstyle = "M9K, no_rw_check" *) reg [15:0] fm8 [0:127];
reg [6:0] wp9, rp10;
reg [7:0] fc11;
reg [15:0] fq12;
wire ff13 = (fc11 == 8'd128);
wire fe14 = (fc11 == 8'd0);
wire wr15 = stim1[17] & ~ff13;
wire rd16 = stim1[29] & ~fe14;
reg [29:0] stim2;
localparam [2:0] ST17_0 = 3'd0;
localparam [2:0] ST17_1 = 3'd1;
localparam [2:0] ST17_2 = 3'd3;
localparam [2:0] ST17_3 = 3'd2;
localparam [2:0] ST17_4 = 3'd6;
reg [2:0] st17;
reg [2:0] fo18;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) sr1 <= {sr1[4:0], stim0[2]};
always @(posedge clk) hit2 <= (sr1 == 6'd47);
always @(posedge clk) case (sd3)
  A: sd3 <= hit2 ? B : A;
  B: sd3 <= hit2 ? C : A;
  C: sd3 <= stim0[21] ? A : C;
  default: sd3 <= A;
endcase
always @(posedge clk) stim1 <= {stim1[29:0], ~(stim1[30] ^ stim1[27])};
always @(posedge clk) lim5 <= {(stim0[31] ^ stim0[30]), (stim0[17] ^ stim0[6]), (stim0[4] ^ stim0[5]), (stim0[0] ^ stim0[11]), (stim0[25] ^ stim0[13]), (stim0[22] ^ stim0[28]), (stim0[9] ^ stim0[16]), (stim0[8] ^ stim0[29]), (stim0[19] ^ stim0[3]), (stim0[18] ^ stim0[24]), (stim0[23] ^ stim0[7]), (stim0[15] ^ stim0[26]), (stim0[14] ^ stim0[10]), (stim0[12] ^ stim0[27]), (stim0[1] ^ stim0[20]), (stim1[0] ^ stim1[18])};
always @(posedge clk) cmp6 <= cnt4 >= lim5;
always @(posedge clk) case (st7)
  RUN: st7 <= cmp6 ? HOLD : RUN;
  HOLD: st7 <= stim1[26] ? CLR : WAIT;
  CLR: st7 <= RUN;
  WAIT: st7 <= stim1[25] ? RUN : WAIT;
endcase
always @(posedge clk) if (st7 == CLR) cnt4 <= {16{1'b0}}; else if (st7 == RUN) cnt4 <= cnt4 + 16'd1;
always @(posedge clk) begin
  if (wr15) begin fm8[wp9] <= {stim1[23], stim1[19], stim1[15], stim1[28], stim1[7], stim1[8], stim1[12], stim1[14], stim1[21], stim1[27], stim1[11], stim1[24], stim1[5], stim1[22], stim1[13], stim1[1]}; wp9 <= wp9 + 7'd1; end
  if (rd16) begin fq12 <= fm8[rp10]; rp10 <= rp10 + 7'd1; end
  fc11 <= fc11 + {{7{1'b0}}, wr15} - {{7{1'b0}}, rd16};
end
always @(posedge clk) stim2 <= {stim2[28:0], ~(stim2[29] ^ stim2[5] ^ stim2[3] ^ stim2[0])};
always @(posedge clk) begin
 if (stim2[7] & stim2[21] & stim2[25]) st17 <= ST17_0;
 else case (st17)
  ST17_0: st17 <= stim1[30] ? ST17_1 : stim1[4] ? ST17_0 : ST17_1;
  ST17_1: st17 <= stim1[10] ? ST17_2 : ST17_3;
  ST17_2: st17 <= stim1[20] ? ST17_3 : ST17_4;
  ST17_3: st17 <= stim1[9] ? ST17_4 : ST17_2;
  ST17_4: st17 <= stim1[16] ? ST17_0 : stim2[19] ? ST17_0 : ST17_0;
  default: st17 <= ST17_0;
 endcase
end
always @(posedge clk) fo18 <= {(st17 == ST17_1), (st17 == ST17_4), (st17 == ST17_2)};
always @(posedge clk) y_q <= (^sr1) ^ hit2 ^ (^sd3) ^ (^cnt4) ^ (^st7) ^ cmp6 ^ (^fq12) ^ (^fc11) ^ (^wp9) ^ (^rp10) ^ (^st17) ^ (^fo18);
assign y = y_q;
endmodule
