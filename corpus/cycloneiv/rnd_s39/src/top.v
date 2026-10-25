module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7);
  wire n0;
  reg q0;
  wire n1;
  reg q1;
  wire n2;
  reg q2;
  wire n3;
  wire n4;
  wire n5;
  wire [10:0] s0;
  wire n7;
  wire n8;
  wire n9;
  reg q9;
  wire n10;
  wire n11;
  wire n12;
  wire n13;
  wire n14;
  wire n15;
  wire n16;
  wire n17;
  reg q17;
  wire n18;
  reg q18;
  wire n19;
  wire n20;
  reg q20;
  wire n21;
  wire n22;
  wire n23;
  wire n24;
  wire n25;
  reg q25;
  wire n26;
  wire n27;
  wire n28;
  reg q28;
  wire n29;
  wire n30;
  wire n31;
  wire [6:0] s1;
  wire n33;
  wire n34;
  wire n35;
  wire n36;
  wire [9:0] s2;
  wire [6:0] s3;
  wire n39;
  reg q39;
  wire n40;
  wire n41;
  wire n42;
  wire n43;
  wire n44;
  wire n45;
  reg q45;
  wire n46;
  wire n47;
  reg q47;
  wire n48;
  reg q48;
  wire n49;
  wire n50;
  reg q50;
  wire n51;
  wire n52;
  wire n53;
  wire [11:0] s4;
  wire n55;
  wire n56;
  reg q56;
  wire [12:0] s5;
  wire n58;
  wire n59;
  wire n60;
  wire n61;
  wire n62;
  reg q62;
  assign n0 = 16'hedad >> {i3, i2, i10, i6};
  assign n1 = 16'h811b >> {i10, i9, i1, i7};
  assign n2 = 16'he23a >> {i4, i10, i3, q1};
  assign n3 = 16'h603d >> {i7, i2, i4, i8};
  assign n4 = 16'hdbe1 >> {i9, i4, i5, i2};
  assign n5 = 16'hc5d0 >> {i0, i11, q1, n3};
  assign s0 = {1'b0, i10, i9, i11, i3, n4, i1, i6, i7, i1, i4} - {1'b0, i8, n4, i7, q1, q0, i7, i7, i0, n3, i9};
  assign n7 = 16'haa9f >> {s0[10], i5, s0[4], i8};
  assign n8 = 16'hbd04 >> {i6, n4, s0[4], s0[3]};
  assign n9 = 16'ha1a3 >> {n4, s0[8], q1, n4};
  assign n10 = 16'h82fe >> {i1, i7, s0[7], n5};
  assign n11 = 16'hd60e >> {s0[2], i12, s0[7], q1};
  assign n12 = 16'h5170 >> {i12, i12, i2, n11};
  assign n13 = 16'h34f9 >> {i1, n5, i8, n7};
  assign n14 = 16'h117a >> {i12, n7, q1, i0};
  assign n15 = 16'hcb68 >> {s0[10], n13, s0[3], s0[1]};
  assign n16 = 16'hff04 >> {i8, s0[10], n13, i4};
  assign n17 = 16'h48f8 >> {i12, i4, n5, n15};
  assign n18 = 16'h0740 >> {i5, s0[3], n8, n16};
  assign n19 = 16'h7b5c >> {s0[8], n8, q1, n8};
  assign n20 = 16'hbbab >> {q17, n5, i8, q9};
  assign n21 = 16'h1665 >> {s0[9], s0[3], n13, n14};
  assign n22 = 16'h023c >> {s0[9], i6, i10, n16};
  assign n23 = 16'hee16 >> {i6, n10, i4, s0[9]};
  assign n24 = 16'ha951 >> {i9, n15, q18, n13};
  assign n25 = 16'h6fba >> {n14, n11, n23, i7};
  assign n26 = 16'h1257 >> {s0[4], n21, s0[4], s0[4]};
  assign n27 = 16'h140d >> {q1, q0, s0[1], n22};
  assign n28 = 16'hcec3 >> {n7, n4, n27, n13};
  assign n29 = 16'h5357 >> {n26, s0[3], n27, q2};
  assign n30 = 16'hb54f >> {i0, q1, i9, i1};
  assign n31 = 16'h28be >> {n26, n7, n26, n5};
  assign s1 = {1'b0, s0[0], q9, s0[6], n27, n21, n26} - {1'b0, s0[4], n11, i9, q25, q0, n19};
  assign n33 = 16'h20f7 >> {q20, i5, i1, n30};
  assign n34 = 16'hb271 >> {n24, s1[2], q17, s0[7]};
  assign n35 = 16'hb86f >> {n30, n31, n31, i12};
  assign n36 = 16'h70d4 >> {n31, n7, s0[5], n34};
  assign s2 = {1'b0, s0[5], n16, q9, s0[4], i2, s0[4], s1[1], n14, s0[7]} + {1'b0, q20, q2, q25, n3, i0, s0[5], s1[5], s1[2], s1[3]};
  assign s3 = {1'b0, i11, i6, n34, n15, s0[8], i0} - {1'b0, i3, q2, s1[6], i9, s1[5], n23};
  assign n39 = 16'hc0b0 >> {n12, n16, s0[7], q28};
  assign n40 = 16'h424c >> {n24, n7, s1[0], n7};
  assign n41 = 16'hdec1 >> {n7, q39, s1[6], s1[0]};
  assign n42 = 16'heeb3 >> {q25, s2[8], n34, q1};
  assign n43 = 16'hca09 >> {i8, s3[3], n34, n22};
  assign n44 = 16'h0c32 >> {n31, n19, s2[5], n33};
  assign n45 = 16'h4037 >> {s2[8], s1[5], s3[1], q39};
  assign n46 = 16'h4902 >> {s3[6], n40, n16, n26};
  assign n47 = 16'h551e >> {s2[0], s1[0], i0, s1[3]};
  assign n48 = 16'hc529 >> {s1[2], n42, s3[0], n13};
  assign n49 = 16'h6ac2 >> {s3[6], s2[1], n16, n19};
  assign n50 = 16'h8208 >> {n31, n46, n29, q25};
  assign n51 = 16'h7655 >> {q25, s1[0], q17, s1[1]};
  assign n52 = 16'h9dac >> {n15, n49, n35, s3[2]};
  assign n53 = 16'ha38e >> {n24, n15, n33, n44};
  assign s4 = {1'b0, s2[0], n53, q50, s2[6], s1[1], s1[1], n3, q0, q9, n36, n26} + {1'b0, n46, n16, i10, s1[5], q48, q47, i2, q1, s3[6], s1[1], s3[3]};
  assign n55 = 16'h3e51 >> {s2[0], s4[8], n36, s2[2]};
  assign n56 = 16'h5df3 >> {n35, n46, s4[8], s1[1]};
  assign s5 = {1'b0, n51, s0[7], q18, s4[1], n43, q25, s4[9], n51, n14, s0[0], s1[3], i11} + {1'b0, n15, i5, n7, s4[0], s1[2], s3[1], s1[1], q1, i9, n14, s2[2], n19};
  assign n58 = 16'h6e9a >> {s4[2], s4[7], s0[8], s5[3]};
  assign n59 = 16'h56a2 >> {s3[2], q45, n55, q39};
  assign n60 = 16'h6d3b >> {n30, s2[5], s2[9], n40};
  assign n61 = 16'h133c >> {s2[2], s4[0], s3[0], n60};
  assign n62 = 16'ha71d >> {s5[7], s5[10], s5[9], n49};
  always @(posedge clk0 or posedge i12) begin if (i12) q0 <= 1'b0; else begin q0 <= n0; end end
  always @(posedge clk0) begin q1 <= n1; end
  always @(posedge clk0) begin if (i2) q2 <= 1'b0; else q2 <= n2; end
  always @(posedge clk0) begin q9 <= n9; end
  always @(negedge clk0 or posedge i7) begin if (i7) q17 <= 1'b0; else begin q17 <= n17; end end
  always @(posedge clk0) begin if (n3) q18 <= 1'b0; else q18 <= n18; end
  always @(posedge clk0) begin if (q0) begin q20 <= n20; end end
  always @(negedge clk0) begin if (n4) q25 <= 1'b0; else q25 <= n25; end
  always @(posedge clk0 or posedge i2) begin if (i2) q28 <= 1'b0; else begin q28 <= n28; end end
  always @(posedge clk0) begin if (s0[0]) begin q39 <= n39; end end
  always @(posedge clk0) begin q45 <= n45; end
  always @(posedge clk0 or posedge n41) begin if (n41) q47 <= 1'b0; else begin if (i6) q47 <= 1'b0; else if (s3[6]) q47 <= s1[6]; else q47 <= n47; end end
  always @(posedge clk0 or posedge s0[7]) begin if (s0[7]) q48 <= 1'b0; else begin q48 <= n48; end end
  always @(posedge clk0) begin q50 <= n50; end
  always @(posedge clk0 or posedge n21) begin if (n21) q56 <= 1'b0; else begin if (s2[0]) q56 <= n40; else q56 <= n56; end end
  always @(posedge clk0) begin if (q50) begin q62 <= n62; end end
  assign o0 = ~(^{n30, n16, n40, s4[8], n52, n29, n46, s4[1], n13, s5[2], n60, s0[2], s2[6], s0[0], s0[9]});
  assign o1 = ~(^{s4[7], q56, s5[1], s2[2], q48, n10, s0[10], s4[11], s0[7], s1[2], s4[0], s5[10], s0[8], q47, s5[12]});
  assign o2 = (^{q45, n23, q20, s5[8], n5, s3[1], n58, s3[5], n41, s2[8], s3[3], n61, n19, s2[5], n43});
  assign o3 = (^{n34, n21, s2[3], s3[6], s2[4], s5[0], n26, s0[6], s4[4], s4[6], s0[4], s1[1], n55, n49, q39});
  assign o4 = (^{q0, n51, s0[1], q62, s2[9], s5[4], s3[2], n11, s2[1], s5[9], n53, s5[3], n36, n12, q9});
  assign o5 = (^{n27, n15, s4[9], n42, n31, s5[11], q2, s4[3], n4, s1[6], s0[3], n3, q17, q25});
  assign o6 = (^{s1[3], s4[5], s3[0], s2[0], s3[4], s4[10], q18, n22, s4[2], n44, n24, n7, s1[0], s1[5]});
  assign o7 = (^{s5[7], n14, s0[5], n8, n59, n35, q50, s1[4], s5[5], n33, q1, q28, s2[7], s5[6]});
endmodule
