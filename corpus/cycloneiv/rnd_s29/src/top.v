module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10);
  wire [12:0] s0;
  wire n1;
  reg q1;
  wire n2;
  wire n3;
  reg q3;
  wire [12:0] s1;
  wire n5;
  wire n6;
  reg q6;
  wire n7;
  wire n8;
  reg q8;
  wire [5:0] s2;
  wire n10;
  reg q10;
  wire n11;
  reg q11;
  wire n12;
  wire n13;
  reg q13;
  wire [8:0] s3;
  wire n15;
  reg q15;
  wire n16;
  wire n17;
  wire n18;
  reg q18;
  wire n19;
  reg q19;
  wire n20;
  reg q20;
  wire n21;
  reg q21;
  wire n22;
  reg q22;
  wire n23;
  reg q23;
  wire n24;
  wire n25;
  wire n26;
  wire n27;
  wire n28;
  wire [8:0] s4;
  wire n30;
  wire [12:0] s5;
  wire n32;
  wire n33;
  wire n34;
  wire n35;
  wire n36;
  reg q36;
  wire n37;
  reg q37;
  wire [7:0] s6;
  wire n39;
  wire n40;
  wire n41;
  wire n42;
  reg q42;
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
  reg q49;
  wire n50;
  reg q50;
  wire n51;
  wire n52;
  wire n53;
  wire n54;
  reg q54;
  wire n55;
  wire n56;
  wire n57;
  reg q57;
  wire n58;
  reg q58;
  wire n59;
  wire n60;
  wire n61;
  reg q61;
  wire [9:0] s7;
  wire n63;
  reg q63;
  wire n64;
  wire n65;
  reg q65;
  wire n66;
  wire n67;
  reg q67;
  wire n68;
  wire n69;
  wire n70;
  wire n71;
  wire [9:0] s8;
  wire n73;
  reg q73;
  wire n74;
  wire n75;
  reg q75;
  wire n76;
  wire [9:0] s9;
  wire n78;
  reg q78;
  wire n79;
  reg q79;
  wire n80;
  wire n81;
  wire n82;
  wire n83;
  wire n84;
  wire n85;
  wire n86;
  reg q86;
  wire n87;
  reg q87;
  assign s0 = {1'b0, i4, i9, i0, i4, i9, i8, i2, i8, i3, i7, i9, i1} + {1'b0, i1, i6, i6, i7, i4, i0, i1, i5, i9, i2, i8, i3};
  assign n1 = 16'h85ce >> {i0, s0[5], i6, i3};
  assign n2 = 16'h22cb >> {i4, s0[7], q1, s0[8]};
  assign n3 = 16'h96c6 >> {s0[7], s0[9], i6, s0[6]};
  assign s1 = {1'b0, s0[11], s0[5], q3, s0[1], s0[11], s0[5], q3, i4, s0[4], s0[10], i6, s0[3]} + {1'b0, i1, s0[6], i3, i5, s0[0], i6, s0[12], s0[5], n2, s0[12], s0[11], s0[11]};
  assign n5 = 16'h868b >> {s1[2], i7, s0[11], s1[9]};
  assign n6 = 16'hc7a7 >> {s1[9], i1, s0[7], i5};
  assign n7 = 16'h0157 >> {s1[10], s1[9], s0[12], i5};
  assign n8 = 16'h84b7 >> {i1, n2, i3, s0[9]};
  assign s2 = {1'b0, s0[11], i5, s1[5], s1[12], i0} - {1'b0, s1[10], s1[1], s0[8], s1[10], s0[7]};
  assign n10 = 16'h75e1 >> {i2, i3, s1[12], s0[8]};
  assign n11 = 16'he77c >> {n7, s0[7], s0[3], i4};
  assign n12 = 16'hbcda >> {i0, q3, s1[10], s0[6]};
  assign n13 = 16'hf3e8 >> {q11, s1[0], s2[3], i2};
  assign s3 = {1'b0, n12, i0, q3, s1[8], s1[8], i4, q8, s0[1]} + {1'b0, i5, i2, q13, n7, s0[8], i4, i8, q11};
  assign n15 = 16'hc1f4 >> {s0[5], n12, i4, s1[11]};
  assign n16 = 16'hb5cc >> {s3[7], s0[8], q8, i3};
  assign n17 = 16'h647c >> {n16, s2[2], s3[0], s3[1]};
  assign n18 = 16'h32af >> {s1[4], s3[7], s2[5], s3[8]};
  assign n19 = 16'hb7ef >> {s0[8], s0[4], s3[5], s2[3]};
  assign n20 = 16'h1e6c >> {s0[8], q10, s3[5], n12};
  assign n21 = 16'h9b26 >> {s1[2], s3[0], s2[0], s1[8]};
  assign n22 = 16'h86e2 >> {q15, n5, s3[0], i0};
  assign n23 = 16'h2f85 >> {s3[6], s1[2], s1[5], s0[6]};
  assign n24 = 16'h347b >> {q15, s3[5], q3, s0[11]};
  assign n25 = 16'h51da >> {s0[1], s2[3], q20, s0[5]};
  assign n26 = 16'h5789 >> {s1[2], s0[6], s1[10], n17};
  assign n27 = 16'h7ad2 >> {q22, s1[3], q21, s0[6]};
  assign n28 = 16'hcadd >> {q19, s3[3], s0[11], q19};
  assign s4 = {1'b0, s1[2], s2[1], s1[1], n7, s0[5], n26, s1[3], n2} - {1'b0, i8, i3, i6, q18, s0[7], q18, s2[0], n5};
  assign n30 = 16'ha4f0 >> {q3, q23, s1[4], s2[1]};
  assign s5 = {1'b0, s3[8], s2[2], s3[4], s1[1], s0[7], s4[7], s4[6], s3[2], s0[1], s4[6], s0[10], n27} - {1'b0, q23, i8, s2[4], s2[3], s1[11], n5, n26, s1[1], n2, s1[2], s0[7], s1[0]};
  assign n32 = 16'h2634 >> {n5, q15, i8, n12};
  assign n33 = 16'h4e76 >> {s4[3], s4[7], s4[7], s2[0]};
  assign n34 = 16'h2f3e >> {s5[9], s3[6], n12, q10};
  assign n35 = 16'hda5b >> {s5[6], s2[4], s3[6], s3[6]};
  assign n36 = 16'h29f0 >> {s4[2], n35, n12, s5[6]};
  assign n37 = 16'hdf54 >> {n30, s5[8], s4[8], s5[0]};
  assign s6 = {1'b0, s5[9], s1[2], s4[5], n12, s4[5], s1[6], q20} - {1'b0, s5[3], s0[1], s2[2], s1[0], q23, q8, s1[4]};
  assign n39 = 16'h166e >> {n27, q18, n17, n33};
  assign n40 = 16'hd02f >> {s5[12], n39, s5[12], n32};
  assign n41 = 16'h4e0a >> {s6[5], n27, q19, s1[10]};
  assign n42 = 16'hfdcb >> {n35, s3[3], s6[1], s3[5]};
  assign n43 = 16'h1acd >> {n28, s5[3], s6[4], s4[6]};
  assign n44 = 16'h5ff5 >> {s6[4], s5[4], n28, n39};
  assign n45 = 16'haf6d >> {s5[0], n25, q23, s6[6]};
  assign n46 = 16'hcad7 >> {q18, s6[3], n32, q22};
  assign n47 = 16'h4db1 >> {s0[5], s6[0], s4[5], s4[3]};
  assign n48 = 16'hee50 >> {s4[7], s5[9], s6[2], s4[0]};
  assign n49 = 16'h40be >> {s0[11], n33, q42, s4[6]};
  assign n50 = 16'h85f2 >> {s5[6], s5[0], n40, s5[5]};
  assign n51 = 16'hc4cd >> {n26, s6[3], s5[6], s4[7]};
  assign n52 = 16'h2cd4 >> {s5[12], s5[12], n24, n28};
  assign n53 = 16'h7e71 >> {n41, s6[4], s5[10], s4[7]};
  assign n54 = 16'h0f96 >> {s6[4], n43, s6[4], s4[0]};
  assign n55 = 16'hfd4b >> {s6[4], s4[1], s4[2], s4[8]};
  assign n56 = 16'h1638 >> {s5[8], s6[3], s5[0], n46};
  assign n57 = 16'h32f0 >> {s5[8], n24, s4[7], n25};
  assign n58 = 16'hb7e0 >> {q45, s4[3], s2[1], q47};
  assign n59 = 16'h34c5 >> {q37, n27, s3[8], q50};
  assign n60 = 16'hb07e >> {q58, n33, s6[5], q48};
  assign n61 = 16'hd5e4 >> {s4[3], s4[6], n55, n59};
  assign s7 = {1'b0, n39, s6[4], s0[3], s1[1], q22, s1[6], q42, n7, s2[5]} - {1'b0, s4[6], s3[0], s0[12], n12, s1[7], s4[8], q36, q13, s1[1]};
  assign n63 = 16'h60a9 >> {n59, s7[8], s4[0], n44};
  assign n64 = 16'he503 >> {s4[7], q63, n55, q22};
  assign n65 = 16'hc85f >> {s1[12], q48, s7[8], n52};
  assign n66 = 16'he93d >> {s0[0], s7[0], s5[6], s5[7]};
  assign n67 = 16'h3dd6 >> {q37, s6[3], q58, n66};
  assign n68 = 16'hfd6b >> {s5[8], n40, s4[2], s5[12]};
  assign n69 = 16'he8e0 >> {q50, s6[2], n33, n35};
  assign n70 = 16'haf78 >> {s1[6], q54, n46, s1[12]};
  assign n71 = 16'hc35c >> {q61, s7[9], q50, n41};
  assign s8 = {1'b0, s3[7], s2[4], s4[5], n69, n35, n46, s5[1], s5[12], q13} - {1'b0, s1[10], n71, n16, n5, q49, q57, s6[3], s2[2], s1[12]};
  assign n73 = 16'h2079 >> {q57, n43, s8[4], s7[1]};
  assign n74 = 16'h35f0 >> {n43, s7[6], q54, s6[4]};
  assign n75 = 16'h3701 >> {s7[4], q42, n44, s8[2]};
  assign n76 = 16'h8cf2 >> {s8[2], q61, n59, q63};
  assign s9 = {1'b0, i4, s5[7], q8, s1[12], s3[2], s5[0], s5[7], s1[5], s2[1]} + {1'b0, s5[5], s4[0], s3[8], s8[5], q19, n12, s8[6], s7[4], n52};
  assign n78 = 16'h8913 >> {q45, q67, n46, n44};
  assign n79 = 16'hf403 >> {n64, s7[9], n59, s9[2]};
  assign n80 = 16'hba20 >> {s9[1], n74, n70, n53};
  assign n81 = 16'h1c59 >> {n68, q79, s9[5], s7[9]};
  assign n82 = 16'hb063 >> {s9[3], s8[8], n66, s9[8]};
  assign n83 = 16'h416a >> {n68, s2[2], n80, s9[6]};
  assign n84 = 16'hb0a3 >> {n76, n71, s7[9], n66};
  assign n85 = 16'hb8c3 >> {s8[6], s3[4], s9[1], n53};
  assign n86 = 16'heaa8 >> {n81, n56, s8[4], s7[4]};
  assign n87 = 16'he673 >> {s8[2], q63, n76, s5[0]};
  always @(posedge clk0 or posedge i4) begin if (i4) q1 <= 1'b0; else begin if (i6) begin q1 <= n1; end end end
  always @(posedge clk0) begin q3 <= n3; end
  always @(posedge clk0) begin if (s0[7]) begin if (n2) q6 <= 1'b0; else if (i5) q6 <= q1; else q6 <= n6; end end
  always @(posedge clk0) begin if (s0[12]) q8 <= 1'b0; else if (s0[6]) q8 <= s0[2]; else q8 <= n8; end
  always @(posedge clk0 or posedge i9) begin if (i9) q10 <= 1'b1; else begin q10 <= n10; end end
  always @(posedge clk0 or posedge s2[3]) begin if (s2[3]) q11 <= 1'b0; else begin q11 <= n11; end end
  always @(posedge clk0 or posedge s1[11]) begin if (s1[11]) q13 <= 1'b0; else begin q13 <= n13; end end
  always @(posedge clk0 or posedge s3[2]) begin if (s3[2]) q15 <= 1'b1; else begin if (q6) q15 <= s3[1]; else q15 <= n15; end end
  always @(posedge clk0 or posedge i8) begin if (i8) q18 <= 1'b0; else begin if (s0[5]) q18 <= 1'b0; else q18 <= n18; end end
  always @(posedge clk0) begin q19 <= n19; end
  always @(posedge clk0) begin if (i4) q20 <= i2; else q20 <= n20; end
  always @(negedge clk0) begin if (s0[6]) q21 <= 1'b0; else if (s2[3]) q21 <= i5; else q21 <= n21; end
  always @(posedge clk0) begin q22 <= n22; end
  always @(posedge clk0) begin if (i9) q23 <= 1'b0; else q23 <= n23; end
  always @(posedge clk0) begin q36 <= n36; end
  always @(posedge clk0) begin if (q3) q37 <= 1'b0; else q37 <= n37; end
  always @(negedge clk0) begin if (s0[5]) q42 <= 1'b0; else q42 <= n42; end
  always @(posedge clk0) begin if (s5[0]) q45 <= 1'b0; else q45 <= n45; end
  always @(negedge clk0) begin q47 <= n47; end
  always @(posedge clk0 or posedge q11) begin if (q11) q48 <= 1'b1; else begin if (q22) q48 <= n12; else q48 <= n48; end end
  always @(posedge clk0) begin if (n30) q49 <= q47; else q49 <= n49; end
  always @(posedge clk0) begin if (n27) begin if (q22) q50 <= 1'b0; else q50 <= n50; end end
  always @(negedge clk0 or posedge s4[4]) begin if (s4[4]) q54 <= 1'b1; else begin if (s5[6]) q54 <= 1'b0; else if (s0[5]) q54 <= s5[2]; else q54 <= n54; end end
  always @(posedge clk0 or posedge s5[11]) begin if (s5[11]) q57 <= 1'b1; else begin q57 <= n57; end end
  always @(posedge clk0) begin if (s3[2]) begin if (s1[3]) q58 <= 1'b0; else if (s3[7]) q58 <= s3[1]; else q58 <= n58; end end
  always @(posedge clk0) begin if (q18) q61 <= 1'b0; else if (n32) q61 <= s6[3]; else q61 <= n61; end
  always @(posedge clk0) begin q63 <= n63; end
  always @(posedge clk0) begin if (s3[2]) begin if (s5[7]) q65 <= q36; else q65 <= n65; end end
  always @(posedge clk0) begin if (n43) begin q67 <= n67; end end
  always @(posedge clk0) begin if (s5[8]) q73 <= s1[8]; else q73 <= n73; end
  always @(posedge clk0) begin q75 <= n75; end
  always @(posedge clk0) begin q78 <= n78; end
  always @(posedge clk0) begin if (s0[5]) q79 <= 1'b0; else if (s6[1]) q79 <= i0; else q79 <= n79; end
  always @(posedge clk0) begin if (s9[7]) begin q86 <= n86; end end
  always @(posedge clk0 or posedge i1) begin if (i1) q87 <= 1'b0; else begin q87 <= n87; end end
  assign o0 = ~(^{s0[4], s1[2], q45, n84, s9[7], n55, s5[6], q61, n66, n32, q11, s8[8], s7[0], s7[7], s7[4], n82, s3[1]});
  assign o1 = (^{s0[9], s0[10], s1[10], s5[7], s1[9], s8[6], q65, q54, n30, s7[9], s9[8], s0[6], s1[11], q86, s7[1], s1[1], n24});
  assign o2 = (^{q15, s4[4], s1[12], n27, s9[0], s1[4], s5[9], s6[0], s6[1], s7[2], n64, s3[2], q3, q67, s2[5], s4[1], q79});
  assign o3 = ~(^{n35, s8[9], s2[0], n71, s8[2], n56, s6[2], q48, s0[3], s0[11], s6[5], s4[8], q8, s5[5], s5[4], s0[12]});
  assign o4 = (^{n17, q37, n40, s5[8], n33, n16, n26, s4[2], q87, s7[3], n60, q18, q36, s4[7], s6[4], s5[3]});
  assign o5 = (^{q22, n25, s4[3], s6[3], n34, s5[2], s3[7], n51, s1[0], s0[1], s8[7], q50, q47, q6, s9[4], q57});
  assign o6 = (^{s9[5], s6[7], s8[4], s8[0], s8[5], s0[8], n83, s5[1], n80, q58, n81, n53, s8[3], q75, s9[2], q21});
  assign o7 = (^{s5[10], s4[5], n46, n28, n43, n74, s3[4], s5[11], n39, s1[6], s0[2], n69, q42, s3[0], s5[0], q13});
  assign o8 = (^{s3[3], q63, s6[6], s0[5], n68, q73, s2[2], n52, n59, s9[3], s0[0], n12, s4[0], s2[4], s7[5], q49});
  assign o9 = (^{s3[8], q1, s5[12], s2[1], s9[6], s0[7], s7[6], n76, n5, s7[8], s3[6], s4[6], q10, n44, s1[8], n41});
  assign o10 = ~(^{s2[3], n70, s8[1], q19, q20, s1[3], s1[7], q78, s9[9], q23, n85, s3[5], n2, n7, s1[5], s9[1]});
endmodule
