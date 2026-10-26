module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, input i18, input i19, input i20, input i21, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10, output o11, output o12, output o13, output o14);
  wire n0;
  wire n1;
  reg q1;
  wire n2;
  wire n3;
  wire n4;
  wire n5;
  reg q5;
  wire [6:0] s0;
  wire n7;
  reg q7;
  wire n8;
  reg q8;
  wire n9;
  reg q9;
  wire n10;
  reg q10;
  wire n11;
  reg q11;
  wire n12;
  wire n13;
  wire [10:0] s1;
  wire n15;
  wire n16;
  wire n17;
  reg q17;
  wire n18;
  wire [9:0] s2;
  wire n20;
  reg q20;
  wire n21;
  wire n22;
  reg q22;
  wire n23;
  assign n0 = 16'hcf8a >> {i8, i2, i1, i1};
  assign n1 = 16'hd2b2 >> {i21, i1, i14, i6};
  assign n2 = 16'h2922 >> {i15, i10, i16, i7};
  assign n3 = 16'haaf8 >> {i10, i12, i18, i17};
  assign n4 = 16'he418 >> {i19, i19, i11, i8};
  assign n5 = 16'h2489 >> {i7, i1, i6, i20};
  assign s0 = {1'b0, i4, i2, i17, i11, i21, i13} - {1'b0, i14, i9, i12, i17, i16, q5};
  assign n7 = 16'h588d >> {i6, i0, q5, s0[2]};
  assign n8 = 16'hfdfc >> {s0[1], i8, s0[3], i21};
  assign n9 = 16'h07b4 >> {q5, i5, i1, i5};
  assign n10 = 16'h9bf3 >> {i17, i10, s0[5], i19};
  assign n11 = 16'hd6f2 >> {i8, q9, i19, q10};
  assign n12 = 16'h6e5e >> {q5, s0[0], s0[2], s0[0]};
  assign n13 = 16'h187f >> {i1, i13, q7, i20};
  assign s1 = {1'b0, n3, s0[2], i14, i13, n0, n2, i20, i2, s0[3], s0[0]} - {1'b0, i20, n12, n4, q7, i20, q5, s0[6], i13, n12, s0[3]};
  assign n15 = 16'hd0b3 >> {n3, s1[4], i19, i18};
  assign n16 = 16'he3dc >> {s0[4], n3, q10, n3};
  assign n17 = 16'h61e8 >> {i21, i3, n12, i2};
  assign n18 = 16'hf32a >> {i17, i21, i11, i11};
  assign s2 = {1'b0, s0[6], i5, i9, s1[2], i4, i13, n16, q10, i3} + {1'b0, i9, n16, n2, i13, s0[3], i8, s1[3], s0[4], i13};
  assign n20 = 16'h6809 >> {s1[2], q7, s2[8], s0[3]};
  assign n21 = 16'hdc56 >> {i21, q9, i9, q8};
  assign n22 = 16'hddd0 >> {s2[4], s2[4], s1[7], s2[9]};
  assign n23 = 16'hbadd >> {q17, s0[6], s0[2], i19};
  always @(posedge clk1) begin q1 <= n1; end
  always @(posedge clk1) begin if (i20) q5 <= 1'b0; else q5 <= n5; end
  always @(posedge clk1) begin q7 <= n7; end
  always @(posedge clk0) begin if (i14) q8 <= 1'b0; else if (i1) q8 <= i6; else q8 <= n8; end
  always @(posedge clk1) begin q9 <= n9; end
  always @(posedge clk0 or posedge s0[6]) begin if (s0[6]) q10 <= 1'b0; else begin q10 <= n10; end end
  always @(posedge clk0 or posedge i9) begin if (i9) q11 <= 1'b1; else begin q11 <= n11; end end
  always @(posedge clk0 or posedge n15) begin if (n15) q17 <= 1'b0; else begin if (i21) q17 <= n4; else q17 <= n17; end end
  always @(posedge clk0) begin if (i5) q20 <= 1'b0; else q20 <= n20; end
  always @(posedge clk1) begin if (q10) q22 <= 1'b0; else q22 <= n22; end
  assign o0 = ~(^{s0[0], q5, s1[7], n13});
  assign o1 = (^{s0[3], n15, s0[5], q22});
  assign o2 = (^{s1[5], s2[5], s0[6], q9});
  assign o3 = (^{n21, n16, s2[1], q7});
  assign o4 = (^{s1[8], q8, q1});
  assign o5 = (^{s2[7], s0[1], s1[10]});
  assign o6 = (^{s1[9], s0[4], s0[2]});
  assign o7 = (^{s1[6], q17, q20});
  assign o8 = (^{n18, s2[9], s1[4]});
  assign o9 = (^{n12, q10, n4});
  assign o10 = (^{n0, n2, n23});
  assign o11 = (^{s1[0], s2[3], s2[2]});
  assign o12 = (^{s2[8], n3, s1[2]});
  assign o13 = (^{s1[1], s1[3], s2[6]});
  assign o14 = (^{s2[4], q11, s2[0]});
endmodule
