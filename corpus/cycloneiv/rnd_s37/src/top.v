module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8);
  wire n0;
  wire n1;
  reg q1;
  wire n2;
  reg q2;
  wire n3;
  wire n4;
  wire n5;
  reg q5;
  wire n6;
  reg q6;
  wire n7;
  wire n8;
  reg q8;
  wire n9;
  wire n10;
  reg q10;
  wire n11;
  reg q11;
  wire n12;
  wire n13;
  wire n14;
  wire n15;
  wire [9:0] s0;
  wire n17;
  reg q17;
  wire n18;
  wire n19;
  reg q19;
  wire n20;
  wire n21;
  wire n22;
  wire n23;
  wire n24;
  wire n25;
  wire n26;
  wire n27;
  reg q27;
  wire n28;
  reg q28;
  wire n29;
  wire n30;
  wire [5:0] s1;
  wire n32;
  wire n33;
  reg q33;
  wire [3:0] s2;
  wire n35;
  wire n36;
  reg q36;
  wire n37;
  wire n38;
  wire [3:0] s3;
  wire n40;
  wire n41;
  reg q41;
  wire n42;
  wire n43;
  wire n44;
  reg q44;
  wire n45;
  wire n46;
  wire n47;
  wire n48;
  wire n49;
  wire n50;
  reg q50;
  wire n51;
  wire n52;
  reg q52;
  wire n53;
  wire n54;
  wire n55;
  reg q55;
  wire n56;
  wire n57;
  wire [8:0] s4;
  wire [4:0] s5;
  wire n60;
  wire n61;
  reg q61;
  wire n62;
  reg q62;
  wire [12:0] s6;
  wire n64;
  wire n65;
  wire n66;
  reg q66;
  wire n67;
  wire n68;
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
  reg q75;
  wire n76;
  wire n77;
  reg q77;
  wire [11:0] s7;
  wire n79;
  wire n80;
  reg q80;
  wire n81;
  wire n82;
  reg q82;
  wire n83;
  reg q83;
  wire n84;
  wire n85;
  reg q85;
  wire n86;
  wire n87;
  wire [7:0] s8;
  wire n89;
  reg q89;
  wire n90;
  assign n0 = 16'h2688 >> {i7, i3, i3, i9};
  assign n1 = 16'hb9b8 >> {n0, i0, i6, i5};
  assign n2 = 16'hb9ee >> {i7, i4, i7, n0};
  assign n3 = 16'hd8c6 >> {i7, i7, i2, i6};
  assign n4 = 16'hb733 >> {i4, i7, n0, q1};
  assign n5 = 16'h3cf1 >> {i6, i2, q2, q1};
  assign n6 = 16'h8e2e >> {i9, i5, q1, i4};
  assign n7 = 16'hab78 >> {n0, i8, n0, q2};
  assign n8 = 16'hd95b >> {q6, n3, i1, n3};
  assign n9 = 16'h948b >> {i2, q8, i1, n3};
  assign n10 = 16'hc8f0 >> {i2, i2, i3, n4};
  assign n11 = 16'h12d2 >> {n3, n9, i4, n7};
  assign n12 = 16'ha972 >> {i5, q2, q1, n3};
  assign n13 = 16'h60e6 >> {n9, i0, i1, i8};
  assign n14 = 16'h2643 >> {q5, n12, q1, q11};
  assign n15 = 16'haead >> {n13, i6, i6, i8};
  assign s0 = {1'b0, n7, q5, i3, n0, n4, n7, n0, q8, q8} - {1'b0, i1, i9, n12, q2, i0, q8, n4, n9, n13};
  assign n17 = 16'hb308 >> {q6, n9, q5, s0[3]};
  assign n18 = 16'he734 >> {i8, n12, s0[3], i7};
  assign n19 = 16'h9e35 >> {q17, s0[4], i4, i1};
  assign n20 = 16'h17dc >> {n4, q6, i3, i1};
  assign n21 = 16'hb522 >> {q8, n12, n14, s0[6]};
  assign n22 = 16'h2bb7 >> {i0, q19, q8, i9};
  assign n23 = 16'he294 >> {q5, q6, s0[0], s0[1]};
  assign n24 = 16'h6d84 >> {n15, i6, q1, q11};
  assign n25 = 16'hd291 >> {i7, i8, q2, n4};
  assign n26 = 16'h6ce2 >> {n18, n23, s0[5], q10};
  assign n27 = 16'h7b9d >> {s0[0], n9, n21, s0[0]};
  assign n28 = 16'h8b50 >> {n21, n25, i6, q5};
  assign n29 = 16'h3057 >> {n21, s0[2], q10, n4};
  assign n30 = 16'h6f44 >> {n26, n24, n4, n25};
  assign s1 = {1'b0, q19, q8, q10, n20, n26} + {1'b0, s0[1], n29, n3, n18, n7};
  assign n32 = 16'h355a >> {s0[8], i0, s0[5], i3};
  assign n33 = 16'hee4c >> {n29, s0[8], q1, q10};
  assign s2 = {1'b0, s0[7], q33, s0[6]} + {1'b0, n0, n13, q19};
  assign n35 = 16'h7dd2 >> {s1[4], q19, s0[8], n18};
  assign n36 = 16'h901a >> {s1[5], i5, q28, s0[1]};
  assign n37 = 16'h3f70 >> {s2[2], s2[0], q33, n4};
  assign n38 = 16'hee0d >> {s2[3], n9, s1[3], s0[2]};
  assign s3 = {1'b0, n3, q17, i2} + {1'b0, n32, q8, s2[3]};
  assign n40 = 16'h4c24 >> {n38, n7, n23, s0[3]};
  assign n41 = 16'hc5fc >> {s1[1], s3[2], q6, n30};
  assign n42 = 16'ha63b >> {q19, n35, n22, q27};
  assign n43 = 16'h80fd >> {s0[1], s0[5], n12, s0[3]};
  assign n44 = 16'h3b8d >> {n38, q6, s3[1], q6};
  assign n45 = 16'hc9d7 >> {q2, n37, i0, q10};
  assign n46 = 16'hb079 >> {q28, s2[0], q19, s0[2]};
  assign n47 = 16'h0057 >> {n20, s2[1], n42, s1[5]};
  assign n48 = 16'h5f82 >> {n30, q41, n47, s3[2]};
  assign n49 = 16'h19bf >> {n15, n30, n32, s1[0]};
  assign n50 = 16'h767b >> {s0[3], s3[2], s0[1], n23};
  assign n51 = 16'hec56 >> {s2[2], s1[4], n29, n46};
  assign n52 = 16'h8606 >> {n14, n14, n24, s0[7]};
  assign n53 = 16'h3aa4 >> {s0[9], n23, n43, n42};
  assign n54 = 16'h8790 >> {q52, s1[5], s0[9], n49};
  assign n55 = 16'hc5fb >> {s1[5], q19, n18, q52};
  assign n56 = 16'h8d07 >> {n23, q33, n29, s2[1]};
  assign n57 = 16'hd2af >> {i1, s0[8], q2, q50};
  assign s4 = {1'b0, n46, n14, s1[5], s1[1], s0[0], q55, q55, n13} - {1'b0, q50, s0[1], s3[3], s1[2], s1[1], q44, q50, n18};
  assign s5 = {1'b0, i3, s0[1], n38, n57} + {1'b0, q19, n23, n32, s4[4]};
  assign n60 = 16'h897e >> {n43, n43, n40, n47};
  assign n61 = 16'hd446 >> {s3[0], s4[1], s5[1], s1[4]};
  assign n62 = 16'h19db >> {n30, q50, s4[6], q33};
  assign s6 = {1'b0, n15, n54, s5[1], n7, n56, q28, s1[0], q33, s5[2], q1, n30, n60} - {1'b0, s3[2], s0[4], s0[5], q44, q10, s0[6], n3, n18, s0[9], i2, s4[8], n53};
  assign n64 = 16'h83be >> {s2[3], n38, s3[1], s6[9]};
  assign n65 = 16'hf424 >> {n29, s4[3], s6[7], s6[0]};
  assign n66 = 16'hb063 >> {s6[4], n43, s3[0], n43};
  assign n67 = 16'h1572 >> {q61, s4[2], s6[5], q44};
  assign n68 = 16'hcb54 >> {s5[0], n67, s4[1], s6[2]};
  assign n69 = 16'hb311 >> {s3[1], n60, n67, n49};
  assign n70 = 16'hc2eb >> {q66, n64, s5[1], n45};
  assign n71 = 16'heb81 >> {q66, i2, s4[1], s6[6]};
  assign n72 = 16'hdf9a >> {s4[3], n45, s6[1], q44};
  assign n73 = 16'hbe99 >> {n72, n54, n57, q55};
  assign n74 = 16'hfa05 >> {n69, n68, q70, s6[4]};
  assign n75 = 16'h1e28 >> {n68, q61, s4[7], s6[6]};
  assign n76 = 16'hb0a8 >> {s6[2], q55, s6[7], s5[0]};
  assign n77 = 16'ha0a0 >> {s4[4], i2, s6[5], n42};
  assign s7 = {1'b0, q17, n4, n60, n60, n74, s4[1], s6[10], q55, n60, s0[3], s5[0]} + {1'b0, s6[9], q71, s6[8], n65, n3, i0, q2, q5, s0[3], s0[0], q28};
  assign n79 = 16'h96c0 >> {n56, s4[1], n65, s7[11]};
  assign n80 = 16'h99ca >> {s6[8], s6[7], n64, s4[5]};
  assign n81 = 16'hca70 >> {s7[7], q2, s6[7], s6[5]};
  assign n82 = 16'hd3dc >> {n54, n72, s5[3], n57};
  assign n83 = 16'h29c4 >> {q41, s7[1], s7[10], s7[6]};
  assign n84 = 16'h90f3 >> {q80, s6[6], n72, q77};
  assign n85 = 16'h1bc1 >> {s6[10], n74, q77, n18};
  assign n86 = 16'h280f >> {s7[2], s5[0], s4[7], s4[7]};
  assign n87 = 16'h08f4 >> {s6[2], q82, q85, n84};
  assign s8 = {1'b0, n13, n43, q66, n32, s0[6], i8, i0} + {1'b0, n26, n45, s0[9], n38, s4[1], s6[10], s0[9]};
  assign n89 = 16'hdac3 >> {s6[5], q75, n60, n69};
  assign n90 = 16'h4a65 >> {s6[5], n74, s6[7], s8[3]};
  always @(posedge clk0 or posedge i7) begin if (i7) q1 <= 1'b0; else begin q1 <= n1; end end
  always @(negedge clk0 or posedge n0) begin if (n0) q2 <= 1'b0; else begin if (i5) q2 <= 1'b0; else if (i5) q2 <= q1; else q2 <= n2; end end
  always @(posedge clk0) begin if (i8) q5 <= 1'b0; else q5 <= n5; end
  always @(posedge clk0) begin if (i6) q6 <= 1'b0; else q6 <= n6; end
  always @(posedge clk0) begin if (q2) q8 <= 1'b0; else q8 <= n8; end
  always @(posedge clk0) begin if (i3) q10 <= 1'b0; else q10 <= n10; end
  always @(posedge clk0) begin if (n0) q11 <= 1'b0; else if (i4) q11 <= i8; else q11 <= n11; end
  always @(posedge clk0) begin if (i3) begin q17 <= n17; end end
  always @(posedge clk0) begin if (s0[5]) begin if (q1) q19 <= 1'b0; else q19 <= n19; end end
  always @(posedge clk0) begin q27 <= n27; end
  always @(negedge clk0) begin q28 <= n28; end
  always @(posedge clk0) begin if (q11) begin if (n15) q33 <= 1'b0; else if (i8) q33 <= n14; else q33 <= n33; end end
  always @(posedge clk0) begin q36 <= n36; end
  always @(negedge clk0 or posedge s0[9]) begin if (s0[9]) q41 <= 1'b1; else begin if (s0[2]) q41 <= n22; else q41 <= n41; end end
  always @(posedge clk0) begin q44 <= n44; end
  always @(posedge clk0 or posedge n0) begin if (n0) q50 <= 1'b1; else begin if (s3[1]) begin q50 <= n50; end end end
  always @(posedge clk0) begin if (n49) begin q52 <= n52; end end
  always @(posedge clk0) begin q55 <= n55; end
  always @(posedge clk0 or posedge s5[0]) begin if (s5[0]) q61 <= 1'b0; else begin if (i1) begin q61 <= n61; end end end
  always @(posedge clk0) begin if (s0[6]) q62 <= 1'b0; else if (s0[5]) q62 <= q44; else q62 <= n62; end
  always @(posedge clk0) begin q66 <= n66; end
  always @(negedge clk0) begin if (s0[0]) q70 <= n35; else q70 <= n70; end
  always @(posedge clk0) begin if (n57) q71 <= q6; else q71 <= n71; end
  always @(posedge clk0 or posedge n72) begin if (n72) q73 <= 1'b0; else begin q73 <= n73; end end
  always @(posedge clk0 or posedge s6[9]) begin if (s6[9]) q75 <= 1'b1; else begin if (i2) begin if (q52) q75 <= 1'b0; else q75 <= n75; end end end
  always @(posedge clk0) begin if (i5) q77 <= n56; else q77 <= n77; end
  always @(posedge clk0 or posedge n79) begin if (n79) q80 <= 1'b1; else begin if (s1[3]) q80 <= n64; else q80 <= n80; end end
  always @(negedge clk0 or posedge n4) begin if (n4) q82 <= 1'b1; else begin if (s4[4]) begin if (n21) q82 <= 1'b0; else if (s6[2]) q82 <= n79; else q82 <= n82; end end end
  always @(negedge clk0 or posedge s0[9]) begin if (s0[9]) q83 <= 1'b1; else begin q83 <= n83; end end
  always @(posedge clk0) begin if (s6[8]) q85 <= 1'b0; else if (s3[1]) q85 <= q50; else q85 <= n85; end
  always @(negedge clk0 or posedge s1[4]) begin if (s1[4]) q89 <= 1'b1; else begin if (n48) q89 <= 1'b0; else q89 <= n89; end end
  assign o0 = (^{q44, n47, q33, s6[7], n45, n74, s5[1], s6[5], q10, s3[0], s6[6], s6[11], q19, n60, q28, n79, s7[1]});
  assign o1 = (^{q89, s5[4], n37, s8[3], n25, q61, s0[0], s7[6], n69, s0[9], n7, s3[1], s1[1], q1, n90, s1[5], s7[4]});
  assign o2 = (^{n21, q71, s6[9], n57, n15, n4, s6[2], n20, q41, s8[1], q73, n24, n14, s5[3], s1[2], n84, n18});
  assign o3 = ~(^{q62, s2[2], n67, s7[9], n46, s6[8], n51, s6[4], s1[0], s7[8], n29, s6[1], q2, s6[3], n54, n87, s7[5]});
  assign o4 = (^{q66, s0[8], n53, q77, s8[6], n9, s6[0], n3, s2[3], q5, s7[3], s4[5], q17, n86, s7[10], s6[10], n49});
  assign o5 = ~(^{q80, s2[1], q52, n26, n32, s7[0], s0[3], n48, n35, s8[5], n23, q83, s3[2], n76, s7[11], n42, s5[0]});
  assign o6 = (^{n68, n65, q82, s0[6], s7[7], s4[1], q70, s7[2], s3[3], s8[7], s0[7], s8[4], n30, q6, n81, s0[2], s4[2]});
  assign o7 = ~(^{n40, q11, s0[4], s8[0], n43, s1[4], s4[6], s4[0], s8[2], s1[3], n12, n38, n13, s4[3], q85, s4[4], s5[2]});
  assign o8 = ~(^{s2[0], n22, q27, s0[5], q75, s4[8], s6[12], q55, q50, n56, s0[1], s4[7], q8, n0, n72, q36, n64});
endmodule
