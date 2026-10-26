module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9);
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
  wire n8;
  reg q8;
  wire n9;
  wire n10;
  wire n11;
  wire n12;
  wire n13;
  wire n14;
  reg q14;
  wire n15;
  wire n16;
  wire n17;
  reg q17;
  wire n18;
  wire n19;
  reg q19;
  wire n20;
  wire n21;
  reg q21;
  wire n22;
  reg q22;
  wire n23;
  reg q23;
  wire n24;
  wire n25;
  wire n26;
  reg q26;
  wire n27;
  reg q27;
  wire n28;
  wire n29;
  wire n30;
  reg q30;
  wire n31;
  wire n32;
  wire n33;
  wire n34;
  wire n35;
  reg q35;
  wire n36;
  reg q36;
  wire n37;
  wire n38;
  reg q38;
  wire n39;
  wire n40;
  reg q40;
  wire n41;
  wire n42;
  reg q42;
  wire n43;
  wire n44;
  reg q44;
  wire n45;
  reg q45;
  wire n46;
  wire n47;
  reg q47;
  wire n48;
  wire n49;
  wire n50;
  wire n51;
  wire n52;
  reg q52;
  wire n53;
  wire n54;
  reg q54;
  wire n55;
  wire n56;
  wire n57;
  wire n58;
  reg q58;
  wire n59;
  wire n60;
  wire n61;
  wire n62;
  wire n63;
  wire n64;
  wire n65;
  wire n66;
  wire n67;
  wire n68;
  wire n69;
  reg q69;
  wire n70;
  wire n71;
  wire n72;
  wire n73;
  wire n74;
  wire n75;
  wire n76;
  reg q76;
  wire n77;
  wire n78;
  wire n79;
  wire n80;
  reg q80;
  wire n81;
  reg q81;
  wire n82;
  wire n83;
  wire n84;
  reg q84;
  wire n85;
  reg q85;
  wire n86;
  wire n87;
  wire n88;
  wire n89;
  reg q89;
  wire n90;
  reg q90;
  wire n91;
  reg q91;
  wire n92;
  wire n93;
  reg q93;
  wire n94;
  wire n95;
  wire n96;
  reg q96;
  wire n97;
  wire n98;
  reg q98;
  wire n99;
  wire n100;
  wire n101;
  wire n102;
  reg q102;
  wire n103;
  assign n0 = 16'h8a32 >> {i7, i4, i6, i3};
  assign n1 = 16'h792c >> {i4, i0, i2, i5};
  assign n2 = 16'hd38f >> {n0, i5, i0, n1};
  assign n3 = 16'hfd00 >> {q2, i3, i1, i5};
  assign n4 = 16'h1af4 >> {i0, i5, i5, i5};
  assign n5 = 16'h28f4 >> {i4, i0, i4, i6};
  assign n6 = 16'h595c >> {i1, i0, n4, i3};
  assign n7 = 16'h783b >> {i3, q3, i4, q3};
  assign n8 = 16'h262d >> {i5, i3, n7, i5};
  assign n9 = 16'h91a9 >> {i0, q8, i7, i4};
  assign n10 = 16'h1fd6 >> {n1, q8, i6, n9};
  assign n11 = 16'he158 >> {n0, n5, q3, n10};
  assign n12 = 16'h8f72 >> {i2, i1, i0, n6};
  assign n13 = 16'h9405 >> {q2, i4, n11, n12};
  assign n14 = 16'h7b94 >> {i1, i0, q3, n5};
  assign n15 = 16'he990 >> {n4, n5, n11, n0};
  assign n16 = 16'h5d8e >> {i2, i7, i1, n9};
  assign n17 = 16'hda3b >> {n13, q2, n5, n15};
  assign n18 = 16'h72d7 >> {n13, i6, n15, n1};
  assign n19 = 16'h5af8 >> {n16, n1, i6, n13};
  assign n20 = 16'hc618 >> {i4, n1, n15, i6};
  assign n21 = 16'hd432 >> {n1, n11, n18, i7};
  assign n22 = 16'hb588 >> {n6, n10, q21, i4};
  assign n23 = 16'h3a11 >> {n11, n1, q3, i5};
  assign n24 = 16'h5283 >> {q2, q21, n5, n1};
  assign n25 = 16'h1206 >> {i5, n4, q17, n5};
  assign n26 = 16'hb996 >> {i2, n6, q21, q3};
  assign n27 = 16'hc21a >> {i7, q17, n11, n5};
  assign n28 = 16'h61e0 >> {i5, q22, n15, n13};
  assign n29 = 16'hf822 >> {n24, q2, n24, i7};
  assign n30 = 16'h9575 >> {n15, n16, q19, n12};
  assign n31 = 16'h1696 >> {q2, q3, i4, q23};
  assign n32 = 16'h0f19 >> {q22, i3, q2, q8};
  assign n33 = 16'h3117 >> {n7, n13, n25, n15};
  assign n34 = 16'hdfa2 >> {n24, q2, q19, i4};
  assign n35 = 16'hdd4e >> {n24, q27, q8, n29};
  assign n36 = 16'h19dd >> {n28, i2, q23, i6};
  assign n37 = 16'h0861 >> {q36, q35, i2, n0};
  assign n38 = 16'h52a6 >> {n18, n10, i7, q21};
  assign n39 = 16'h94e7 >> {n34, n25, i6, q26};
  assign n40 = 16'h0ac7 >> {n39, i4, q38, n32};
  assign n41 = 16'hc432 >> {n4, n33, q26, n34};
  assign n42 = 16'h3799 >> {n31, q14, q3, q35};
  assign n43 = 16'h9bdc >> {n4, n13, n13, n28};
  assign n44 = 16'h3221 >> {q26, q14, q42, i0};
  assign n45 = 16'h2af1 >> {q44, i1, q22, n34};
  assign n46 = 16'hf8be >> {n12, q22, n33, q14};
  assign n47 = 16'hf5d9 >> {i0, n29, q35, i7};
  assign n48 = 16'hac99 >> {i4, n5, n9, q26};
  assign n49 = 16'h22d4 >> {n16, q30, q21, q42};
  assign n50 = 16'hc554 >> {n32, n29, q22, n34};
  assign n51 = 16'h1c0f >> {i4, n10, n48, i1};
  assign n52 = 16'h876f >> {q26, i7, q26, i1};
  assign n53 = 16'hff46 >> {q22, q22, q52, n20};
  assign n54 = 16'hef8f >> {n12, i5, n16, q44};
  assign n55 = 16'hed6a >> {q23, n24, n32, n53};
  assign n56 = 16'h4d2f >> {q40, n4, n31, q19};
  assign n57 = 16'h6fdd >> {n11, q40, n11, q40};
  assign n58 = 16'hf0d3 >> {n41, n33, n28, n13};
  assign n59 = 16'h5482 >> {n15, q52, n0, q44};
  assign n60 = 16'h5e27 >> {n9, n12, n1, q35};
  assign n61 = 16'h5d17 >> {n28, n24, q19, n56};
  assign n62 = 16'h0a2e >> {n61, n48, q45, q21};
  assign n63 = 16'h6541 >> {n10, n48, n51, n7};
  assign n64 = 16'hd39b >> {n43, q40, q22, n33};
  assign n65 = 16'h9871 >> {q2, q21, q36, n37};
  assign n66 = 16'he371 >> {q40, n9, q21, n61};
  assign n67 = 16'h9ee4 >> {n28, n55, n60, n46};
  assign n68 = 16'h8246 >> {n34, q52, q52, n67};
  assign n69 = 16'h8d24 >> {n16, q26, q44, n13};
  assign n70 = 16'hbcbe >> {i0, n18, n57, n31};
  assign n71 = 16'h4ebb >> {n51, n43, q27, n24};
  assign n72 = 16'h3866 >> {n46, n48, n18, q54};
  assign n73 = 16'hbd45 >> {n72, q14, q26, n51};
  assign n74 = 16'h6c89 >> {n10, q40, n66, q22};
  assign n75 = 16'h09d0 >> {n46, n43, n33, n56};
  assign n76 = 16'h54fb >> {n74, q21, q35, n34};
  assign n77 = 16'h54ca >> {n62, n11, n70, n31};
  assign n78 = 16'h367d >> {n37, n25, n31, q44};
  assign n79 = 16'he71a >> {q21, n59, n10, n56};
  assign n80 = 16'he425 >> {n5, q27, n41, q58};
  assign n81 = 16'h4c1b >> {n68, n68, n48, n56};
  assign n82 = 16'h0cde >> {q81, n24, n31, n56};
  assign n83 = 16'hd355 >> {q38, n43, n68, q47};
  assign n84 = 16'hd937 >> {n51, n57, q27, n24};
  assign n85 = 16'h6a2e >> {n82, q80, q27, q35};
  assign n86 = 16'h8f8a >> {n75, n12, n71, n63};
  assign n87 = 16'hf957 >> {n34, n5, q76, n61};
  assign n88 = 16'h2470 >> {q84, n82, q85, n39};
  assign n89 = 16'hd431 >> {n87, q38, n34, n68};
  assign n90 = 16'h9607 >> {n86, n86, n73, q85};
  assign n91 = 16'heaac >> {q89, n83, q69, n49};
  assign n92 = 16'h10af >> {n62, n50, q58, n61};
  assign n93 = 16'heff3 >> {q90, q47, q90, n77};
  assign n94 = 16'hc8e9 >> {q54, q81, n82, n61};
  assign n95 = 16'h87ff >> {n46, n49, n64, n92};
  assign n96 = 16'h6896 >> {n18, n56, n74, q36};
  assign n97 = 16'hcd83 >> {n55, q85, q80, n41};
  assign n98 = 16'h04d7 >> {n72, n68, n48, n24};
  assign n99 = 16'h65c4 >> {n56, n87, n55, n46};
  assign n100 = 16'h98fc >> {q58, q47, q76, q84};
  assign n101 = 16'h0528 >> {n68, n64, n88, n56};
  assign n102 = 16'h4032 >> {n53, n50, n15, n75};
  assign n103 = 16'hf1c9 >> {n53, n59, n68, q81};
  always @(posedge clk0) begin if (i0) q2 <= n0; else q2 <= n2; end
  always @(posedge clk0) begin if (q2) begin q3 <= n3; end end
  always @(posedge clk0) begin if (q3) q8 <= 1'b0; else q8 <= n8; end
  always @(posedge clk0) begin q14 <= n14; end
  always @(negedge clk0) begin if (n6) q17 <= i2; else q17 <= n17; end
  always @(posedge clk0 or posedge i4) begin if (i4) q19 <= 1'b1; else begin q19 <= n19; end end
  always @(posedge clk0) begin if (q17) begin q21 <= n21; end end
  always @(posedge clk0) begin if (i6) q22 <= i4; else q22 <= n22; end
  always @(posedge clk0) begin if (i2) begin if (n9) q23 <= i1; else q23 <= n23; end end
  always @(negedge clk0 or posedge q14) begin if (q14) q26 <= 1'b1; else begin if (i5) begin q26 <= n26; end end end
  always @(posedge clk0) begin q27 <= n27; end
  always @(posedge clk0) begin q30 <= n30; end
  always @(posedge clk0) begin if (n20) q35 <= i4; else q35 <= n35; end
  always @(posedge clk0 or posedge i7) begin if (i7) q36 <= 1'b1; else begin if (q2) q36 <= 1'b0; else if (i3) q36 <= q35; else q36 <= n36; end end
  always @(posedge clk0) begin if (q27) begin q38 <= n38; end end
  always @(posedge clk0 or posedge n24) begin if (n24) q40 <= 1'b1; else begin if (i5) begin q40 <= n40; end end end
  always @(posedge clk0) begin if (n5) begin if (q19) q42 <= 1'b0; else q42 <= n42; end end
  always @(posedge clk0) begin if (q17) q44 <= 1'b0; else q44 <= n44; end
  always @(posedge clk0) begin if (q23) begin q45 <= n45; end end
  always @(posedge clk0) begin if (q17) begin q47 <= n47; end end
  always @(posedge clk0 or posedge q3) begin if (q3) q52 <= 1'b0; else begin if (q2) q52 <= q47; else q52 <= n52; end end
  always @(posedge clk0) begin if (q22) begin q54 <= n54; end end
  always @(posedge clk0) begin q58 <= n58; end
  always @(posedge clk0 or posedge n9) begin if (n9) q69 <= 1'b0; else begin if (q52) q69 <= i4; else q69 <= n69; end end
  always @(posedge clk0) begin if (n46) q76 <= n1; else q76 <= n76; end
  always @(posedge clk0) begin q80 <= n80; end
  always @(posedge clk0) begin if (n5) begin q81 <= n81; end end
  always @(posedge clk0 or posedge i2) begin if (i2) q84 <= 1'b1; else begin if (n48) begin q84 <= n84; end end end
  always @(posedge clk0) begin if (n12) begin q85 <= n85; end end
  always @(posedge clk0) begin q89 <= n89; end
  always @(posedge clk0) begin if (n60) begin if (n20) q90 <= 1'b0; else if (q85) q90 <= q89; else q90 <= n90; end end
  always @(posedge clk0) begin if (n15) q91 <= 1'b0; else q91 <= n91; end
  always @(posedge clk0 or posedge q52) begin if (q52) q93 <= 1'b0; else begin q93 <= n93; end end
  always @(posedge clk0) begin if (n32) begin if (n87) q96 <= 1'b0; else q96 <= n96; end end
  always @(negedge clk0) begin if (n60) begin q98 <= n98; end end
  always @(posedge clk0) begin if (q8) q102 <= 1'b0; else q102 <= n102; end
  assign o0 = (^{n34, q80, q8, n94, q58, q96, n41, q52, q54, q17, n9});
  assign o1 = (^{n59, q81, n75, q69, n97, n74, n73, n32, q90, n55, n82});
  assign o2 = (^{n18, n53, q89, q40, n92, n78, n67, n77, q38, n37, q102});
  assign o3 = (^{n20, n12, n46, n60, q3, n49, n61, q98, q35, q22, n83});
  assign o4 = (^{n4, q26, n51, n24, n57, n65, q2, q45, n31, n0});
  assign o5 = ~(^{n87, n16, n70, q76, n50, n99, n10, q19, n100, q30});
  assign o6 = (^{q21, n66, n13, n33, n86, n71, n39, q27, n103, n62});
  assign o7 = (^{n95, n88, n29, n56, n72, n6, n79, q84, n63, q42});
  assign o8 = (^{q23, q91, n15, q44, n101, n64, n68, q14, n7, q36});
  assign o9 = (^{n25, q85, n28, n5, q93, n43, n48, n11, n1, q47});
endmodule
