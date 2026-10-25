module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, input i18, input i19, output o0, output o1, output o2, output o3);
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
  reg q11;
  wire n12;
  reg q12;
  wire n13;
  reg q13;
  wire n14;
  reg q14;
  wire n15;
  wire n16;
  reg q16;
  wire n17;
  wire n18;
  wire n19;
  wire n20;
  reg q20;
  wire n21;
  reg q21;
  wire n22;
  wire n23;
  reg q23;
  wire n24;
  reg q24;
  wire n25;
  wire n26;
  wire n27;
  wire n28;
  wire n29;
  wire n30;
  reg q30;
  wire n31;
  reg q31;
  wire n32;
  wire n33;
  reg q33;
  wire n34;
  reg q34;
  wire n35;
  wire n36;
  wire n37;
  reg q37;
  wire n38;
  reg q38;
  wire n39;
  reg q39;
  wire n40;
  wire n41;
  reg q41;
  wire n42;
  wire n43;
  wire n44;
  wire n45;
  wire n46;
  wire n47;
  wire n48;
  wire n49;
  reg q49;
  wire n50;
  wire n51;
  wire n52;
  wire n53;
  reg q53;
  wire n54;
  wire n55;
  wire n56;
  reg q56;
  wire n57;
  reg q57;
  wire n58;
  reg q58;
  wire n59;
  wire n60;
  wire n61;
  wire n62;
  wire n63;
  reg q63;
  wire n64;
  reg q64;
  wire n65;
  wire n66;
  assign n0 = 16'h535e >> {i4, i12, i13, i16};
  assign n1 = 16'hdf81 >> {i17, i15, i12, i6};
  assign n2 = 16'hdc6a >> {i0, i14, i16, i15};
  assign n3 = 16'h4b44 >> {i3, i10, i19, i8};
  assign n4 = 16'hf4b1 >> {i8, i15, i6, i19};
  assign n5 = 16'h6266 >> {i5, i14, i6, i13};
  assign n6 = 16'he481 >> {i17, i15, i3, i5};
  assign n7 = 16'h96a0 >> {n5, i17, i8, i6};
  assign n8 = 16'h0d0f >> {i4, n3, i14, n1};
  assign n9 = 16'h7649 >> {n8, i13, q7, n8};
  assign n10 = 16'h2ca2 >> {i14, n8, n3, i15};
  assign n11 = 16'hc8b2 >> {i4, n5, n0, i16};
  assign n12 = 16'hc48c >> {i18, i6, n1, i16};
  assign n13 = 16'h36d1 >> {i3, q7, i13, i18};
  assign n14 = 16'h0bbe >> {i12, n0, n1, n6};
  assign n15 = 16'h3929 >> {i3, i2, n3, i17};
  assign n16 = 16'he2f8 >> {i9, i0, i11, n10};
  assign n17 = 16'had2d >> {n1, q16, n1, n8};
  assign n18 = 16'h998d >> {n5, i7, q13, i17};
  assign n19 = 16'h7855 >> {n10, q7, i1, i1};
  assign n20 = 16'hee8f >> {q7, q11, n5, i19};
  assign n21 = 16'h0fce >> {i9, q16, n15, n10};
  assign n22 = 16'h936c >> {n19, i12, i1, i7};
  assign n23 = 16'h6b31 >> {n19, i17, q13, i19};
  assign n24 = 16'he64c >> {n3, n19, n1, n10};
  assign n25 = 16'hf840 >> {q14, i14, i18, n10};
  assign n26 = 16'h281a >> {n3, i19, q23, i8};
  assign n27 = 16'h00f9 >> {q16, n2, n6, i18};
  assign n28 = 16'hf840 >> {i3, n10, q11, i19};
  assign n29 = 16'hc24a >> {i0, i5, i1, i15};
  assign n30 = 16'hacd6 >> {n15, q23, n4, q13};
  assign n31 = 16'h470d >> {q21, n4, q24, i0};
  assign n32 = 16'ha0f7 >> {i3, q24, n22, i18};
  assign n33 = 16'hbc8d >> {q23, i13, q20, i10};
  assign n34 = 16'h0b91 >> {i2, i16, i0, q12};
  assign n35 = 16'ha094 >> {q34, n3, n15, i10};
  assign n36 = 16'hd50a >> {n2, i9, i9, i8};
  assign n37 = 16'hfa4c >> {i6, n28, n26, q7};
  assign n38 = 16'h11a3 >> {q14, n6, q30, n32};
  assign n39 = 16'hb007 >> {q13, i12, i2, i3};
  assign n40 = 16'h7e8b >> {n10, n4, i2, i16};
  assign n41 = 16'h83a7 >> {i16, i12, i16, n4};
  assign n42 = 16'hef05 >> {q23, n5, i3, q20};
  assign n43 = 16'h9360 >> {q13, n25, n22, i16};
  assign n44 = 16'h02a4 >> {q41, q16, n10, n4};
  assign n45 = 16'hd444 >> {i18, i12, n15, i13};
  assign n46 = 16'h200d >> {q39, n36, q21, i16};
  assign n47 = 16'h9553 >> {i17, i15, q37, i16};
  assign n48 = 16'h25ba >> {i15, n0, i15, q11};
  assign n49 = 16'h9985 >> {q39, n8, n40, n44};
  assign n50 = 16'hce73 >> {q21, q14, q38, n10};
  assign n51 = 16'h1db2 >> {n15, n35, i19, n26};
  assign n52 = 16'h4e20 >> {q30, q21, n48, q33};
  assign n53 = 16'h0ba3 >> {n19, q38, n4, n22};
  assign n54 = 16'h8f56 >> {n45, n3, n8, i14};
  assign n55 = 16'h6981 >> {n3, i9, n32, q9};
  assign n56 = 16'h5ac2 >> {n36, q12, q7, n55};
  assign n57 = 16'h4d9d >> {i18, n48, q11, q37};
  assign n58 = 16'he311 >> {q49, n27, n48, q9};
  assign n59 = 16'h09b9 >> {i9, q58, q24, q39};
  assign n60 = 16'h4ab0 >> {n59, q11, q21, q24};
  assign n61 = 16'h0e75 >> {n48, n32, n59, q41};
  assign n62 = 16'hfa0a >> {n48, q23, q34, n4};
  assign n63 = 16'h795c >> {q13, n59, n42, n52};
  assign n64 = 16'hdda2 >> {n25, n60, q7, q33};
  assign n65 = 16'h42c3 >> {q31, i13, n26, q23};
  assign n66 = 16'he8f2 >> {q57, n32, q9, n19};
  always @(posedge clk1 or posedge n4) begin if (n4) q7 <= 1'b1; else begin if (n1) q7 <= i7; else q7 <= n7; end end
  always @(posedge clk0) begin if (i2) q9 <= 1'b0; else if (i1) q9 <= n0; else q9 <= n9; end
  always @(posedge clk1 or posedge i3) begin if (i3) q11 <= 1'b0; else begin q11 <= n11; end end
  always @(posedge clk0 or posedge i6) begin if (i6) q12 <= 1'b1; else begin if (i8) q12 <= 1'b0; else q12 <= n12; end end
  always @(posedge clk0) begin if (i6) begin if (i8) q13 <= n10; else q13 <= n13; end end
  always @(posedge clk0) begin if (n5) begin if (i8) q14 <= n10; else q14 <= n14; end end
  always @(posedge clk1 or posedge q13) begin if (q13) q16 <= 1'b1; else begin q16 <= n16; end end
  always @(posedge clk1) begin q20 <= n20; end
  always @(posedge clk0) begin if (i13) begin q21 <= n21; end end
  always @(posedge clk0) begin q23 <= n23; end
  always @(posedge clk0 or posedge i11) begin if (i11) q24 <= 1'b0; else begin q24 <= n24; end end
  always @(posedge clk1) begin q30 <= n30; end
  always @(negedge clk1) begin q31 <= n31; end
  always @(posedge clk0) begin if (n32) begin q33 <= n33; end end
  always @(negedge clk0) begin q34 <= n34; end
  always @(posedge clk0) begin if (i7) q37 <= 1'b0; else q37 <= n37; end
  always @(posedge clk1) begin if (n22) q38 <= n15; else q38 <= n38; end
  always @(posedge clk1) begin if (n8) q39 <= q23; else q39 <= n39; end
  always @(posedge clk0 or posedge i11) begin if (i11) q41 <= 1'b0; else begin if (n10) q41 <= i3; else q41 <= n41; end end
  always @(posedge clk0) begin q49 <= n49; end
  always @(posedge clk0) begin if (q14) begin q53 <= n53; end end
  always @(posedge clk1) begin q56 <= n56; end
  always @(posedge clk1 or posedge q20) begin if (q20) q57 <= 1'b1; else begin if (n10) q57 <= 1'b0; else if (n19) q57 <= i12; else q57 <= n57; end end
  always @(posedge clk1) begin if (n28) begin q58 <= n58; end end
  always @(posedge clk1) begin if (i1) begin if (q9) q63 <= 1'b0; else q63 <= n63; end end
  always @(negedge clk1) begin if (q11) begin if (n26) q64 <= 1'b0; else q64 <= n64; end end
  assign o0 = (^{n15, q9, q63, q7, q39, q33, n19, q49, n54, q24, n6, n0, q56, q64, n35, q13, q12});
  assign o1 = (^{n18, n65, n66, n47, n61, q21, n17, n22, n44, n5, n52, n25, n43, n60, q20, q34, q57});
  assign o2 = (^{n55, n3, n45, n27, q30, q37, q53, n62, n48, n46, n32, q23, q41, q11, n4, n8, n29});
  assign o3 = (^{n59, q16, n28, n10, n1, n51, q58, q38, n40, q14, q31, n36, n2, n50, n26, n42});
endmodule
