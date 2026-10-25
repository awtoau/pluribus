module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10, output o11, output o12);
  wire n0;
  wire n1;
  wire n2;
  reg q2;
  wire n3;
  reg q3;
  wire n4;
  wire n5;
  wire n6;
  wire n7;
  reg q7;
  wire n8;
  reg q8;
  wire n9;
  wire n10;
  wire n11;
  reg q11;
  wire n12;
  wire n13;
  wire n14;
  wire n15;
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
  wire n23;
  wire n24;
  reg q24;
  wire n25;
  reg q25;
  wire n26;
  wire n27;
  wire n28;
  reg q28;
  wire n29;
  wire n30;
  wire n31;
  wire n32;
  wire n33;
  wire n34;
  wire n35;
  wire n36;
  reg q36;
  wire n37;
  wire n38;
  wire n39;
  wire n40;
  wire n41;
  reg q41;
  wire n42;
  reg q42;
  wire n43;
  reg q43;
  wire n44;
  wire n45;
  reg q45;
  wire n46;
  wire n47;
  wire n48;
  wire n49;
  wire n50;
  wire n51;
  wire n52;
  reg q52;
  wire n53;
  wire n54;
  wire n55;
  wire n56;
  wire n57;
  reg q57;
  wire n58;
  reg q58;
  wire n59;
  reg q59;
  wire n60;
  wire n61;
  wire n62;
  wire n63;
  reg q63;
  assign n0 = 16'hb55a >> {i12, i13, i10, i11};
  assign n1 = 16'h9a07 >> {i1, i3, i15, i17};
  assign n2 = 16'h72b4 >> {n0, i3, i2, n0};
  assign n3 = 16'he792 >> {i16, i4, i15, i13};
  assign n4 = 16'hd2f1 >> {q3, i0, i8, n0};
  assign n5 = 16'h36e8 >> {i12, n1, i7, q2};
  assign n6 = 16'hc286 >> {i8, n0, n0, i9};
  assign n7 = 16'h09fe >> {n6, i7, i7, i2};
  assign n8 = 16'hf074 >> {i6, i5, i5, i8};
  assign n9 = 16'h66a9 >> {i13, i9, i8, i12};
  assign n10 = 16'hc345 >> {n9, i13, i17, i12};
  assign n11 = 16'ha043 >> {i6, i11, q7, n5};
  assign n12 = 16'h06b8 >> {n1, i1, i15, n0};
  assign n13 = 16'hd95e >> {i16, q3, i1, q7};
  assign n14 = 16'h3793 >> {n5, i17, i6, i10};
  assign n15 = 16'hf55c >> {i16, n6, i7, i0};
  assign n16 = 16'h60ab >> {i17, i4, n14, n15};
  assign n17 = 16'he38b >> {i9, n14, n4, i11};
  assign n18 = 16'hcce2 >> {i0, i7, n4, i2};
  assign n19 = 16'hd614 >> {n13, i15, i3, q3};
  assign n20 = 16'h4cc2 >> {n12, i2, q8, i6};
  assign n21 = 16'hd1b5 >> {n9, i5, i12, n14};
  assign n22 = 16'h6705 >> {i5, q19, i8, i14};
  assign n23 = 16'h7a4b >> {n0, q19, i5, i16};
  assign n24 = 16'h2cb1 >> {n1, n23, i8, q18};
  assign n25 = 16'h6527 >> {q20, n10, n13, n6};
  assign n26 = 16'h66c8 >> {i2, i1, i5, i2};
  assign n27 = 16'hbf6d >> {i5, n4, q11, i11};
  assign n28 = 16'h173c >> {i9, q18, n13, n27};
  assign n29 = 16'h5453 >> {i14, q7, n5, i6};
  assign n30 = 16'hdfa1 >> {i17, n22, n4, q11};
  assign n31 = 16'h6429 >> {i16, i11, n13, n9};
  assign n32 = 16'h8069 >> {n13, n31, n0, i17};
  assign n33 = 16'hc20d >> {n30, i14, i5, q19};
  assign n34 = 16'hb393 >> {i11, n15, n13, q19};
  assign n35 = 16'h3fa8 >> {n5, n0, n12, i1};
  assign n36 = 16'h6a46 >> {i2, i5, i15, q21};
  assign n37 = 16'hbfc5 >> {i0, q18, q36, n26};
  assign n38 = 16'h33bc >> {i4, q11, n30, n12};
  assign n39 = 16'h1718 >> {i7, n4, i5, n14};
  assign n40 = 16'hb12c >> {q19, q8, q28, n13};
  assign n41 = 16'ha480 >> {n26, n9, q7, n14};
  assign n42 = 16'h381c >> {n13, n17, n30, q36};
  assign n43 = 16'ha741 >> {n23, q19, n9, n26};
  assign n44 = 16'h3a45 >> {q18, q2, i7, n6};
  assign n45 = 16'h55e8 >> {n15, i9, n13, q3};
  assign n46 = 16'h41b4 >> {n15, q3, q11, n30};
  assign n47 = 16'hd63a >> {i11, n27, i15, i7};
  assign n48 = 16'hdb0c >> {n26, n12, n16, i7};
  assign n49 = 16'h73ca >> {n5, n17, i15, n39};
  assign n50 = 16'h1c3b >> {n10, n33, q8, i16};
  assign n51 = 16'h0970 >> {n27, n10, q41, n13};
  assign n52 = 16'h4ad0 >> {n22, q7, q7, q19};
  assign n53 = 16'h2984 >> {n35, n44, i11, q2};
  assign n54 = 16'h014d >> {i2, n13, q43, n15};
  assign n55 = 16'h01b6 >> {n39, n49, q43, n22};
  assign n56 = 16'hf184 >> {n34, q2, n54, n30};
  assign n57 = 16'hff01 >> {n50, q28, n23, n53};
  assign n58 = 16'h9272 >> {n16, q28, n34, n35};
  assign n59 = 16'hd8b4 >> {q45, n55, n5, q42};
  assign n60 = 16'h008f >> {q8, n33, q20, n32};
  assign n61 = 16'h6732 >> {q59, n34, q42, n6};
  assign n62 = 16'hc68a >> {n37, n50, q8, n46};
  assign n63 = 16'h21a7 >> {n23, n51, n46, n27};
  always @(posedge clk1) begin q2 <= n2; end
  always @(posedge clk0 or posedge n0) begin if (n0) q3 <= 1'b1; else begin if (i5) begin if (i1) q3 <= i1; else q3 <= n3; end end end
  always @(posedge clk1) begin if (i5) q7 <= i4; else q7 <= n7; end
  always @(posedge clk1) begin q8 <= n8; end
  always @(posedge clk0) begin q11 <= n11; end
  always @(posedge clk0) begin if (q7) q18 <= 1'b0; else if (n6) q18 <= i14; else q18 <= n18; end
  always @(posedge clk0) begin q19 <= n19; end
  always @(posedge clk0) begin if (i13) begin q20 <= n20; end end
  always @(posedge clk0) begin if (n0) begin q21 <= n21; end end
  always @(posedge clk1) begin if (i9) begin if (q2) q24 <= 1'b0; else q24 <= n24; end end
  always @(posedge clk0 or posedge q7) begin if (q7) q25 <= 1'b0; else begin if (q7) q25 <= 1'b0; else q25 <= n25; end end
  always @(posedge clk0) begin if (q24) begin q28 <= n28; end end
  always @(posedge clk1 or posedge n35) begin if (n35) q36 <= 1'b1; else begin if (n27) begin q36 <= n36; end end end
  always @(posedge clk1 or posedge n17) begin if (n17) q41 <= 1'b1; else begin if (n29) q41 <= n30; else q41 <= n41; end end
  always @(posedge clk1) begin q42 <= n42; end
  always @(posedge clk0) begin if (i4) begin q43 <= n43; end end
  always @(posedge clk1) begin q45 <= n45; end
  always @(posedge clk0) begin q52 <= n52; end
  always @(posedge clk0) begin if (q11) begin q57 <= n57; end end
  always @(posedge clk1 or posedge i17) begin if (i17) q58 <= 1'b0; else begin q58 <= n58; end end
  always @(posedge clk1) begin if (i10) begin q59 <= n59; end end
  always @(posedge clk0 or posedge n49) begin if (n49) q63 <= 1'b1; else begin if (q41) q63 <= 1'b0; else q63 <= n63; end end
  assign o0 = ~(^{q45, n55, n60, n32, n35});
  assign o1 = (^{q11, n31, q63, n56, q20});
  assign o2 = (^{q52, n62, q3, n46, n50});
  assign o3 = (^{n14, n47, q43, q7, n15});
  assign o4 = (^{n40, q25, q21, n22, n13});
  assign o5 = (^{n51, n12, n1, n54, n38});
  assign o6 = (^{n0, n4, q24, q58, n16});
  assign o7 = ~(^{n34, n53, n33, n26, q59});
  assign o8 = ~(^{n17, n9, n48, n49, q19});
  assign o9 = (^{n44, n37, n23, q2, n27});
  assign o10 = (^{q41, n30, q42, q36, n10});
  assign o11 = (^{q18, n29, n5, n39, q8});
  assign o12 = (^{q57, q28, n6, n61});
endmodule
