module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, input i18, input i19, input i20, input i21, input i22, output o0, output o1, output o2, output o3, output o4, output o5);
  wire n0;
  wire n1;
  wire n2;
  wire n3;
  wire n4;
  wire n5;
  wire n6;
  wire n7;
  reg q7;
  wire n8;
  wire n9;
  reg q9;
  wire n10;
  wire n11;
  wire n12;
  wire n13;
  wire n14;
  reg q14;
  wire n15;
  reg q15;
  wire n16;
  wire n17;
  wire n18;
  wire n19;
  reg q19;
  wire n20;
  reg q20;
  wire n21;
  wire [8:0] s0;
  wire n23;
  reg q23;
  wire n24;
  wire n25;
  wire n26;
  reg q26;
  wire n27;
  wire n28;
  wire n29;
  wire n30;
  wire n31;
  wire n32;
  reg q32;
  wire n33;
  wire n34;
  wire n35;
  wire n36;
  wire n37;
  reg q37;
  wire n38;
  wire n39;
  reg q39;
  wire n40;
  wire n41;
  wire n42;
  reg q42;
  wire n43;
  wire [3:0] s1;
  wire n45;
  reg q45;
  wire n46;
  wire n47;
  wire n48;
  wire n49;
  wire [4:0] s2;
  wire [12:0] s3;
  wire n52;
  reg q52;
  wire [12:0] s4;
  wire [10:0] s5;
  wire n55;
  assign n0 = 16'hf8a7 >> {i18, i4, i11, i0};
  assign n1 = 16'h5f54 >> {i20, i4, i6, i22};
  assign n2 = 16'ha0c3 >> {i6, i22, i17, i7};
  assign n3 = 16'hc7c5 >> {n2, i20, i9, i5};
  assign n4 = 16'h40e1 >> {n0, i20, i19, i1};
  assign n5 = 16'h626a >> {i9, i15, i4, i12};
  assign n6 = 16'h48df >> {i22, i21, i12, i7};
  assign n7 = 16'hb417 >> {i12, i3, i16, i1};
  assign n8 = 16'h822f >> {i18, n3, i3, i9};
  assign n9 = 16'hb948 >> {i9, n6, i16, i12};
  assign n10 = 16'ha85d >> {n6, i3, q9, n0};
  assign n11 = 16'hb1a4 >> {i11, i16, i5, i3};
  assign n12 = 16'h9385 >> {i4, n2, i19, i13};
  assign n13 = 16'h1dd5 >> {i18, i20, i21, n8};
  assign n14 = 16'hd263 >> {n3, i18, n4, n11};
  assign n15 = 16'he271 >> {n3, n3, i2, i7};
  assign n16 = 16'h039d >> {i18, i14, i16, i13};
  assign n17 = 16'hde34 >> {q7, i11, i22, n6};
  assign n18 = 16'h86d0 >> {i20, i4, q14, n4};
  assign n19 = 16'h5c87 >> {n5, i8, n0, i6};
  assign n20 = 16'h1e3d >> {n0, q15, n2, q15};
  assign n21 = 16'h94b4 >> {i5, i14, q7, i17};
  assign s0 = {1'b0, i3, i9, n6, n12, n4, i7, i14, n1} - {1'b0, n12, i12, q7, n17, n12, q7, n13, i22};
  assign n23 = 16'h47b7 >> {n12, s0[6], i19, i11};
  assign n24 = 16'h5969 >> {s0[4], i2, q7, s0[1]};
  assign n25 = 16'ha58e >> {i2, i2, s0[1], q14};
  assign n26 = 16'hfbdc >> {n4, i7, i13, s0[3]};
  assign n27 = 16'h3771 >> {i2, n13, q15, s0[0]};
  assign n28 = 16'hd639 >> {n21, i12, i19, s0[4]};
  assign n29 = 16'ha3c7 >> {n10, q23, n28, i11};
  assign n30 = 16'h5c0b >> {n27, n16, i19, i6};
  assign n31 = 16'h878d >> {i15, i4, n16, i10};
  assign n32 = 16'h9f59 >> {n5, i8, s0[2], n16};
  assign n33 = 16'h2f02 >> {i9, n27, s0[2], s0[5]};
  assign n34 = 16'h1330 >> {q9, s0[0], i5, n21};
  assign n35 = 16'hd4e4 >> {s0[6], n12, s0[6], i9};
  assign n36 = 16'h7750 >> {n3, i15, n18, s0[1]};
  assign n37 = 16'h90cc >> {n4, s0[7], q15, i8};
  assign n38 = 16'hef75 >> {n25, n16, q15, n13};
  assign n39 = 16'h1a9b >> {q37, n18, s0[8], n17};
  assign n40 = 16'h2088 >> {i16, n17, n34, i11};
  assign n41 = 16'haf9d >> {i17, i20, q15, n40};
  assign n42 = 16'h1023 >> {i19, n18, n18, s0[0]};
  assign n43 = 16'h06e1 >> {n27, i15, n6, n27};
  assign s1 = {1'b0, n8, i0, q9} - {1'b0, n40, s0[8], n17};
  assign n45 = 16'hf5a1 >> {q9, n10, n3, n18};
  assign n46 = 16'haafc >> {n1, n16, n1, n0};
  assign n47 = 16'hed73 >> {n40, q42, s0[6], q39};
  assign n48 = 16'hfc3b >> {q42, n10, s0[5], n24};
  assign n49 = 16'h9851 >> {n28, n27, n11, n18};
  assign s2 = {1'b0, i20, n10, i5, i12} - {1'b0, i10, q23, n47, n1};
  assign s3 = {1'b0, i8, n34, n47, i2, i13, s2[2], n48, q19, n48, q14, s0[8], s0[2]} - {1'b0, s0[4], n41, n33, s2[4], s0[0], n13, i18, s2[2], n30, n35, q39, n49};
  assign n52 = 16'h94e7 >> {n33, q45, s3[6], n34};
  assign s4 = {1'b0, q37, i19, i10, n47, n1, i16, s3[10], s2[2], i3, n36, s3[0], n10} - {1'b0, i17, i6, q9, s3[8], s3[2], s2[4], s3[8], n25, i15, s3[10], i10, s3[6]};
  assign s5 = {1'b0, i20, n5, n49, s3[3], i17, i7, i11, s2[3], n5, q19} - {1'b0, q15, n24, s3[12], i9, s3[8], n41, n17, s0[3], i12, s3[2]};
  assign n55 = 16'hbda8 >> {s5[7], s3[7], q9, s0[6]};
  always @(posedge clk1) begin if (i19) begin if (i14) q7 <= 1'b0; else if (i19) q7 <= i0; else q7 <= n7; end end
  always @(posedge clk0) begin if (n6) q9 <= i9; else q9 <= n9; end
  always @(posedge clk0) begin q14 <= n14; end
  always @(posedge clk1) begin q15 <= n15; end
  always @(posedge clk1 or posedge n18) begin if (n18) q19 <= 1'b1; else begin q19 <= n19; end end
  always @(posedge clk0 or posedge i9) begin if (i9) q20 <= 1'b0; else begin if (n2) begin if (i2) q20 <= n10; else q20 <= n20; end end end
  always @(posedge clk0 or posedge i18) begin if (i18) q23 <= 1'b0; else begin q23 <= n23; end end
  always @(posedge clk1) begin q26 <= n26; end
  always @(negedge clk0) begin if (i14) q32 <= 1'b0; else q32 <= n32; end
  always @(posedge clk0) begin if (n13) q37 <= 1'b0; else q37 <= n37; end
  always @(posedge clk1) begin if (i1) begin if (i18) q39 <= 1'b0; else q39 <= n39; end end
  always @(posedge clk1) begin if (n13) q42 <= 1'b0; else q42 <= n42; end
  always @(posedge clk1) begin q45 <= n45; end
  always @(posedge clk0 or posedge s3[2]) begin if (s3[2]) q52 <= 1'b1; else begin q52 <= n52; end end
  assign o0 = ~(^{s1[2], s1[1], q39, n41, s3[10], s1[3], n49, s4[10], s5[9], s3[8], s3[11], n29, s2[2], n55, s5[7], n33, n47, s4[7]});
  assign o1 = (^{s3[9], s0[6], s0[0], s4[9], s5[1], n12, n24, n17, n31, n21, n6, s3[4], s5[10], q32, s5[6], n10, n36, q19});
  assign o2 = (^{n18, q15, q23, s3[2], s2[1], s0[7], s4[4], q20, n1, q52, q42, s3[0], n2, s0[5], s2[4], n4, s2[0], s1[0]});
  assign o3 = (^{s0[1], s4[12], s4[6], q7, s3[7], n3, s5[0], s5[4], n40, s4[1], s3[6], n16, n25, n0, s4[11], s5[8], n5});
  assign o4 = (^{s2[3], n35, n13, s4[2], n30, n28, s4[0], q37, n46, n11, n43, q45, s0[2], q14, n38, s0[8], n27});
  assign o5 = (^{n8, s4[3], s5[5], q26, s3[12], s5[3], s3[3], s5[2], s0[3], s4[5], n48, s3[5], q9, s4[8], s0[4], n34, s3[1]});
endmodule
