module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, input i18, input i19, input i20, input i21, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10, output o11, output o12, output o13, output o14);
  wire n0;
  reg q0;
  wire n1;
  wire n2;
  reg q2;
  wire n3;
  wire n4;
  reg q4;
  wire [6:0] s0;
  wire n6;
  wire n7;
  reg q7;
  wire [9:0] s1;
  wire n9;
  wire n10;
  wire n11;
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
  wire [4:0] s2;
  wire n23;
  wire n24;
  reg q24;
  wire n25;
  wire n26;
  wire n27;
  wire n28;
  reg q28;
  wire n29;
  reg q29;
  wire [10:0] s3;
  wire n31;
  wire n32;
  wire [12:0] s4;
  wire [8:0] s5;
  wire [7:0] s6;
  wire n36;
  wire n37;
  wire n38;
  reg q38;
  wire n39;
  wire n40;
  reg q40;
  wire n41;
  wire [12:0] s7;
  wire n43;
  reg q43;
  wire n44;
  wire n45;
  reg q45;
  wire n46;
  wire [3:0] s8;
  wire [7:0] s9;
  wire n49;
  wire n50;
  wire n51;
  wire n52;
  wire n53;
  wire n54;
  wire [11:0] s10;
  wire n56;
  wire [5:0] s11;
  wire [8:0] s12;
  wire n59;
  wire n60;
  wire [5:0] s13;
  wire n62;
  wire n63;
  wire n64;
  wire n65;
  wire n66;
  wire n67;
  reg q67;
  wire n68;
  wire n69;
  reg q69;
  wire n70;
  wire n71;
  reg q71;
  wire n72;
  wire n73;
  reg q73;
  wire n74;
  wire n75;
  wire n76;
  reg q76;
  wire n77;
  wire n78;
  wire n79;
  wire n80;
  wire n81;
  wire n82;
  wire n83;
  reg q83;
  wire [5:0] s14;
  wire n85;
  reg q85;
  wire n86;
  wire n87;
  wire [8:0] s15;
  wire n89;
  wire n90;
  reg q90;
  wire n91;
  wire n92;
  wire n93;
  reg q93;
  wire n94;
  reg q94;
  wire n95;
  assign n0 = 16'h0a96 >> {i7, i5, i4, i17};
  assign n1 = 16'h1e68 >> {i20, i9, i3, i7};
  assign n2 = 16'h12bf >> {i14, i3, n1, i21};
  assign n3 = 16'h8bd7 >> {i0, i9, i3, i15};
  assign n4 = 16'h8f0f >> {i17, i20, i21, i7};
  assign s0 = {1'b0, q4, i5, i3, i16, i18, i9} - {1'b0, i20, i14, i5, i3, i15, q4};
  assign n6 = 16'h8996 >> {i17, s0[6], i3, i16};
  assign n7 = 16'h0d82 >> {n3, i1, s0[6], i8};
  assign s1 = {1'b0, i15, i10, i14, i21, i2, i13, i6, i19, q7} - {1'b0, q0, s0[5], q4, i12, i15, i4, q4, i11, i13};
  assign n9 = 16'h7f16 >> {s0[0], q0, n6, s1[4]};
  assign n10 = 16'hd0e1 >> {i17, i14, s1[2], i19};
  assign n11 = 16'he4d4 >> {n9, i2, q0, s1[7]};
  assign n12 = 16'he66b >> {s1[3], n6, i0, i3};
  assign n13 = 16'h11b4 >> {i3, i5, i9, i18};
  assign n14 = 16'h7aa7 >> {n11, n12, i0, i15};
  assign n15 = 16'h2395 >> {q0, s0[3], n3, n9};
  assign n16 = 16'h21f0 >> {s0[3], s0[3], s1[8], i2};
  assign n17 = 16'hf8d6 >> {n16, q0, s1[9], i17};
  assign n18 = 16'heb2f >> {q2, s0[3], i8, s0[6]};
  assign n19 = 16'ha3d6 >> {i13, s1[9], i3, n12};
  assign n20 = 16'h24dc >> {q7, n15, i13, i20};
  assign n21 = 16'h769e >> {s1[8], i21, s1[1], i18};
  assign s2 = {1'b0, n14, s0[5], s0[1], i17} + {1'b0, q20, s1[8], q20, s0[0]};
  assign n23 = 16'hf3b6 >> {s1[8], n12, i8, i9};
  assign n24 = 16'ha7ec >> {i20, i9, i18, q20};
  assign n25 = 16'h1ff6 >> {s0[3], i9, q7, n12};
  assign n26 = 16'h98a6 >> {i7, s2[2], i16, s0[0]};
  assign n27 = 16'h9c28 >> {i14, s1[8], n13, s0[5]};
  assign n28 = 16'hb78a >> {n13, q2, q19, i6};
  assign n29 = 16'hab44 >> {q2, s2[4], s1[8], i15};
  assign s3 = {1'b0, s1[6], q4, i15, q28, i11, s0[6], i17, s1[8], i8, q20} - {1'b0, s1[1], s1[5], i3, n11, i2, n1, q0, s2[3], q2, i2};
  assign n31 = 16'hc231 >> {n13, s2[4], s2[3], s0[0]};
  assign n32 = 16'hc3a7 >> {s1[5], s3[8], i5, n12};
  assign s4 = {1'b0, q19, q2, s1[2], i17, s3[2], i10, s0[2], i6, i5, s0[2], q4, s1[5]} + {1'b0, i0, i3, s3[9], s3[1], s3[7], q0, i9, n15, s3[0], n16, s1[9], s3[8]};
  assign s5 = {1'b0, s4[1], i21, s4[5], s2[3], s4[12], s4[11], s1[1], q0} - {1'b0, s3[0], s3[5], s4[0], q0, s3[0], s0[1], s0[6], n3};
  assign s6 = {1'b0, s0[5], s4[0], n17, i8, n13, s5[8], s2[2]} - {1'b0, s1[2], i6, s5[1], s0[3], s4[3], n26, n16};
  assign n36 = 16'hd908 >> {s6[7], s0[2], n32, s4[2]};
  assign n37 = 16'hb55d >> {s5[0], s6[6], s4[7], s5[7]};
  assign n38 = 16'h94fa >> {q4, s2[1], s1[9], s4[0]};
  assign n39 = 16'h9f5f >> {s4[8], s6[6], s4[6], n23};
  assign n40 = 16'h69ab >> {n32, q28, s5[0], s3[2]};
  assign n41 = 16'hdd02 >> {s4[10], s6[1], s4[10], n27};
  assign s7 = {1'b0, i13, i21, s4[0], s4[10], q20, s5[3], i20, s3[0], q40, s5[1], s0[5], q19} + {1'b0, s4[1], s5[2], n37, s4[0], s4[9], s4[5], s0[2], i17, s0[2], n3, i5, s2[3]};
  assign n43 = 16'h9c7d >> {s4[9], s7[0], n36, s7[10]};
  assign n44 = 16'hc155 >> {s5[5], s5[5], s7[10], s5[2]};
  assign n45 = 16'h8df5 >> {s7[2], n21, n32, s3[9]};
  assign n46 = 16'h1422 >> {s3[7], n37, s3[5], s3[10]};
  assign s8 = {1'b0, q4, s4[11], i4} - {1'b0, s4[6], s7[9], n9};
  assign s9 = {1'b0, s6[2], s7[3], i18, n14, i18, n17, s7[8]} + {1'b0, n32, s7[2], s0[5], s0[4], s4[4], n3, i0};
  assign n49 = 16'h7a4f >> {s9[3], q43, n46, s5[7]};
  assign n50 = 16'h36ae >> {s7[1], s5[8], s8[3], s4[10]};
  assign n51 = 16'hfcbf >> {s5[2], s6[5], s2[1], n46};
  assign n52 = 16'hf1fa >> {s9[1], s9[1], n46, s8[3]};
  assign n53 = 16'he77b >> {i11, s5[0], s7[3], i4};
  assign n54 = 16'ha5b8 >> {n50, s5[2], s9[3], s8[3]};
  assign s10 = {1'b0, s7[3], i18, q19, s7[11], s4[1], s0[1], s3[0], i1, s1[1], s3[3], s4[3]} - {1'b0, s5[7], s7[9], s1[4], s4[5], s4[3], n53, n31, s7[7], s4[7], n21, s3[3]};
  assign n56 = 16'hf962 >> {s7[12], n53, s9[0], s7[8]};
  assign s11 = {1'b0, s3[9], s4[12], i21, s3[7], s3[1]} - {1'b0, n50, s1[3], s10[10], s10[4], s7[3]};
  assign s12 = {1'b0, i0, s6[3], n50, n26, s3[2], s1[3], s5[2], i13} + {1'b0, s10[11], s5[1], s10[5], s6[5], q43, s1[0], s5[8], n39};
  assign n59 = 16'hdb99 >> {s8[3], n51, n49, s12[7]};
  assign n60 = 16'hb971 >> {n46, q45, n56, q43};
  assign s13 = {1'b0, i4, n1, s8[1], s9[4], q20} - {1'b0, s7[0], n36, n32, q2, s6[2]};
  assign n62 = 16'he163 >> {i0, s12[6], s10[9], s10[3]};
  assign n63 = 16'hb0df >> {n51, s7[12], s11[2], s10[3]};
  assign n64 = 16'h7de2 >> {s10[5], s13[4], s10[6], n50};
  assign n65 = 16'hf2e1 >> {n64, n54, s13[3], s12[8]};
  assign n66 = 16'hc32c >> {n62, s5[5], n49, n63};
  assign n67 = 16'h2bb8 >> {s11[3], s8[3], s11[4], s10[4]};
  assign n68 = 16'had17 >> {s8[3], s10[10], s4[4], s9[6]};
  assign n69 = 16'h627c >> {n50, s10[3], s10[1], s10[6]};
  assign n70 = 16'h64ff >> {s9[5], q69, n52, s10[9]};
  assign n71 = 16'h4d74 >> {s10[11], s10[10], q67, n56};
  assign n72 = 16'haf85 >> {s13[0], s11[2], n52, s9[7]};
  assign n73 = 16'h2d71 >> {s10[2], n64, s12[6], s9[2]};
  assign n74 = 16'h9e70 >> {s13[5], s11[5], s10[4], i19};
  assign n75 = 16'hc9c9 >> {n63, q69, s11[5], n56};
  assign n76 = 16'he912 >> {s13[1], n62, s10[4], s4[1]};
  assign n77 = 16'h804a >> {s10[11], s13[5], s12[2], s5[2]};
  assign n78 = 16'hbaa5 >> {n74, q69, n77, s9[7]};
  assign n79 = 16'he30f >> {s10[5], q67, s9[0], s13[1]};
  assign n80 = 16'h7e3d >> {s12[4], q43, s11[0], q71};
  assign n81 = 16'h2cf3 >> {q69, s12[7], q73, n75};
  assign n82 = 16'hd7aa >> {n53, s10[9], s12[7], n65};
  assign n83 = 16'hfde6 >> {s10[9], n60, s12[1], n62};
  assign s14 = {1'b0, n50, s6[0], n3, s9[2], s10[0]} - {1'b0, s10[11], n51, q24, n77, n78};
  assign n85 = 16'hd331 >> {s10[6], n65, q76, q76};
  assign n86 = 16'h208f >> {n78, s14[1], s11[4], s0[2]};
  assign n87 = 16'hd81b >> {n75, s12[0], s11[4], s11[4]};
  assign s15 = {1'b0, n1, s2[3], s7[11], i21, q45, s7[4], s13[1], i13} + {1'b0, s6[6], s10[2], i4, s4[0], q7, s14[1], s10[6], q67};
  assign n89 = 16'h47ea >> {n70, s15[5], n79, s12[4]};
  assign n90 = 16'hc2f1 >> {q85, s15[1], n81, q73};
  assign n91 = 16'h4065 >> {n60, n62, s15[3], s5[8]};
  assign n92 = 16'h7f0c >> {s13[5], q73, n68, n64};
  assign n93 = 16'h2767 >> {n15, s13[1], s13[2], s13[0]};
  assign n94 = 16'h1ae3 >> {s13[0], n14, n86, q67};
  assign n95 = 16'h234d >> {n81, s12[3], q76, s13[5]};
  always @(posedge clk0) begin q0 <= n0; end
  always @(posedge clk0) begin if (i10) begin q2 <= n2; end end
  always @(posedge clk0) begin if (i15) begin q4 <= n4; end end
  always @(posedge clk0) begin if (i19) begin if (n6) q7 <= n6; else q7 <= n7; end end
  always @(posedge clk0) begin if (i11) q18 <= 1'b0; else q18 <= n18; end
  always @(posedge clk0) begin if (i3) q19 <= 1'b0; else q19 <= n19; end
  always @(posedge clk0) begin if (i18) begin q20 <= n20; end end
  always @(posedge clk0) begin if (s0[2]) begin if (i8) q24 <= n21; else q24 <= n24; end end
  always @(posedge clk0) begin q28 <= n28; end
  always @(posedge clk0 or posedge i19) begin if (i19) q29 <= 1'b1; else begin q29 <= n29; end end
  always @(negedge clk0) begin if (n37) begin q38 <= n38; end end
  always @(posedge clk0 or posedge n10) begin if (n10) q40 <= 1'b1; else begin q40 <= n40; end end
  always @(posedge clk0 or posedge n14) begin if (n14) q43 <= 1'b1; else begin q43 <= n43; end end
  always @(negedge clk0) begin if (q7) begin q45 <= n45; end end
  always @(posedge clk0) begin if (n65) q67 <= 1'b0; else if (i4) q67 <= i9; else q67 <= n67; end
  always @(posedge clk0 or posedge q4) begin if (q4) q69 <= 1'b0; else begin q69 <= n69; end end
  always @(posedge clk0 or posedge s12[3]) begin if (s12[3]) q71 <= 1'b0; else begin if (s3[3]) begin q71 <= n71; end end end
  always @(posedge clk0) begin if (n27) begin q73 <= n73; end end
  always @(posedge clk0) begin if (n39) q76 <= i0; else q76 <= n76; end
  always @(posedge clk0) begin if (q40) q83 <= 1'b0; else q83 <= n83; end
  always @(posedge clk0) begin if (n41) q85 <= s12[3]; else q85 <= n85; end
  always @(negedge clk0 or posedge s6[5]) begin if (s6[5]) q90 <= 1'b0; else begin q90 <= n90; end end
  always @(posedge clk0) begin if (q76) q93 <= s14[5]; else q93 <= n93; end
  always @(posedge clk0 or posedge n36) begin if (n36) q94 <= 1'b0; else begin q94 <= n94; end end
  assign o0 = (^{s1[2], n91, s8[3], q20, n65, s12[2], s2[3], s13[4], s3[8], s4[1], n52, s1[9], n36, q90, q0});
  assign o1 = (^{s9[7], n64, s15[0], n95, s5[7], n44, s3[10], n80, s6[5], s9[4], n77, s10[0], q4, s10[7], q2});
  assign o2 = ~(^{n66, s7[9], q83, s10[2], n46, s7[3], s9[3], s3[0], s4[3], s1[3], s10[4], s6[3], s9[5], q67, s7[2]});
  assign o3 = ~(^{n56, q93, s5[0], n1, s11[0], s4[11], n27, n49, n13, s12[6], s7[1], n32, s14[1], s15[5], s1[4]});
  assign o4 = (^{s1[1], s4[7], n6, s4[2], q28, n31, s14[3], s3[3], s13[3], s13[5], s13[0], q76, s0[6], q45, s3[7]});
  assign o5 = (^{s1[5], s14[0], s15[2], s3[1], s10[1], s3[2], q24, s12[3], s15[6], q85, n59, n21, s10[10], n14, q69});
  assign o6 = ~(^{s15[7], n51, s13[2], s2[1], s10[6], s12[7], s3[5], s3[9], s2[2], s6[6], n54, s11[1], s4[8], n81});
  assign o7 = ~(^{s0[4], q19, n15, s6[7], q71, s2[4], n92, s4[0], s8[1], s5[8], s7[4], s6[0], n86, s5[1]});
  assign o8 = (^{s12[5], q7, s14[2], n23, s14[4], s7[10], q94, n53, s2[0], n60, s7[5], s13[1], s6[4], s1[8]});
  assign o9 = (^{q18, s11[2], s1[7], n82, q73, s10[8], n41, s10[3], s15[4], n63, q40, n72, s5[4], s8[0]});
  assign o10 = (^{n89, s5[5], s5[2], s0[1], n16, s10[9], n37, s10[11], s7[0], n68, s11[4], s0[0], s11[5], n50});
  assign o11 = ~(^{s15[3], s7[8], s9[2], n78, n75, s15[1], n25, n70, s4[4], s12[0], q38, s4[6], n9, n3});
  assign o12 = (^{s8[2], n62, s0[2], s7[11], q29, s0[5], s6[1], s9[6], n10, s9[0], n79, n74, s1[0], s6[2]});
  assign o13 = (^{n39, n17, s4[10], s3[4], s4[5], s0[3], s3[6], s12[4], n87, n11, s7[12], s4[12], s5[6], n26});
  assign o14 = (^{s7[6], s5[3], s11[3], s12[8], s7[7], s15[8], s1[6], s9[1], s12[1], s10[5], s4[9], n12, q43, s14[5]});
endmodule
