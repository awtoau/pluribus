module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10, output o11);
  wire n0;
  wire n1;
  wire n2;
  wire [7:0] s0;
  wire n4;
  reg q4;
  wire n5;
  reg q5;
  wire n6;
  wire n7;
  wire n8;
  wire n9;
  wire n10;
  wire n11;
  wire n12;
  wire n13;
  wire n14;
  wire n15;
  wire n16;
  wire n17;
  wire [3:0] s1;
  wire n19;
  reg q19;
  wire [11:0] s2;
  wire n21;
  wire [4:0] s3;
  wire n23;
  wire n24;
  wire n25;
  reg q25;
  wire n26;
  wire n27;
  reg q27;
  wire [12:0] s4;
  wire n29;
  wire [6:0] s5;
  wire n31;
  reg q31;
  wire n32;
  wire n33;
  wire n34;
  wire n35;
  wire n36;
  reg q36;
  wire n37;
  reg q37;
  wire n38;
  reg q38;
  wire n39;
  wire n40;
  reg q40;
  wire n41;
  wire [9:0] s6;
  wire n43;
  reg q43;
  wire n44;
  wire n45;
  reg q45;
  wire n46;
  reg q46;
  wire n47;
  reg q47;
  wire n48;
  wire n49;
  wire n50;
  reg q50;
  wire n51;
  wire n52;
  wire n53;
  reg q53;
  wire n54;
  reg q54;
  wire n55;
  wire [6:0] s7;
  wire n57;
  reg q57;
  wire n58;
  reg q58;
  wire n59;
  wire n60;
  reg q60;
  wire n61;
  wire n62;
  reg q62;
  wire n63;
  reg q63;
  wire n64;
  reg q64;
  wire n65;
  wire [3:0] s8;
  wire n67;
  wire n68;
  wire n69;
  reg q69;
  assign n0 = 16'h49a1 >> {i1, i17, i9, i3};
  assign n1 = 16'hc10e >> {i17, i15, i2, i17};
  assign n2 = 16'h816a >> {i11, i8, i3, i1};
  assign s0 = {1'b0, i10, i2, i13, i14, i12, i3, i15} + {1'b0, n0, i3, i11, i15, i3, i11, i9};
  assign n4 = 16'h22db >> {s0[7], i12, i7, i1};
  assign n5 = 16'he067 >> {i14, i1, s0[6], s0[6]};
  assign n6 = 16'hfa8e >> {q4, i9, s0[7], s0[6]};
  assign n7 = 16'hf3b9 >> {n2, s0[2], i7, i2};
  assign n8 = 16'h9cbd >> {s0[0], i7, s0[7], i8};
  assign n9 = 16'h58f0 >> {i14, n1, i2, i4};
  assign n10 = 16'hc326 >> {s0[4], i15, i12, i9};
  assign n11 = 16'h9881 >> {n7, s0[4], q4, n8};
  assign n12 = 16'ha6f8 >> {q5, i16, s0[0], i17};
  assign n13 = 16'h6ade >> {i13, n7, n7, n11};
  assign n14 = 16'hdb9f >> {i8, n11, n8, s0[7]};
  assign n15 = 16'h8eef >> {i11, i6, s0[4], n13};
  assign n16 = 16'h52ae >> {s0[1], n11, s0[4], s0[0]};
  assign n17 = 16'h6e0d >> {n2, s0[3], i8, i8};
  assign s1 = {1'b0, s0[6], n14, s0[7]} - {1'b0, s0[3], q5, i4};
  assign n19 = 16'h5a3c >> {n9, i3, n17, n15};
  assign s2 = {1'b0, s0[6], n2, i11, n12, q4, i17, s1[0], i7, s0[7], i13, s0[4]} + {1'b0, s0[2], n6, i10, s0[6], q19, i6, s1[2], n10, n13, n1, n1};
  assign n21 = 16'h9a22 >> {s2[2], s2[2], s0[1], i7};
  assign s3 = {1'b0, i15, s0[3], s2[2], i9} - {1'b0, s0[5], i12, n1, i1};
  assign n23 = 16'h1661 >> {s0[7], s3[1], s3[1], s2[9]};
  assign n24 = 16'hc504 >> {n10, n2, s0[7], i17};
  assign n25 = 16'h4329 >> {s0[0], s2[10], i14, q5};
  assign n26 = 16'h428a >> {n7, s0[3], n23, i9};
  assign n27 = 16'h70ff >> {n24, i13, q25, s2[11]};
  assign s4 = {1'b0, q27, q4, s1[3], n24, s0[4], s2[10], s3[2], n14, n9, i15, s0[5], n23} - {1'b0, s0[3], i13, s2[8], i8, s0[6], i2, s2[9], s0[1], i11, s0[0], i11, i16};
  assign n29 = 16'h1f6d >> {s2[10], n6, s1[2], s2[7]};
  assign s5 = {1'b0, s4[0], s4[0], i5, i11, s2[9], s4[6]} - {1'b0, s0[4], s4[4], s1[3], s2[6], i9, s4[12]};
  assign n31 = 16'h153a >> {n23, n13, s5[1], s2[4]};
  assign n32 = 16'h8cd6 >> {s5[5], s5[2], s3[4], s3[0]};
  assign n33 = 16'h6359 >> {n21, s2[4], n17, s2[9]};
  assign n34 = 16'h9868 >> {s4[4], n29, s1[1], s4[7]};
  assign n35 = 16'hd629 >> {s4[2], n13, n11, s4[0]};
  assign n36 = 16'h3202 >> {s4[0], s4[4], n14, s1[3]};
  assign n37 = 16'he6b4 >> {q27, q25, n24, s3[3]};
  assign n38 = 16'hacc1 >> {i13, s5[0], s2[10], s1[2]};
  assign n39 = 16'ha288 >> {q31, s3[0], n32, s4[7]};
  assign n40 = 16'he198 >> {n32, s2[9], q25, n16};
  assign n41 = 16'h69c1 >> {s2[6], i2, n33, s3[1]};
  assign s6 = {1'b0, q40, s5[4], s5[3], i14, s4[12], s1[0], i1, q5, i16} - {1'b0, n21, s2[4], s5[0], s2[3], q37, s5[5], s1[3], s2[11], n15};
  assign n43 = 16'h5008 >> {s4[9], q27, i8, s6[5]};
  assign n44 = 16'h2702 >> {i11, q37, q38, s2[11]};
  assign n45 = 16'h8f8e >> {n24, s5[2], s2[7], s3[4]};
  assign n46 = 16'hdf99 >> {s6[5], q40, s2[10], s2[2]};
  assign n47 = 16'hb9e3 >> {n32, s3[4], n44, n35};
  assign n48 = 16'h2f9b >> {n29, n34, n33, s4[6]};
  assign n49 = 16'hda45 >> {n35, q45, s5[6], s6[6]};
  assign n50 = 16'hc09f >> {s4[7], q45, s4[2], q40};
  assign n51 = 16'h095b >> {s5[0], s6[4], i6, q36};
  assign n52 = 16'h49bc >> {n32, s6[7], s4[7], s4[5]};
  assign n53 = 16'haf67 >> {q45, n44, s4[9], s4[2]};
  assign n54 = 16'h4b04 >> {s5[3], s6[5], s6[5], s6[3]};
  assign n55 = 16'hbeba >> {s4[6], n33, n48, s4[9]};
  assign s7 = {1'b0, n12, n35, s2[6], s3[3], i4, i15} - {1'b0, s6[1], s0[2], s4[12], s2[9], s4[9], s3[3]};
  assign n57 = 16'hcdab >> {s4[12], s4[11], s4[11], s6[3]};
  assign n58 = 16'hfc90 >> {s6[3], s5[6], n52, n52};
  assign n59 = 16'h4dab >> {s6[4], s4[4], q58, q57};
  assign n60 = 16'he28a >> {s7[5], s6[6], n41, s4[8]};
  assign n61 = 16'h64d9 >> {s7[4], s4[10], n41, q53};
  assign n62 = 16'h621c >> {q38, q36, n44, n52};
  assign n63 = 16'hdffa >> {n49, s7[5], q50, s6[8]};
  assign n64 = 16'hc37c >> {q58, s0[4], q46, n52};
  assign n65 = 16'hce63 >> {q64, n44, s6[7], n61};
  assign s8 = {1'b0, n32, s1[2], i17} + {1'b0, s4[7], s7[2], i17};
  assign n67 = 16'hb916 >> {q50, s5[2], s5[2], n48};
  assign n68 = 16'h2ebe >> {q43, n39, s7[3], s7[3]};
  assign n69 = 16'h63ee >> {s8[3], s2[5], n61, s6[3]};
  always @(posedge clk1) begin q4 <= n4; end
  always @(negedge clk0) begin if (s0[5]) q5 <= 1'b0; else q5 <= n5; end
  always @(posedge clk1) begin if (i5) begin if (i13) q19 <= n9; else q19 <= n19; end end
  always @(posedge clk0) begin if (s2[5]) q25 <= 1'b0; else q25 <= n25; end
  always @(posedge clk0 or posedge s0[6]) begin if (s0[6]) q27 <= 1'b1; else begin if (s2[8]) begin q27 <= n27; end end end
  always @(posedge clk1) begin if (s4[5]) begin q31 <= n31; end end
  always @(posedge clk0) begin if (s4[2]) q36 <= s0[6]; else q36 <= n36; end
  always @(posedge clk0) begin q37 <= n37; end
  always @(posedge clk0) begin q38 <= n38; end
  always @(posedge clk0) begin if (s2[4]) q40 <= n16; else q40 <= n40; end
  always @(posedge clk0 or posedge s6[5]) begin if (s6[5]) q43 <= 1'b0; else begin if (n10) q43 <= 1'b0; else q43 <= n43; end end
  always @(posedge clk1 or posedge s6[7]) begin if (s6[7]) q45 <= 1'b1; else begin q45 <= n45; end end
  always @(posedge clk0) begin if (i10) begin q46 <= n46; end end
  always @(posedge clk0 or posedge q19) begin if (q19) q47 <= 1'b1; else begin q47 <= n47; end end
  always @(posedge clk1) begin if (n10) q50 <= 1'b0; else q50 <= n50; end
  always @(posedge clk0 or posedge s3[3]) begin if (s3[3]) q53 <= 1'b0; else begin if (n11) begin q53 <= n53; end end end
  always @(posedge clk1) begin q54 <= n54; end
  always @(posedge clk1) begin if (q31) q57 <= 1'b0; else q57 <= n57; end
  always @(posedge clk0) begin if (s7[6]) begin q58 <= n58; end end
  always @(negedge clk0) begin if (s4[11]) begin q60 <= n60; end end
  always @(posedge clk0 or posedge n24) begin if (n24) q62 <= 1'b1; else begin if (n34) begin q62 <= n62; end end end
  always @(posedge clk1 or posedge i1) begin if (i1) q63 <= 1'b0; else begin if (q19) begin if (s5[6]) q63 <= n2; else q63 <= n63; end end end
  always @(posedge clk0) begin if (s5[6]) q64 <= 1'b0; else q64 <= n64; end
  always @(posedge clk0) begin if (i14) begin q69 <= n69; end end
  assign o0 = (^{n17, n15, n6, q58, n23, n29, s4[7], s6[1], q45, n67, s2[11]});
  assign o1 = ~(^{q60, q64, s3[3], s2[10], s8[0], q69, s2[1], q37, s7[3], s0[2], s2[0]});
  assign o2 = ~(^{n11, n10, s4[6], s6[6], s6[2], n61, n26, q57, s6[9], s7[6], n39});
  assign o3 = ~(^{s6[8], q63, s4[2], n49, n12, s2[7], s3[1], q19, n44, n13, s5[5]});
  assign o4 = (^{s4[0], n14, s6[7], q4, s1[1], s2[6], q36, n51, s2[9], n9, s5[0]});
  assign o5 = ~(^{n65, n34, q27, s7[1], n55, q62, s2[3], s1[2], s5[1], s4[1], s1[3]});
  assign o6 = (^{s4[5], s4[4], n32, s3[0], s0[4], s7[5], q50, s7[2], s0[3], n0, s6[4]});
  assign o7 = ~(^{n35, n2, s1[0], s6[3], s0[7], s6[5], q25, s6[0], s2[5], n21, s2[8]});
  assign o8 = (^{s5[4], s5[2], n8, s0[6], s3[2], s8[1], q40, s2[4], s3[4], q5, q46});
  assign o9 = (^{q54, n52, s0[0], s5[6], n68, s8[3], s2[2], q47, s4[10], s4[12], n48});
  assign o10 = (^{s5[3], n41, s7[4], s4[3], n1, q43, s8[2], q53, s7[0], s0[5], s4[11]});
  assign o11 = (^{s4[8], n16, n7, n33, n59, s0[1], q38, n24, s4[9], q31});
endmodule
