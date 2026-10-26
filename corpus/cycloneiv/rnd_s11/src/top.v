module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10);
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
  reg q8;
  wire n9;
  reg q9;
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
  reg q23;
  wire n24;
  wire n25;
  reg q25;
  wire n26;
  reg q26;
  wire n27;
  reg q27;
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
  reg q38;
  wire n39;
  wire n40;
  wire n41;
  wire n42;
  wire n43;
  reg q43;
  wire n44;
  wire n45;
  wire n46;
  reg q46;
  wire n47;
  wire n48;
  wire n49;
  wire n50;
  wire n51;
  reg q51;
  wire n52;
  wire n53;
  wire n54;
  wire n55;
  reg q55;
  wire n56;
  wire n57;
  wire n58;
  wire n59;
  reg q59;
  wire n60;
  wire n61;
  wire n62;
  reg q62;
  wire n63;
  reg q63;
  wire n64;
  wire n65;
  reg q65;
  wire n66;
  reg q66;
  assign n0 = 16'h9c68 >> {i0, i0, i5, i3};
  assign n1 = 16'ha0b8 >> {i4, i7, i0, i1};
  assign n2 = 16'h1bcb >> {i5, i1, i2, i0};
  assign n3 = 16'h6600 >> {n0, i6, n0, i1};
  assign n4 = 16'h6e44 >> {n0, i3, i4, i4};
  assign n5 = 16'h268d >> {i5, i3, i0, n0};
  assign n6 = 16'hf0ef >> {n5, i2, i3, i4};
  assign n7 = 16'h1e52 >> {i3, n2, n4, i0};
  assign n8 = 16'h5b02 >> {q7, q7, n2, i6};
  assign n9 = 16'h2eed >> {n4, i4, n0, n6};
  assign n10 = 16'he896 >> {q9, n5, i2, n6};
  assign n11 = 16'h1eea >> {i2, n0, q9, n6};
  assign n12 = 16'h2add >> {q8, i6, i5, n5};
  assign n13 = 16'ha3ba >> {i5, n10, n5, n3};
  assign n14 = 16'hca9e >> {i1, n0, n0, i4};
  assign n15 = 16'hb757 >> {i7, i3, n2, q8};
  assign n16 = 16'hefe5 >> {i6, n12, i6, n12};
  assign n17 = 16'h7ebf >> {n4, i8, i5, n16};
  assign n18 = 16'h74ff >> {i7, i8, n17, q8};
  assign n19 = 16'hbdac >> {i7, q9, n10, n5};
  assign n20 = 16'ha2ff >> {n5, i3, n3, i1};
  assign n21 = 16'h8bff >> {n17, n0, n10, n14};
  assign n22 = 16'h9139 >> {n4, n10, i3, n0};
  assign n23 = 16'hc968 >> {n6, n13, n0, n16};
  assign n24 = 16'h1fd3 >> {q9, n22, n17, n17};
  assign n25 = 16'h2b45 >> {n10, i0, q7, n4};
  assign n26 = 16'h3ad5 >> {i4, i6, i4, n16};
  assign n27 = 16'h8f4d >> {n2, n5, i8, q11};
  assign n28 = 16'hafc8 >> {n22, n12, q20, n0};
  assign n29 = 16'h7b82 >> {n1, n12, n16, n14};
  assign n30 = 16'h5853 >> {i0, n5, n14, n1};
  assign n31 = 16'hebc1 >> {n12, n22, n2, i7};
  assign n32 = 16'hb9c4 >> {q7, q20, n17, n5};
  assign n33 = 16'hc30c >> {n3, i0, n10, q20};
  assign n34 = 16'h7177 >> {q30, n24, n16, i3};
  assign n35 = 16'h6120 >> {n33, n0, q7, q27};
  assign n36 = 16'hde65 >> {i7, n3, n4, i4};
  assign n37 = 16'hf408 >> {i2, n12, q7, q27};
  assign n38 = 16'hd83e >> {i5, q19, q25, n10};
  assign n39 = 16'hb2c2 >> {i8, i0, n0, n12};
  assign n40 = 16'hcfc1 >> {q19, n13, i0, q25};
  assign n41 = 16'h6ca2 >> {i7, i7, n17, q20};
  assign n42 = 16'h6b5a >> {q38, q18, n35, q28};
  assign n43 = 16'hfbd9 >> {i5, n2, n10, i1};
  assign n44 = 16'h1d8b >> {i7, q21, n12, q36};
  assign n45 = 16'hc15a >> {n0, n44, n3, i0};
  assign n46 = 16'h88ec >> {q9, n3, n33, n35};
  assign n47 = 16'h8850 >> {i6, q20, n0, i0};
  assign n48 = 16'hfb09 >> {q34, n3, n29, q36};
  assign n49 = 16'h7841 >> {n42, i3, q30, q21};
  assign n50 = 16'ha778 >> {n32, n45, q26, n45};
  assign n51 = 16'h3a55 >> {i8, n24, n0, i8};
  assign n52 = 16'hea09 >> {q11, q23, n29, n33};
  assign n53 = 16'h6259 >> {n10, n12, n12, n40};
  assign n54 = 16'h4ab4 >> {n29, i5, n47, q19};
  assign n55 = 16'h7b97 >> {n1, q46, n41, q26};
  assign n56 = 16'ha8a0 >> {n16, n48, q30, i7};
  assign n57 = 16'hcca3 >> {n45, n6, i4, n4};
  assign n58 = 16'h7612 >> {q55, n13, n54, n49};
  assign n59 = 16'hda31 >> {q19, n16, n5, q36};
  assign n60 = 16'h27fe >> {q7, n56, q8, q23};
  assign n61 = 16'h0e94 >> {n2, n50, q51, n1};
  assign n62 = 16'hc4f4 >> {n3, n56, n29, q18};
  assign n63 = 16'h7f94 >> {q55, n56, n1, n22};
  assign n64 = 16'h71f3 >> {q62, n12, n16, q36};
  assign n65 = 16'h4a09 >> {q55, q18, q9, n44};
  assign n66 = 16'hd261 >> {n50, n37, q23, q36};
  always @(posedge clk0) begin if (n4) begin if (n0) q7 <= 1'b0; else q7 <= n7; end end
  always @(posedge clk0 or posedge n5) begin if (n5) q8 <= 1'b1; else begin q8 <= n8; end end
  always @(posedge clk0) begin if (q7) q9 <= 1'b0; else q9 <= n9; end
  always @(posedge clk0) begin if (i7) q11 <= n3; else q11 <= n11; end
  always @(negedge clk0) begin if (i3) begin q18 <= n18; end end
  always @(posedge clk0 or posedge i0) begin if (i0) q19 <= 1'b0; else begin q19 <= n19; end end
  always @(posedge clk0) begin if (i3) q20 <= n15; else q20 <= n20; end
  always @(posedge clk0) begin if (n16) begin q21 <= n21; end end
  always @(posedge clk0 or posedge i6) begin if (i6) q23 <= 1'b1; else begin if (n6) begin q23 <= n23; end end end
  always @(posedge clk0 or posedge n10) begin if (n10) q25 <= 1'b1; else begin if (i5) q25 <= 1'b0; else if (n10) q25 <= i3; else q25 <= n25; end end
  always @(posedge clk0) begin if (q25) begin if (n3) q26 <= q19; else q26 <= n26; end end
  always @(negedge clk0) begin if (n15) begin q27 <= n27; end end
  always @(posedge clk0) begin if (q18) begin if (n17) q28 <= 1'b0; else q28 <= n28; end end
  always @(posedge clk0 or posedge i1) begin if (i1) q30 <= 1'b0; else begin q30 <= n30; end end
  always @(posedge clk0 or posedge n3) begin if (n3) q34 <= 1'b1; else begin if (q23) q34 <= n4; else q34 <= n34; end end
  always @(posedge clk0 or posedge n16) begin if (n16) q36 <= 1'b0; else begin if (n14) begin q36 <= n36; end end end
  always @(posedge clk0) begin if (n24) q38 <= 1'b0; else q38 <= n38; end
  always @(posedge clk0) begin q43 <= n43; end
  always @(posedge clk0 or posedge n0) begin if (n0) q46 <= 1'b1; else begin if (n42) begin if (q38) q46 <= 1'b0; else q46 <= n46; end end end
  always @(negedge clk0) begin if (q18) q51 <= 1'b0; else if (n1) q51 <= n1; else q51 <= n51; end
  always @(posedge clk0 or posedge n5) begin if (n5) q55 <= 1'b0; else begin if (n37) q55 <= i4; else q55 <= n55; end end
  always @(posedge clk0 or posedge n0) begin if (n0) q59 <= 1'b0; else begin if (i4) q59 <= 1'b0; else q59 <= n59; end end
  always @(posedge clk0 or posedge n44) begin if (n44) q62 <= 1'b1; else begin if (n2) q62 <= 1'b0; else q62 <= n62; end end
  always @(posedge clk0 or posedge i0) begin if (i0) q63 <= 1'b1; else begin if (q9) begin if (n0) q63 <= 1'b0; else q63 <= n63; end end end
  always @(posedge clk0) begin if (n22) q65 <= 1'b0; else if (n44) q65 <= n5; else q65 <= n65; end
  always @(posedge clk0) begin q66 <= n66; end
  assign o0 = (^{n61, q46, q66, n53, q62, q28, n57});
  assign o1 = ~(^{q65, n52, q63, q34, q7, n31});
  assign o2 = (^{n29, n60, q55, q43, n40, n24});
  assign o3 = (^{n54, n56, n49, q25, n0, q18});
  assign o4 = (^{q30, q8, n47, n48, n32, n1});
  assign o5 = (^{q38, n17, n45, n39, q19, q59});
  assign o6 = ~(^{n3, n44, n6, n5, n33, n4});
  assign o7 = ~(^{n12, n15, n13, n37, q21, n16});
  assign o8 = (^{n14, q51, q11, n22, n35, n58});
  assign o9 = (^{q27, n50, n41, n42, q26, n2});
  assign o10 = (^{n64, q23, q36, n10, q20, q9});
endmodule
