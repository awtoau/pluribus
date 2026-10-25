module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10, output o11, output o12);
  wire n0;
  wire n1;
  reg q1;
  wire n2;
  wire n3;
  reg q3;
  wire n4;
  reg q4;
  wire n5;
  reg q5;
  wire n6;
  wire n7;
  reg q7;
  wire n8;
  wire n9;
  wire n10;
  wire n11;
  wire n12;
  wire n13;
  wire n14;
  reg q14;
  wire n15;
  wire n16;
  reg q16;
  wire n17;
  wire n18;
  reg q18;
  wire n19;
  wire [12:0] s0;
  wire n21;
  reg q21;
  wire n22;
  wire n23;
  reg q23;
  wire n24;
  wire n25;
  reg q25;
  wire n26;
  reg q26;
  wire n27;
  wire n28;
  reg q28;
  wire n29;
  wire n30;
  reg q30;
  wire n31;
  wire n32;
  wire n33;
  wire n34;
  reg q34;
  wire n35;
  wire n36;
  reg q36;
  wire n37;
  wire n38;
  wire n39;
  reg q39;
  wire [8:0] s1;
  wire [8:0] s2;
  wire n42;
  wire n43;
  reg q43;
  wire n44;
  wire n45;
  wire n46;
  reg q46;
  wire n47;
  wire n48;
  reg q48;
  wire n49;
  wire n50;
  reg q50;
  wire n51;
  reg q51;
  wire n52;
  reg q52;
  wire n53;
  reg q53;
  wire n54;
  wire n55;
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
  wire n66;
  reg q66;
  wire n67;
  reg q67;
  wire n68;
  wire n69;
  wire [4:0] s3;
  wire [10:0] s4;
  wire n72;
  wire [12:0] s5;
  wire n74;
  reg q74;
  wire n75;
  wire n76;
  wire n77;
  wire n78;
  wire n79;
  reg q79;
  wire n80;
  wire n81;
  wire n82;
  wire [12:0] s6;
  wire n84;
  reg q84;
  wire n85;
  wire n86;
  wire n87;
  wire n88;
  reg q88;
  wire n89;
  wire n90;
  wire n91;
  reg q91;
  wire n92;
  reg q92;
  wire n93;
  wire n94;
  reg q94;
  wire n95;
  wire n96;
  wire n97;
  reg q97;
  wire n98;
  wire n99;
  wire n100;
  wire n101;
  wire n102;
  reg q102;
  wire n103;
  wire n104;
  wire n105;
  reg q105;
  wire n106;
  assign n0 = 16'hdc23 >> {i1, i3, i5, i2};
  assign n1 = 16'hb0e3 >> {i7, i0, i5, n0};
  assign n2 = 16'hf51a >> {q1, i6, n0, i1};
  assign n3 = 16'h7984 >> {i6, i3, i6, n0};
  assign n4 = 16'h48af >> {i7, i1, i7, i5};
  assign n5 = 16'h7c87 >> {i0, n2, i2, i2};
  assign n6 = 16'hec0b >> {q1, i4, i1, i0};
  assign n7 = 16'he707 >> {i5, n0, i1, q4};
  assign n8 = 16'h1fb1 >> {q5, i5, q4, q4};
  assign n9 = 16'h49d0 >> {n6, n6, i6, q7};
  assign n10 = 16'h76f5 >> {i3, i3, n8, n9};
  assign n11 = 16'hea04 >> {q7, q5, n2, q5};
  assign n12 = 16'hf2ec >> {q1, n2, i5, n2};
  assign n13 = 16'h172f >> {n8, i5, i3, i2};
  assign n14 = 16'h6e33 >> {i6, n11, q3, n2};
  assign n15 = 16'hddd3 >> {i3, n10, i0, n9};
  assign n16 = 16'h2609 >> {i1, n13, i0, q7};
  assign n17 = 16'h1be6 >> {n15, q16, n0, q7};
  assign n18 = 16'h9bbc >> {n13, n10, n6, n8};
  assign n19 = 16'h1a8d >> {q16, i5, i5, i7};
  assign s0 = {1'b0, i3, n11, n13, q5, n13, n15, n13, n2, n13, q5, i4, i1} + {1'b0, i1, q5, n6, i1, q14, i2, n8, i4, q18, n10, n17, n11};
  assign n21 = 16'h2c11 >> {n8, s0[5], q5, n17};
  assign n22 = 16'hcc72 >> {s0[6], q21, i3, s0[8]};
  assign n23 = 16'h52ff >> {n8, i6, i3, i5};
  assign n24 = 16'h8afb >> {n2, n12, q18, s0[4]};
  assign n25 = 16'hddae >> {n9, n2, s0[12], n6};
  assign n26 = 16'h0d7f >> {q3, n17, s0[12], q25};
  assign n27 = 16'hea83 >> {s0[5], i6, q18, q18};
  assign n28 = 16'hfc0f >> {q1, n27, n15, q18};
  assign n29 = 16'hcd68 >> {i6, n9, n19, s0[0]};
  assign n30 = 16'h4318 >> {n19, q1, n8, i6};
  assign n31 = 16'h2cb2 >> {n24, s0[7], s0[6], q3};
  assign n32 = 16'hf118 >> {s0[2], n13, i0, i7};
  assign n33 = 16'h0271 >> {q21, q16, n9, i4};
  assign n34 = 16'h11a8 >> {q1, q18, s0[3], n12};
  assign n35 = 16'h90a4 >> {n17, n27, n2, n9};
  assign n36 = 16'hc394 >> {q7, i4, n22, s0[1]};
  assign n37 = 16'h0e93 >> {n6, n19, q5, s0[9]};
  assign n38 = 16'h9f76 >> {n17, n2, n29, q25};
  assign n39 = 16'hb20c >> {n27, q3, n22, q34};
  assign s1 = {1'b0, s0[8], i4, s0[5], s0[11], s0[7], i6, q28, n31} - {1'b0, s0[7], n10, n37, q5, i4, s0[2], q30, i0};
  assign s2 = {1'b0, n31, n8, q16, s1[8], q14, q18, i0, s0[10]} - {1'b0, n6, s1[6], n29, i2, s0[9], s0[0], q5, q14};
  assign n42 = 16'h38bb >> {s0[1], s0[4], n35, q14};
  assign n43 = 16'hb7d0 >> {n33, s1[1], s2[3], s0[7]};
  assign n44 = 16'h0d91 >> {s2[1], s0[6], n33, n27};
  assign n45 = 16'h0272 >> {q26, n22, n15, n44};
  assign n46 = 16'h70b4 >> {n33, n17, q25, n15};
  assign n47 = 16'h997f >> {s1[4], s1[6], q23, s2[2]};
  assign n48 = 16'h5edd >> {n38, q18, q34, s0[11]};
  assign n49 = 16'hf473 >> {n24, s2[6], q4, s1[3]};
  assign n50 = 16'h4989 >> {s2[3], s1[7], q3, q43};
  assign n51 = 16'h436c >> {n38, q50, s0[9], n24};
  assign n52 = 16'h5c76 >> {n24, s0[9], n33, q21};
  assign n53 = 16'hceb4 >> {s1[7], s2[6], q52, s1[0]};
  assign n54 = 16'h2dd9 >> {s0[3], s0[10], s1[4], q21};
  assign n55 = 16'hd108 >> {s1[5], q21, s2[0], s2[8]};
  assign n56 = 16'h88cb >> {s2[4], s2[4], s2[7], q50};
  assign n57 = 16'h915e >> {q39, n35, s2[0], n49};
  assign n58 = 16'hca6d >> {q34, n32, s0[7], q18};
  assign n59 = 16'hd2ae >> {n45, q57, n45, s1[2]};
  assign n60 = 16'h9f18 >> {s2[6], q28, q46, q57};
  assign n61 = 16'hf707 >> {q23, q30, s1[7], q46};
  assign n62 = 16'h5280 >> {n56, q39, s0[10], s2[3]};
  assign n63 = 16'h56a6 >> {n38, n61, n38, n44};
  assign n64 = 16'h9f7a >> {n63, q48, n22, q30};
  assign n65 = 16'hcb8e >> {q53, s2[1], n32, n64};
  assign n66 = 16'hbef9 >> {s1[6], s2[8], s2[8], q51};
  assign n67 = 16'hdf3e >> {q50, s2[0], s2[8], q48};
  assign n68 = 16'h317b >> {q25, n44, n33, s2[8]};
  assign n69 = 16'he660 >> {n29, n45, n68, n63};
  assign s3 = {1'b0, n17, s0[1], q25, s1[4]} - {1'b0, i6, q67, s1[5], s0[0]};
  assign s4 = {1'b0, s1[5], s1[4], i2, s0[3], n65, n27, q26, s1[5], i5, q53} - {1'b0, q52, n38, s0[2], s0[3], n29, n68, n68, q51, n0, n56};
  assign n72 = 16'h63a6 >> {s1[3], n45, s2[8], s4[8]};
  assign s5 = {1'b0, q25, n31, q16, s4[3], q25, s4[0], q21, s4[3], q34, q57, n15, s2[2]} - {1'b0, n10, q16, q48, s2[4], q5, q28, i7, s0[10], q53, n24, s4[9], n55};
  assign n74 = 16'h9a29 >> {q62, s0[3], q50, q51};
  assign n75 = 16'h190f >> {q48, n44, s5[0], s5[1]};
  assign n76 = 16'hb627 >> {n61, q66, s3[3], s5[1]};
  assign n77 = 16'hff43 >> {s4[7], s4[5], s4[8], s3[1]};
  assign n78 = 16'hbbad >> {s4[2], n68, s5[6], s5[9]};
  assign n79 = 16'h12d7 >> {s4[10], n75, q57, n77};
  assign n80 = 16'h9e5a >> {n54, q79, n63, q62};
  assign n81 = 16'h8977 >> {i1, q3, n72, s4[9]};
  assign n82 = 16'h80a9 >> {s4[8], n61, n56, n77};
  assign s6 = {1'b0, q28, n45, s2[1], n55, s4[1], q53, s5[2], s5[7], s0[1], s4[5], s5[6], q43} + {1'b0, n37, s5[9], i3, s2[4], s4[1], n44, q67, s4[0], s2[0], q5, s4[2], s3[3]};
  assign n84 = 16'h25c1 >> {s3[4], q62, s5[9], s6[4]};
  assign n85 = 16'h6097 >> {n35, s6[2], s4[7], q67};
  assign n86 = 16'he649 >> {q79, s6[12], s3[0], s5[7]};
  assign n87 = 16'h8d94 >> {s6[1], s6[0], n69, q23};
  assign n88 = 16'h403b >> {n69, q74, s5[6], s4[6]};
  assign n89 = 16'hc2af >> {q84, s5[1], s3[4], s6[11]};
  assign n90 = 16'hecd0 >> {s5[6], s6[12], q88, n85};
  assign n91 = 16'h51be >> {s6[4], s3[4], s6[12], s6[5]};
  assign n92 = 16'h3c09 >> {s6[3], s5[3], s6[3], s4[9]};
  assign n93 = 16'h134c >> {n80, s4[0], s5[0], n87};
  assign n94 = 16'hf059 >> {s6[11], s4[9], s5[8], s4[1]};
  assign n95 = 16'h9e2f >> {s4[5], n89, q79, s4[8]};
  assign n96 = 16'h74d4 >> {i0, n22, s4[10], s4[9]};
  assign n97 = 16'h30e5 >> {n82, s5[5], s5[3], s4[5]};
  assign n98 = 16'he947 >> {n93, q74, n81, s5[11]};
  assign n99 = 16'he4b1 >> {s5[6], n96, s4[5], s5[5]};
  assign n100 = 16'h77f5 >> {s4[9], s5[7], s5[1], s5[9]};
  assign n101 = 16'h6493 >> {q84, s6[11], s5[8], s6[2]};
  assign n102 = 16'h53dc >> {s6[6], s6[11], s5[5], s4[10]};
  assign n103 = 16'h5da7 >> {n99, s4[8], s6[2], s5[2]};
  assign n104 = 16'hf2ba >> {s6[6], q16, s5[6], n80};
  assign n105 = 16'h88e1 >> {n72, s2[2], q91, n101};
  assign n106 = 16'h4d69 >> {q94, n100, n103, s5[4]};
  always @(posedge clk0) begin if (i7) q1 <= 1'b0; else q1 <= n1; end
  always @(posedge clk0 or posedge i0) begin if (i0) q3 <= 1'b1; else begin if (i1) q3 <= i3; else q3 <= n3; end end
  always @(posedge clk0 or posedge i2) begin if (i2) q4 <= 1'b0; else begin q4 <= n4; end end
  always @(posedge clk0 or posedge i6) begin if (i6) q5 <= 1'b0; else begin if (i7) begin if (q4) q5 <= 1'b0; else q5 <= n5; end end end
  always @(posedge clk0 or posedge i4) begin if (i4) q7 <= 1'b0; else begin if (i6) begin if (i3) q7 <= 1'b0; else q7 <= n7; end end end
  always @(posedge clk0 or posedge q1) begin if (q1) q14 <= 1'b1; else begin if (n8) begin if (i0) q14 <= q4; else q14 <= n14; end end end
  always @(posedge clk0 or posedge i6) begin if (i6) q16 <= 1'b1; else begin if (n6) q16 <= 1'b0; else q16 <= n16; end end
  always @(negedge clk0) begin if (n17) q18 <= 1'b0; else if (n9) q18 <= n9; else q18 <= n18; end
  always @(posedge clk0) begin q21 <= n21; end
  always @(posedge clk0 or posedge n15) begin if (n15) q23 <= 1'b1; else begin if (s0[6]) q23 <= i6; else q23 <= n23; end end
  always @(posedge clk0) begin if (n2) begin if (s0[8]) q25 <= s0[3]; else q25 <= n25; end end
  always @(posedge clk0 or posedge s0[10]) begin if (s0[10]) q26 <= 1'b0; else begin if (n11) begin q26 <= n26; end end end
  always @(posedge clk0) begin if (q7) q28 <= 1'b0; else if (n0) q28 <= s0[2]; else q28 <= n28; end
  always @(posedge clk0) begin if (s0[12]) begin q30 <= n30; end end
  always @(posedge clk0) begin q34 <= n34; end
  always @(negedge clk0) begin if (q23) q36 <= 1'b0; else q36 <= n36; end
  always @(posedge clk0 or posedge i1) begin if (i1) q39 <= 1'b1; else begin q39 <= n39; end end
  always @(posedge clk0) begin if (s2[3]) q43 <= 1'b0; else q43 <= n43; end
  always @(posedge clk0 or posedge q14) begin if (q14) q46 <= 1'b0; else begin if (q39) begin if (q5) q46 <= s1[2]; else q46 <= n46; end end end
  always @(posedge clk0) begin if (s2[8]) q48 <= 1'b0; else q48 <= n48; end
  always @(posedge clk0 or posedge n38) begin if (n38) q50 <= 1'b1; else begin if (s0[1]) begin if (n13) q50 <= 1'b0; else q50 <= n50; end end end
  always @(posedge clk0) begin if (i6) q51 <= 1'b0; else q51 <= n51; end
  always @(posedge clk0) begin if (q7) begin if (s1[5]) q52 <= n13; else q52 <= n52; end end
  always @(posedge clk0) begin if (s1[4]) begin if (n17) q53 <= 1'b0; else q53 <= n53; end end
  always @(posedge clk0 or posedge n24) begin if (n24) q57 <= 1'b1; else begin if (i2) begin if (s2[2]) q57 <= s2[5]; else q57 <= n57; end end end
  always @(posedge clk0) begin if (n44) q60 <= s1[1]; else q60 <= n60; end
  always @(negedge clk0) begin if (n33) begin if (q34) q62 <= n15; else q62 <= n62; end end
  always @(posedge clk0) begin if (n55) begin q66 <= n66; end end
  always @(negedge clk0) begin q67 <= n67; end
  always @(posedge clk0) begin if (s5[12]) begin q74 <= n74; end end
  always @(posedge clk0) begin if (i3) begin q79 <= n79; end end
  always @(posedge clk0 or posedge s0[10]) begin if (s0[10]) q84 <= 1'b0; else begin if (n13) q84 <= 1'b0; else if (n9) q84 <= q34; else q84 <= n84; end end
  always @(posedge clk0) begin q88 <= n88; end
  always @(posedge clk0) begin q91 <= n91; end
  always @(posedge clk0) begin q92 <= n92; end
  always @(posedge clk0 or posedge s6[2]) begin if (s6[2]) q94 <= 1'b0; else begin if (n22) q94 <= n49; else q94 <= n94; end end
  always @(posedge clk0 or posedge s0[6]) begin if (s0[6]) q97 <= 1'b0; else begin q97 <= n97; end end
  always @(negedge clk0) begin if (n89) begin if (s0[3]) q102 <= 1'b0; else q102 <= n102; end end
  always @(posedge clk0) begin q105 <= n105; end
  assign o0 = (^{s5[6], s2[6], n63, n93, s1[8], n55, q84, s4[2], s1[5], q62, s0[12], n17, q67, s3[3]});
  assign o1 = (^{s6[11], s1[1], s6[2], s6[12], n44, n2, s1[0], s0[5], s5[11], s4[5], n58, n42, q50, s0[8]});
  assign o2 = ~(^{n11, s6[10], s6[7], q74, n82, n19, q46, n100, n64, q39, n101, n27, n31, n78});
  assign o3 = (^{q66, n98, s3[2], s4[7], n72, s1[3], s0[9], n10, n81, n96, s4[3], n106, s5[9], q57});
  assign o4 = (^{n33, q14, q91, n99, q36, n87, s5[5], n69, n90, s4[0], q97, q23, s0[6]});
  assign o5 = ~(^{n65, q92, s5[0], n37, n86, n38, q25, q34, s4[1], s3[4], n12, n9, s6[3]});
  assign o6 = (^{n76, q48, q4, s0[10], q60, s2[7], s3[1], n85, s4[10], n13, n47, q28, n8});
  assign o7 = (^{q18, s6[4], s2[1], s5[7], q79, q1, s5[1], n103, q30, s4[8], q105, s5[12], s5[3]});
  assign o8 = (^{q7, n75, n0, n56, n15, q52, s2[8], s4[4], n61, s5[4], q51, n45, s4[9]});
  assign o9 = (^{s6[0], n24, s6[6], q21, n54, s4[6], s6[1], q94, s5[8], n95, q26, s2[2], n68});
  assign o10 = (^{s2[0], n22, s0[2], s1[6], n35, q53, n104, s6[9], s1[7], s2[4], n49, q102, s6[5]});
  assign o11 = (^{s0[3], s0[4], n32, n59, n29, s2[3], s1[2], s0[7], n89, q3, s0[1], s5[2], s2[5]});
  assign o12 = (^{n80, n77, s3[0], q43, s5[10], n6, q5, q16, s6[8], s0[11], q88, s0[0], s1[4]});
endmodule
