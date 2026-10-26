module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, input i18, input i19, input i20, input i21, input i22, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10, output o11, output o12);
  wire n0;
  wire n1;
  wire n2;
  reg q2;
  wire n3;
  reg q3;
  wire n4;
  wire n5;
  reg q5;
  wire n6;
  wire n7;
  reg q7;
  wire n8;
  wire n9;
  wire n10;
  reg q10;
  wire n11;
  wire n12;
  wire n13;
  reg q13;
  wire n14;
  reg q14;
  wire n15;
  wire n16;
  wire n17;
  wire n18;
  wire n19;
  wire n20;
  wire n21;
  wire n22;
  wire n23;
  reg q23;
  wire n24;
  reg q24;
  wire n25;
  wire n26;
  reg q26;
  wire n27;
  wire n28;
  reg q28;
  wire n29;
  reg q29;
  wire n30;
  reg q30;
  wire n31;
  wire n32;
  reg q32;
  wire n33;
  wire n34;
  wire n35;
  wire n36;
  reg q36;
  wire n37;
  wire n38;
  wire n39;
  reg q39;
  wire n40;
  wire n41;
  wire n42;
  reg q42;
  wire n43;
  wire n44;
  wire n45;
  wire n46;
  wire n47;
  wire n48;
  wire n49;
  wire n50;
  wire n51;
  reg q51;
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
  wire n59;
  wire n60;
  reg q60;
  wire n61;
  wire n62;
  reg q62;
  wire n63;
  wire n64;
  wire n65;
  reg q65;
  wire n66;
  wire n67;
  wire n68;
  reg q68;
  wire n69;
  wire n70;
  reg q70;
  wire n71;
  reg q71;
  wire n72;
  wire n73;
  reg q73;
  wire n74;
  wire n75;
  wire n76;
  reg q76;
  assign n0 = 16'h0a7d >> {i3, i10, i19, i14};
  assign n1 = 16'h449c >> {i6, i16, i5, i19};
  assign n2 = 16'h3eae >> {i20, i15, i20, i8};
  assign n3 = 16'hf2bc >> {i2, i6, i19, i5};
  assign n4 = 16'hc846 >> {i21, i10, i12, i18};
  assign n5 = 16'h62ac >> {n0, i12, i0, i1};
  assign n6 = 16'hb20d >> {i20, q3, q5, n1};
  assign n7 = 16'hb31c >> {i18, i13, i17, i19};
  assign n8 = 16'h2dcf >> {i10, i9, i10, i11};
  assign n9 = 16'hc55b >> {q7, n0, i17, n6};
  assign n10 = 16'hcb6a >> {i3, i7, i11, n6};
  assign n11 = 16'h32ed >> {i1, i16, i3, i15};
  assign n12 = 16'he19e >> {i21, i8, q5, i0};
  assign n13 = 16'hcf4d >> {i1, i16, n0, n12};
  assign n14 = 16'ha458 >> {i11, i11, n1, i1};
  assign n15 = 16'h7740 >> {i8, n9, i8, q5};
  assign n16 = 16'hc305 >> {i6, q5, n9, i13};
  assign n17 = 16'h123f >> {i14, i22, i16, q10};
  assign n18 = 16'h45cd >> {i22, i2, i17, n4};
  assign n19 = 16'h399c >> {n11, i5, i12, i9};
  assign n20 = 16'h387f >> {i5, i13, n17, i18};
  assign n21 = 16'h03d0 >> {i16, q14, n8, i6};
  assign n22 = 16'h7462 >> {i0, i14, i7, n20};
  assign n23 = 16'h354f >> {q7, q13, i6, n8};
  assign n24 = 16'hc626 >> {i8, i17, n19, q5};
  assign n25 = 16'hfad9 >> {i5, i13, i16, i18};
  assign n26 = 16'hcd49 >> {i16, n20, i3, i16};
  assign n27 = 16'h7a5e >> {q26, i21, i9, n11};
  assign n28 = 16'h0d0a >> {i8, n20, n27, n18};
  assign n29 = 16'hdad0 >> {i8, n18, n4, n16};
  assign n30 = 16'he641 >> {i5, n19, n11, n27};
  assign n31 = 16'h043a >> {n27, i20, n4, n20};
  assign n32 = 16'ha9c0 >> {n17, i4, q10, n17};
  assign n33 = 16'h7489 >> {i21, q28, i18, q14};
  assign n34 = 16'h6018 >> {i4, i1, q7, i12};
  assign n35 = 16'h4cb4 >> {q13, q24, q32, i12};
  assign n36 = 16'h6aa5 >> {q5, q5, i2, i19};
  assign n37 = 16'hd18d >> {q29, i5, i18, i0};
  assign n38 = 16'h5ef9 >> {q26, n34, q30, n37};
  assign n39 = 16'haed8 >> {n4, n8, n22, i7};
  assign n40 = 16'h5ff9 >> {i3, n15, i22, q26};
  assign n41 = 16'h3ea4 >> {n19, n11, q26, n18};
  assign n42 = 16'h7c14 >> {i16, n17, n40, i22};
  assign n43 = 16'h1540 >> {n21, n34, i20, i10};
  assign n44 = 16'h4955 >> {i0, n33, q10, q13};
  assign n45 = 16'h1767 >> {n37, n38, q13, i18};
  assign n46 = 16'ha321 >> {n17, n25, i20, n16};
  assign n47 = 16'hcff5 >> {i14, i11, n44, q32};
  assign n48 = 16'hb155 >> {q5, q39, q26, n6};
  assign n49 = 16'h08ed >> {n12, n46, n6, n38};
  assign n50 = 16'h2405 >> {n19, n11, n25, n34};
  assign n51 = 16'h182a >> {i19, n31, i5, i16};
  assign n52 = 16'h4435 >> {n6, n8, n8, q39};
  assign n53 = 16'ha96b >> {i21, q2, n1, n49};
  assign n54 = 16'h104a >> {n6, n12, n17, q14};
  assign n55 = 16'h2c74 >> {n35, n40, q14, q28};
  assign n56 = 16'h29f4 >> {n19, q30, n37, n18};
  assign n57 = 16'h62d0 >> {q23, n38, q26, n47};
  assign n58 = 16'h36ff >> {q29, i1, n16, q2};
  assign n59 = 16'hf6a9 >> {n37, n22, n0, q54};
  assign n60 = 16'h26a8 >> {n19, n46, q39, q23};
  assign n61 = 16'h38bb >> {n27, n37, n43, q29};
  assign n62 = 16'h634f >> {n59, n40, n25, q42};
  assign n63 = 16'h2750 >> {q5, q62, q14, q23};
  assign n64 = 16'h92a4 >> {n11, q54, q60, q51};
  assign n65 = 16'h8855 >> {q24, q24, q30, n17};
  assign n66 = 16'h18c7 >> {q36, n48, q39, n8};
  assign n67 = 16'h3514 >> {q13, n45, i22, n56};
  assign n68 = 16'he66d >> {n56, q28, n40, n9};
  assign n69 = 16'h4aa6 >> {q10, n67, n53, q29};
  assign n70 = 16'hcd67 >> {n47, n67, n31, n63};
  assign n71 = 16'hb357 >> {q24, q54, q55, q65};
  assign n72 = 16'habbe >> {n35, q28, q3, n61};
  assign n73 = 16'h85a6 >> {q32, n35, i8, n41};
  assign n74 = 16'hb539 >> {n21, q32, n44, n45};
  assign n75 = 16'hcc38 >> {q51, q32, q42, n48};
  assign n76 = 16'hdcb8 >> {n46, n31, n45, q57};
  always @(posedge clk0) begin if (i4) begin q2 <= n2; end end
  always @(posedge clk0) begin if (i11) q3 <= 1'b0; else q3 <= n3; end
  always @(posedge clk0) begin if (n4) begin q5 <= n5; end end
  always @(posedge clk0) begin if (i7) begin q7 <= n7; end end
  always @(posedge clk0 or posedge q2) begin if (q2) q10 <= 1'b0; else begin if (q3) q10 <= 1'b0; else q10 <= n10; end end
  always @(posedge clk0) begin if (n0) q13 <= i17; else q13 <= n13; end
  always @(posedge clk0) begin q14 <= n14; end
  always @(negedge clk0 or posedge q3) begin if (q3) q23 <= 1'b1; else begin q23 <= n23; end end
  always @(posedge clk0) begin if (i2) q24 <= i19; else q24 <= n24; end
  always @(posedge clk0) begin q26 <= n26; end
  always @(posedge clk0) begin q28 <= n28; end
  always @(posedge clk0) begin if (q26) q29 <= i12; else q29 <= n29; end
  always @(negedge clk0 or posedge i11) begin if (i11) q30 <= 1'b1; else begin if (n15) q30 <= i9; else q30 <= n30; end end
  always @(posedge clk0) begin if (i10) q32 <= 1'b0; else q32 <= n32; end
  always @(posedge clk0) begin if (q10) begin q36 <= n36; end end
  always @(posedge clk0 or posedge n25) begin if (n25) q39 <= 1'b1; else begin q39 <= n39; end end
  always @(negedge clk0) begin if (n41) q42 <= n41; else q42 <= n42; end
  always @(posedge clk0) begin if (n17) q51 <= 1'b0; else q51 <= n51; end
  always @(posedge clk0) begin q52 <= n52; end
  always @(negedge clk0 or posedge n47) begin if (n47) q54 <= 1'b1; else begin q54 <= n54; end end
  always @(posedge clk0 or posedge i5) begin if (i5) q55 <= 1'b0; else begin if (q3) q55 <= 1'b0; else if (i2) q55 <= q36; else q55 <= n55; end end
  always @(posedge clk0) begin if (i14) begin if (n25) q57 <= 1'b0; else if (q14) q57 <= n34; else q57 <= n57; end end
  always @(posedge clk0) begin if (n34) begin q60 <= n60; end end
  always @(posedge clk0) begin if (n53) q62 <= 1'b0; else q62 <= n62; end
  always @(posedge clk0) begin if (n27) begin if (i12) q65 <= 1'b0; else if (i11) q65 <= i5; else q65 <= n65; end end
  always @(posedge clk0) begin if (i3) begin q68 <= n68; end end
  always @(negedge clk0) begin if (n21) q70 <= 1'b0; else q70 <= n70; end
  always @(posedge clk0) begin q71 <= n71; end
  always @(posedge clk0) begin q73 <= n73; end
  always @(posedge clk0) begin q76 <= n76; end
  assign o0 = (^{n56, n43, q60, n61, n40, n59});
  assign o1 = (^{q26, n16, q57, q65, n58, n33});
  assign o2 = (^{n17, n53, n69, n49, n34, n72});
  assign o3 = ~(^{q39, n48, q23, n31, q14, n74});
  assign o4 = (^{n67, n15, n45, q54, q5, n6});
  assign o5 = (^{q73, n35, n0, n64, q7, n18});
  assign o6 = (^{n21, n20, n41, n46, q29, q28});
  assign o7 = (^{q55, n50, n38, n22, q30, q32});
  assign o8 = ~(^{n47, n66, n19, q2, q76, n1});
  assign o9 = (^{q36, q24, q51, n27, n12, q3});
  assign o10 = (^{q68, q52, q42, q13, q10, n63});
  assign o11 = (^{q71, n9, q62, n25, n8, n44});
  assign o12 = ~(^{n11, q70, n75, n37, n4});
endmodule
