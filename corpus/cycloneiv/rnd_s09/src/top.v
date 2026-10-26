module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, output o0, output o1, output o2, output o3);
  wire n0;
  wire n1;
  reg q1;
  wire n2;
  wire n3;
  wire n4;
  wire n5;
  reg q5;
  wire n6;
  wire n7;
  wire n8;
  wire [10:0] s0;
  wire n10;
  wire n11;
  reg q11;
  wire n12;
  reg q12;
  wire n13;
  wire [10:0] s1;
  wire n15;
  wire n16;
  reg q16;
  wire n17;
  wire n18;
  reg q18;
  wire n19;
  reg q19;
  wire n20;
  wire n21;
  wire n22;
  wire n23;
  reg q23;
  wire [9:0] s2;
  wire n25;
  reg q25;
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
  wire [10:0] s3;
  wire n35;
  wire n36;
  reg q36;
  wire n37;
  reg q37;
  wire n38;
  reg q38;
  wire [8:0] s4;
  wire [7:0] s5;
  wire n41;
  wire n42;
  reg q42;
  wire n43;
  wire [12:0] s6;
  wire n45;
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
  reg q52;
  wire n53;
  wire n54;
  reg q54;
  wire n55;
  reg q55;
  wire n56;
  wire n57;
  reg q57;
  wire n58;
  reg q58;
  wire n59;
  wire n60;
  reg q60;
  wire n61;
  wire n62;
  wire n63;
  wire n64;
  reg q64;
  wire n65;
  reg q65;
  wire n66;
  wire n67;
  reg q67;
  wire n68;
  reg q68;
  wire n69;
  reg q69;
  assign n0 = 16'hadc3 >> {i1, i9, i5, i2};
  assign n1 = 16'h4af9 >> {i7, i2, i14, i12};
  assign n2 = 16'h3a7b >> {i3, i10, i6, i11};
  assign n3 = 16'h8682 >> {i16, i7, i15, q1};
  assign n4 = 16'hacf3 >> {i1, i7, q1, i10};
  assign n5 = 16'h18a1 >> {i11, i8, n2, i9};
  assign n6 = 16'h02df >> {i15, n0, i1, i13};
  assign n7 = 16'hc13c >> {i8, i3, q5, i14};
  assign n8 = 16'h57ec >> {i12, i13, i8, i0};
  assign s0 = {1'b0, n8, n4, i0, i14, n4, n0, i12, i7, n2, i16} + {1'b0, n6, n3, n0, i1, i1, i12, i6, i5, q1, n3};
  assign n10 = 16'hb8eb >> {s0[2], i13, s0[4], s0[9]};
  assign n11 = 16'h2e18 >> {s0[7], s0[7], n4, n10};
  assign n12 = 16'h188f >> {i15, i2, i6, n3};
  assign n13 = 16'h111b >> {i10, i1, n4, i14};
  assign s1 = {1'b0, q5, i8, i1, i5, n7, n6, s0[9], s0[8], i11, q12} + {1'b0, i17, n13, s0[2], i5, i7, i4, i12, s0[5], s0[2], i7};
  assign n15 = 16'h874d >> {i5, i2, s0[6], s0[0]};
  assign n16 = 16'h96bd >> {s1[2], i15, i1, s0[2]};
  assign n17 = 16'h9ed5 >> {s0[9], s1[3], s0[7], s1[4]};
  assign n18 = 16'h558c >> {i17, i1, i13, s0[2]};
  assign n19 = 16'h32ec >> {s1[9], s1[4], n10, n2};
  assign n20 = 16'h42f9 >> {i15, s1[5], q18, s0[2]};
  assign n21 = 16'hb126 >> {q16, n3, s1[3], i13};
  assign n22 = 16'hda64 >> {q5, i11, s0[10], s1[5]};
  assign n23 = 16'h0a18 >> {s0[9], s1[8], s0[10], n10};
  assign s2 = {1'b0, i14, i3, i11, q11, i12, i12, s1[6], q5, i12} - {1'b0, q18, s1[2], q19, n13, s0[9], i5, i11, i0, n7};
  assign n25 = 16'h0eea >> {n4, s2[0], s0[7], s2[7]};
  assign n26 = 16'h4324 >> {s2[2], s0[2], q18, s0[10]};
  assign n27 = 16'hbd65 >> {s1[4], s0[0], i5, q12};
  assign n28 = 16'ha786 >> {q11, s1[10], s1[4], n27};
  assign n29 = 16'h1fb2 >> {s0[0], q5, n17, s0[8]};
  assign n30 = 16'h8d94 >> {q26, n15, q11, s1[7]};
  assign n31 = 16'he1cb >> {s1[2], s0[6], s1[8], n13};
  assign n32 = 16'hd4c8 >> {s0[5], n29, s1[7], n22};
  assign n33 = 16'he72f >> {i2, s2[7], n2, s2[8]};
  assign s3 = {1'b0, s1[1], n33, i0, s0[5], n17, i16, i11, i4, i5, s2[0]} - {1'b0, s2[1], n3, q12, q11, i6, i7, n6, i10, i10, s0[9]};
  assign n35 = 16'h53fb >> {n31, s0[6], n28, q11};
  assign n36 = 16'h9d29 >> {s3[2], s0[2], s2[0], n28};
  assign n37 = 16'hf361 >> {q26, s3[9], s2[8], q26};
  assign n38 = 16'h5dfe >> {n27, s3[8], s1[1], q36};
  assign s4 = {1'b0, s0[0], i11, s3[6], q18, s1[3], s1[1], q23, s3[5]} - {1'b0, s3[10], n6, n17, s2[6], n15, n6, i11, i7};
  assign s5 = {1'b0, i10, s2[4], s0[2], n8, s0[8], s4[6], s1[6]} + {1'b0, s4[4], i6, n20, n28, s3[6], s1[1], n35};
  assign n41 = 16'h1396 >> {s2[6], n15, s4[7], n31};
  assign n42 = 16'hccf8 >> {s2[8], s4[4], s3[4], n31};
  assign n43 = 16'h7354 >> {s5[6], n31, s3[2], n21};
  assign s6 = {1'b0, s3[1], s0[0], n33, s3[6], n20, i10, s0[1], i14, s1[9], q12, s1[5], q18} - {1'b0, n8, i6, q36, n33, s1[5], s5[2], s5[7], s1[4], s2[0], n17, s4[7], s0[8]};
  assign n45 = 16'h26dc >> {q36, q32, s3[10], s4[2]};
  assign n46 = 16'h4e89 >> {s4[1], s5[1], s3[0], s4[3]};
  assign n47 = 16'h7ff3 >> {i10, s3[3], n33, s3[9]};
  assign n48 = 16'h77db >> {s4[3], s6[12], s6[11], s3[3]};
  assign n49 = 16'hb28b >> {s6[1], s6[12], q38, s6[2]};
  assign n50 = 16'h8b7f >> {s4[5], s1[9], s3[6], s5[2]};
  assign n51 = 16'hf61b >> {q49, s3[2], n21, n45};
  assign n52 = 16'hbf04 >> {n20, q42, n33, s4[5]};
  assign n53 = 16'h8d38 >> {q37, s4[7], n46, s6[0]};
  assign n54 = 16'h5ff7 >> {n45, s2[6], n53, q52};
  assign n55 = 16'h8549 >> {q5, s6[12], q36, s2[5]};
  assign n56 = 16'h8c8a >> {s5[4], n46, s4[8], q36};
  assign n57 = 16'hec42 >> {s5[0], i13, s4[2], s3[2]};
  assign n58 = 16'h24dc >> {s3[4], s4[7], s4[6], n35};
  assign n59 = 16'h9207 >> {s6[6], n43, n4, s4[6]};
  assign n60 = 16'h506c >> {s0[6], n51, i7, n51};
  assign n61 = 16'h45c6 >> {n13, n53, s6[11], s6[10]};
  assign n62 = 16'h0697 >> {s5[6], q42, s1[5], s4[3]};
  assign n63 = 16'heef6 >> {s6[5], n22, n43, q54};
  assign n64 = 16'hddd0 >> {n51, s5[5], s4[0], s4[5]};
  assign n65 = 16'h7ff2 >> {n41, n56, n63, s6[3]};
  assign n66 = 16'hd2c9 >> {q50, s6[5], s5[2], s5[0]};
  assign n67 = 16'h05b4 >> {q47, q48, s6[8], q49};
  assign n68 = 16'h03b6 >> {s5[5], n61, s4[6], n41};
  assign n69 = 16'hdb0c >> {s5[2], s0[9], n51, q57};
  always @(posedge clk0 or posedge i3) begin if (i3) q1 <= 1'b1; else begin if (i4) q1 <= i5; else q1 <= n1; end end
  always @(negedge clk1) begin if (i7) q5 <= 1'b0; else q5 <= n5; end
  always @(posedge clk0) begin if (i16) begin q11 <= n11; end end
  always @(posedge clk1) begin if (i12) q12 <= 1'b0; else if (s0[8]) q12 <= i10; else q12 <= n12; end
  always @(posedge clk0) begin q16 <= n16; end
  always @(posedge clk0) begin if (n13) begin if (i0) q18 <= 1'b0; else if (n17) q18 <= s0[6]; else q18 <= n18; end end
  always @(posedge clk0 or posedge n3) begin if (n3) q19 <= 1'b0; else begin q19 <= n19; end end
  always @(posedge clk0) begin if (q19) begin if (s1[6]) q23 <= 1'b0; else if (i8) q23 <= i3; else q23 <= n23; end end
  always @(posedge clk0) begin q25 <= n25; end
  always @(posedge clk1) begin if (i4) q26 <= 1'b0; else q26 <= n26; end
  always @(posedge clk0) begin if (i9) begin if (s0[2]) q32 <= 1'b0; else if (s0[2]) q32 <= i11; else q32 <= n32; end end
  always @(posedge clk1 or posedge n15) begin if (n15) q36 <= 1'b1; else begin q36 <= n36; end end
  always @(posedge clk1) begin if (s1[6]) begin if (s1[10]) q37 <= s2[2]; else q37 <= n37; end end
  always @(posedge clk0) begin q38 <= n38; end
  always @(posedge clk0) begin q42 <= n42; end
  always @(posedge clk0) begin q47 <= n47; end
  always @(negedge clk0) begin if (q18) begin if (s3[2]) q48 <= 1'b0; else if (n31) q48 <= s3[6]; else q48 <= n48; end end
  always @(posedge clk1) begin if (i5) q49 <= s1[2]; else q49 <= n49; end
  always @(posedge clk1) begin if (s1[8]) begin if (i14) q50 <= q47; else q50 <= n50; end end
  always @(posedge clk1) begin if (s0[10]) begin q52 <= n52; end end
  always @(posedge clk1 or posedge s3[6]) begin if (s3[6]) q54 <= 1'b1; else begin if (i5) q54 <= 1'b0; else q54 <= n54; end end
  always @(posedge clk1) begin q55 <= n55; end
  always @(posedge clk1) begin if (s3[6]) q57 <= s5[6]; else q57 <= n57; end
  always @(posedge clk1) begin if (s0[1]) begin q58 <= n58; end end
  always @(posedge clk1 or posedge q26) begin if (q26) q60 <= 1'b1; else begin q60 <= n60; end end
  always @(posedge clk0) begin if (s5[2]) q64 <= 1'b0; else if (i9) q64 <= s5[5]; else q64 <= n64; end
  always @(posedge clk0 or posedge n0) begin if (n0) q65 <= 1'b0; else begin q65 <= n65; end end
  always @(posedge clk0 or posedge n66) begin if (n66) q67 <= 1'b0; else begin if (q65) q67 <= n10; else q67 <= n67; end end
  always @(posedge clk1 or posedge i10) begin if (i10) q68 <= 1'b1; else begin if (n56) q68 <= 1'b0; else q68 <= n68; end end
  always @(posedge clk1) begin q69 <= n69; end
  assign o0 = (^{s1[1], s0[6], s1[3], s6[9], q69, s2[1], q48, s1[5], n56, s1[4], q32, s2[8], q18, s0[8], q60, s0[4], n27, q19, s4[7], s2[3], q52, s6[10], q38, n29, n3, s6[3], s6[5], s1[8], s3[10], n20, s5[0], s1[7], n0, s0[7]});
  assign o1 = (^{s2[4], s0[2], s2[2], s1[9], n30, n8, n35, s5[3], s3[8], q57, q26, s1[6], s4[2], s4[5], s2[5], s0[3], n22, q36, s2[0], n41, n46, s3[4], n66, q16, s4[3], s6[6], n17, n59, n28, s6[4], s1[2], q55, s5[7], s4[8]});
  assign o2 = ~(^{s6[12], s5[2], n33, s3[2], s2[9], s0[0], n61, q49, n62, s5[5], n10, n13, q68, s3[3], n43, n53, s5[1], s4[0], q67, q11, n45, n31, s6[8], s3[1], s1[10], s6[1], s3[0], n63, s6[2], s3[7], n21, q58, q54, q64});
  assign o3 = (^{n15, n2, s0[10], s0[1], s0[5], q25, s4[4], q5, n51, q65, q42, s6[7], q12, s3[5], s5[6], s2[7], q50, n7, s0[9], q23, s6[0], n6, s6[11], n4, s4[6], s3[9], q47, q1, s2[6], q37, s5[4], s1[0], s4[1], s3[6]});
endmodule
