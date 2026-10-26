module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9);
  wire n0;
  wire [5:0] s0;
  wire [7:0] s1;
  wire [10:0] s2;
  wire n4;
  wire [8:0] s3;
  wire [7:0] s4;
  wire n7;
  reg q7;
  wire n8;
  wire n9;
  reg q9;
  wire n10;
  wire n11;
  reg q11;
  wire n12;
  wire n13;
  reg q13;
  wire n14;
  wire n15;
  wire [6:0] s5;
  wire n17;
  reg q17;
  wire n18;
  wire n19;
  wire n20;
  wire [10:0] s6;
  wire n22;
  wire n23;
  wire [12:0] s7;
  wire n25;
  wire n26;
  reg q26;
  wire n27;
  wire [4:0] s8;
  wire [9:0] s9;
  wire n30;
  reg q30;
  wire n31;
  wire n32;
  reg q32;
  wire n33;
  wire [8:0] s10;
  wire n35;
  wire n36;
  reg q36;
  wire n37;
  reg q37;
  wire n38;
  wire n39;
  wire n40;
  wire n41;
  reg q41;
  wire n42;
  wire [7:0] s11;
  wire [5:0] s12;
  wire [11:0] s13;
  wire n46;
  assign n0 = 16'hb603 >> {i9, i6, i0, i4};
  assign s0 = {1'b0, i4, i0, i4, i5, n0} + {1'b0, i7, i8, i6, i8, i4};
  assign s1 = {1'b0, i5, s0[1], i7, s0[2], s0[4], n0, i3} + {1'b0, i0, i5, s0[0], i2, i8, s0[2], i3};
  assign s2 = {1'b0, i5, s0[5], s1[1], i8, i9, i6, s1[5], s1[2], s1[5], i1} + {1'b0, i2, s1[6], s0[2], i4, s0[4], i0, i0, i2, s1[3], s1[3]};
  assign n4 = 16'h769b >> {s0[2], s2[0], s1[4], s0[0]};
  assign s3 = {1'b0, i9, n4, i4, i1, s2[4], s1[6], s1[7], s2[10]} + {1'b0, s1[5], s2[1], s2[0], s1[7], s1[2], s1[7], s2[6], s1[5]};
  assign s4 = {1'b0, s2[3], s1[3], s1[5], i7, s1[6], s2[10], i8} + {1'b0, i8, s2[2], s3[1], s1[6], i0, s0[3], s1[5]};
  assign n7 = 16'hd89c >> {i2, s1[7], s3[3], s4[7]};
  assign n8 = 16'h9008 >> {s0[0], s4[7], s4[7], i1};
  assign n9 = 16'h7ff0 >> {s1[1], s4[1], i5, s1[2]};
  assign n10 = 16'h8c53 >> {s4[1], s2[9], s4[0], s3[7]};
  assign n11 = 16'hf4ad >> {n0, s4[1], s3[8], s3[2]};
  assign n12 = 16'h0eac >> {s1[0], s0[5], i8, s2[10]};
  assign n13 = 16'h421c >> {s1[1], s3[4], s3[7], s0[4]};
  assign n14 = 16'h7019 >> {i5, i4, s0[4], i1};
  assign n15 = 16'h552b >> {s2[9], s3[5], i8, s2[10]};
  assign s5 = {1'b0, s3[2], q7, s3[6], s2[1], s2[4], s2[9]} - {1'b0, n8, s3[0], s3[4], s4[2], i4, i7};
  assign n17 = 16'hda00 >> {s2[0], s2[6], s0[1], s5[0]};
  assign n18 = 16'h4fba >> {s1[0], s0[5], s3[8], s5[3]};
  assign n19 = 16'h7b2c >> {s1[0], q9, s5[5], n10};
  assign n20 = 16'ha8a6 >> {s5[5], s2[7], s1[7], s3[1]};
  assign s6 = {1'b0, n8, n4, s2[0], s2[8], s0[4], s2[1], s2[4], s5[0], s3[7], s0[3]} - {1'b0, s2[9], s0[1], s1[5], i1, s3[4], i4, s2[8], i6, s1[0], s2[0]};
  assign n22 = 16'h9612 >> {s5[5], s3[8], s3[5], s6[8]};
  assign n23 = 16'hb236 >> {n10, s4[4], s0[1], s6[9]};
  assign s7 = {1'b0, s6[2], s4[1], s2[4], s3[6], s2[4], s1[0], s4[2], s4[1], s1[4], n12, s2[2], s2[0]} + {1'b0, q11, s3[7], i9, q11, n12, n19, s3[8], s1[2], n18, s6[8], s3[1], n19};
  assign n25 = 16'h8c0d >> {n23, s6[10], q11, q7};
  assign n26 = 16'h5e75 >> {s7[9], s7[6], s6[9], s6[1]};
  assign n27 = 16'h85e9 >> {s3[6], s6[9], s2[9], s5[4]};
  assign s8 = {1'b0, s3[5], s6[0], i4, s6[8]} + {1'b0, s3[6], s3[4], s7[11], s3[3]};
  assign s9 = {1'b0, s7[3], i7, q26, s2[10], s5[0], s8[2], n22, q26, s3[0]} + {1'b0, i5, s4[6], q26, s2[0], s4[5], n22, s2[6], n18, s2[3]};
  assign n30 = 16'h1111 >> {s8[0], s9[2], s7[1], q13};
  assign n31 = 16'h479f >> {s9[8], q26, i9, s5[5]};
  assign n32 = 16'h1ba4 >> {n18, s7[3], s8[0], s6[8]};
  assign n33 = 16'h1b6d >> {s7[11], s6[3], s8[1], s7[4]};
  assign s10 = {1'b0, i1, s0[1], s1[3], s5[2], s7[1], s4[2], q30, s0[4]} - {1'b0, q13, s6[3], q7, s1[5], s0[3], s4[7], s5[6], n10};
  assign n35 = 16'hb9ab >> {s9[1], s1[3], s8[3], n20};
  assign n36 = 16'h80e8 >> {s7[9], s2[3], s9[8], s9[8]};
  assign n37 = 16'he9c2 >> {s10[0], s10[5], s10[4], s7[2]};
  assign n38 = 16'h7dce >> {s6[3], n23, s9[5], s9[9]};
  assign n39 = 16'h63ec >> {s4[3], s9[1], s7[10], n38};
  assign n40 = 16'hc063 >> {s6[5], n38, s7[9], s5[2]};
  assign n41 = 16'hf329 >> {s7[4], s10[2], n38, s8[3]};
  assign n42 = 16'h254d >> {s6[9], s6[9], s6[7], s7[5]};
  assign s11 = {1'b0, s7[6], s9[2], s7[12], s10[2], s3[6], s1[3], s7[7]} - {1'b0, s6[8], n0, n42, n0, s1[1], s10[1], s4[7]};
  assign s12 = {1'b0, s0[3], s10[3], s2[5], s1[7], s7[5]} - {1'b0, s2[1], s10[4], n31, s10[2], s6[0]};
  assign s13 = {1'b0, s6[8], s11[1], n12, n10, s8[0], s4[1], s11[5], s3[8], s2[7], s0[5], s10[0]} - {1'b0, s1[7], s8[1], q26, s1[4], s0[2], s7[10], q9, s6[2], s10[5], s9[0], s8[0]};
  assign n46 = 16'h0f39 >> {q41, s11[5], s10[7], s10[2]};
  always @(posedge clk0) begin if (s4[2]) begin q7 <= n7; end end
  always @(posedge clk0 or posedge s2[8]) begin if (s2[8]) q9 <= 1'b0; else begin if (s2[3]) begin if (i7) q9 <= s4[5]; else q9 <= n9; end end end
  always @(posedge clk0) begin q11 <= n11; end
  always @(posedge clk1) begin if (s3[1]) q13 <= i3; else q13 <= n13; end
  always @(posedge clk1 or posedge s5[3]) begin if (s5[3]) q17 <= 1'b1; else begin if (n8) q17 <= s1[1]; else q17 <= n17; end end
  always @(posedge clk1) begin if (i0) q26 <= s6[3]; else q26 <= n26; end
  always @(posedge clk0) begin q30 <= n30; end
  always @(posedge clk0) begin if (s3[8]) begin q32 <= n32; end end
  always @(posedge clk0 or posedge s9[9]) begin if (s9[9]) q36 <= 1'b0; else begin if (s7[8]) q36 <= s8[2]; else q36 <= n36; end end
  always @(posedge clk0) begin if (q36) q37 <= 1'b0; else if (s10[5]) q37 <= n18; else q37 <= n37; end
  always @(posedge clk1) begin if (s8[3]) q41 <= s2[9]; else q41 <= n41; end
  assign o0 = (^{n10, s2[6], n19, s3[8], s12[3], s3[4], s10[0], s1[4], s4[2], s6[6], s9[2], n35, s12[4], q13, s6[7], s9[7]});
  assign o1 = (^{s2[3], n42, s4[5], s9[3], q36, s0[3], n4, s7[5], s4[0], s1[7], s6[1], n31, s5[5], s9[9], q11, s3[3]});
  assign o2 = (^{s0[5], s11[6], s7[11], s10[4], q9, s6[10], s13[5], s9[4], s2[2], s5[1], s7[3], q26, s8[4], s13[7], s1[3], s1[1]});
  assign o3 = (^{s11[3], s10[6], s2[0], s3[2], q32, s0[1], s2[7], n8, s11[2], s4[7], s11[5], s7[12], n12, n20, s11[7], n14});
  assign o4 = (^{s13[6], s10[1], s8[2], s4[6], s7[9], s2[1], s10[2], s7[10], s6[0], s10[7], s9[8], s10[5], s8[1], s11[1], s2[10], s13[8]});
  assign o5 = (^{n23, q7, s13[1], s11[4], s13[4], s3[7], n39, s12[0], n38, s4[4], s6[4], s7[6], n15, s7[7], s2[4], n27});
  assign o6 = (^{q37, s2[9], s8[0], s3[6], s11[0], n46, s1[5], s6[9], s2[5], s1[6], s12[2], n33, s5[0], s13[9], s3[0]});
  assign o7 = (^{s13[10], s8[3], s13[0], s4[1], n0, s9[6], s7[2], s7[4], s9[1], s0[4], n40, n22, s13[2], s7[8], s3[1]});
  assign o8 = (^{q17, s9[5], q30, s5[2], s12[5], s0[2], n18, s6[2], s7[1], s5[4], s10[8], n25, s13[3], s5[3], s1[0]});
  assign o9 = (^{s6[5], s9[0], s7[0], s4[3], s6[8], s2[8], s12[1], s0[0], s6[3], q41, s3[5], s13[11], s10[3], s5[6], s1[2]});
endmodule
