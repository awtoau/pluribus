module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7);
  wire n0;
  reg q0;
  wire n1;
  wire n2;
  wire n3;
  reg q3;
  wire n4;
  wire n5;
  wire n6;
  wire n7;
  wire n8;
  wire n9;
  wire n10;
  reg q10;
  wire n11;
  wire n12;
  wire n13;
  reg q13;
  wire n14;
  wire n15;
  reg q15;
  wire n16;
  wire n17;
  wire n18;
  reg q18;
  wire n19;
  wire n20;
  wire n21;
  wire n22;
  reg q22;
  wire n23;
  wire n24;
  wire n25;
  reg q25;
  wire n26;
  wire n27;
  reg q27;
  wire n28;
  wire n29;
  wire n30;
  wire n31;
  reg q31;
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
  reg q40;
  wire n41;
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
  wire n54;
  wire n55;
  wire n56;
  wire n57;
  reg q57;
  wire n58;
  reg q58;
  wire n59;
  assign n0 = 16'hc302 >> {i8, i9, i0, i11};
  assign n1 = 16'h7d70 >> {i9, i8, i9, i8};
  assign n2 = 16'hd36d >> {i1, i3, i4, q0};
  assign n3 = 16'hbed0 >> {n2, i8, i8, q0};
  assign n4 = 16'h57f1 >> {i2, i5, i3, i0};
  assign n5 = 16'ha183 >> {i7, q3, q0, i3};
  assign n6 = 16'h9f91 >> {i8, i4, i9, i9};
  assign n7 = 16'h56f9 >> {i10, i10, n2, n5};
  assign n8 = 16'h676f >> {q3, i4, i8, i6};
  assign n9 = 16'h68d7 >> {n6, i3, n4, i10};
  assign n10 = 16'hf5d6 >> {i2, i9, i0, i11};
  assign n11 = 16'h0245 >> {i7, n5, i10, n7};
  assign n12 = 16'h8146 >> {n6, n6, q10, n2};
  assign n13 = 16'h002d >> {i5, i4, n4, i4};
  assign n14 = 16'hdd37 >> {n2, n2, i5, i6};
  assign n15 = 16'hf5c8 >> {q10, n7, i5, i7};
  assign n16 = 16'ha756 >> {i10, i4, n4, i1};
  assign n17 = 16'h54b1 >> {n7, i10, i9, i8};
  assign n18 = 16'h2e3f >> {n12, q3, i11, n11};
  assign n19 = 16'h647c >> {n2, i4, n12, q15};
  assign n20 = 16'hb351 >> {i11, i11, n7, n6};
  assign n21 = 16'hf273 >> {i2, q3, n6, n8};
  assign n22 = 16'hfe01 >> {n16, i2, n20, n14};
  assign n23 = 16'hc13f >> {i0, n9, n7, q22};
  assign n24 = 16'h9ca8 >> {i6, i2, i8, i9};
  assign n25 = 16'h596b >> {n24, i6, n16, n12};
  assign n26 = 16'hc0ae >> {i8, i9, n12, q3};
  assign n27 = 16'h67b2 >> {n5, n12, n1, q15};
  assign n28 = 16'h1682 >> {n14, q22, i5, i2};
  assign n29 = 16'h6985 >> {n20, n1, i3, q15};
  assign n30 = 16'hcca8 >> {n24, n23, n9, i6};
  assign n31 = 16'h1cee >> {q22, n16, n30, n29};
  assign n32 = 16'hf66e >> {q10, n11, n23, n12};
  assign n33 = 16'h8ae3 >> {n17, n5, n14, i3};
  assign n34 = 16'h7f64 >> {i1, i3, n23, q18};
  assign n35 = 16'h09e1 >> {n14, n16, q34, q22};
  assign n36 = 16'habf2 >> {n11, n26, i9, n32};
  assign n37 = 16'he8b1 >> {n24, n30, q36, i7};
  assign n38 = 16'hde44 >> {q36, i9, n28, n7};
  assign n39 = 16'h0295 >> {n32, q22, i0, q0};
  assign n40 = 16'h58fd >> {i6, q13, i1, n26};
  assign n41 = 16'h3dc5 >> {n9, n20, i8, n8};
  assign n42 = 16'h79b1 >> {i1, n4, q10, n1};
  assign n43 = 16'h5990 >> {n4, n30, n32, q22};
  assign n44 = 16'h2a31 >> {n39, n17, n9, q15};
  assign n45 = 16'hf390 >> {n4, n11, i1, n23};
  assign n46 = 16'hea5e >> {n45, i10, n12, i0};
  assign n47 = 16'hf304 >> {i3, q34, q31, q13};
  assign n48 = 16'h0e00 >> {n43, n45, n28, n8};
  assign n49 = 16'h906f >> {n37, n2, i8, i7};
  assign n50 = 16'h5d5f >> {n16, q49, n9, n44};
  assign n51 = 16'h88b5 >> {n5, n28, q25, q0};
  assign n52 = 16'ha14a >> {n45, n9, n23, n46};
  assign n53 = 16'hcabc >> {n44, n23, q49, n12};
  assign n54 = 16'h27d1 >> {n4, q38, n37, n23};
  assign n55 = 16'h6434 >> {q15, n24, n39, n2};
  assign n56 = 16'hb931 >> {i2, n55, i10, n47};
  assign n57 = 16'hfae0 >> {n1, n6, n47, n20};
  assign n58 = 16'h11c9 >> {q18, n47, n19, i10};
  assign n59 = 16'h22c2 >> {q15, q10, n29, n32};
  always @(negedge clk1 or posedge i2) begin if (i2) q0 <= 1'b1; else begin if (i6) q0 <= 1'b0; else q0 <= n0; end end
  always @(posedge clk1) begin if (i7) begin if (i5) q3 <= 1'b0; else q3 <= n3; end end
  always @(posedge clk1 or posedge n4) begin if (n4) q10 <= 1'b0; else begin if (n9) q10 <= 1'b0; else if (i1) q10 <= n9; else q10 <= n10; end end
  always @(posedge clk1) begin if (n7) begin q13 <= n13; end end
  always @(posedge clk1) begin if (n11) begin if (i6) q15 <= n7; else q15 <= n15; end end
  always @(posedge clk0 or posedge i4) begin if (i4) q18 <= 1'b1; else begin if (i5) begin q18 <= n18; end end end
  always @(posedge clk1) begin if (i9) q22 <= 1'b0; else if (n9) q22 <= i0; else q22 <= n22; end
  always @(negedge clk1) begin if (i0) q25 <= i5; else q25 <= n25; end
  always @(posedge clk0 or posedge n20) begin if (n20) q27 <= 1'b0; else begin if (i2) begin q27 <= n27; end end end
  always @(posedge clk1) begin if (n5) begin q31 <= n31; end end
  always @(posedge clk0 or posedge q13) begin if (q13) q34 <= 1'b0; else begin if (n11) q34 <= 1'b0; else q34 <= n34; end end
  always @(posedge clk1 or posedge n28) begin if (n28) q36 <= 1'b0; else begin if (i8) q36 <= n17; else q36 <= n36; end end
  always @(posedge clk0) begin if (q34) begin if (i1) q38 <= n30; else q38 <= n38; end end
  always @(posedge clk1) begin q40 <= n40; end
  always @(posedge clk0 or posedge n32) begin if (n32) q49 <= 1'b1; else begin if (i1) begin q49 <= n49; end end end
  always @(posedge clk0 or posedge n45) begin if (n45) q57 <= 1'b0; else begin q57 <= n57; end end
  always @(posedge clk1) begin q58 <= n58; end
  assign o0 = (^{n30, n51, n50, q3, n7, n53, q57, n11});
  assign o1 = (^{n28, q13, n56, n2, q22, n54, q58, q0});
  assign o2 = (^{n59, q15, n26, q36, n29, q25, n41, n48});
  assign o3 = (^{q10, n35, n9, n12, n4, n19, q38, n45});
  assign o4 = (^{n5, n8, n6, n43, n52, q49, n33});
  assign o5 = ~(^{n32, n24, q40, n47, n14, n21, n42});
  assign o6 = (^{q27, n44, n39, n37, n17, n55, n16});
  assign o7 = (^{n20, n46, n23, q34, n1, q31, q18});
endmodule
