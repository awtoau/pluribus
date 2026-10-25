module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, output o0, output o1, output o2, output o3, output o4, output o5);
  wire n0;
  reg q0;
  wire n1;
  wire n2;
  reg q2;
  wire n3;
  wire n4;
  wire n5;
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
  reg q14;
  wire n15;
  reg q15;
  wire n16;
  reg q16;
  wire n17;
  reg q17;
  wire n18;
  wire n19;
  wire n20;
  reg q20;
  wire n21;
  reg q21;
  wire n22;
  wire n23;
  wire n24;
  wire n25;
  wire n26;
  wire n27;
  wire n28;
  wire n29;
  wire n30;
  wire n31;
  reg q31;
  wire n32;
  wire n33;
  wire n34;
  wire n35;
  wire [3:0] s0;
  wire n37;
  wire n38;
  reg q38;
  wire n39;
  reg q39;
  wire n40;
  reg q40;
  wire n41;
  wire n42;
  wire n43;
  reg q43;
  wire [4:0] s1;
  wire n45;
  wire n46;
  wire n47;
  reg q47;
  wire n48;
  wire n49;
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
  wire n59;
  wire n60;
  wire n61;
  reg q61;
  wire n62;
  reg q62;
  wire n63;
  reg q63;
  wire n64;
  reg q64;
  wire n65;
  wire n66;
  reg q66;
  wire n67;
  wire n68;
  wire n69;
  wire n70;
  wire n71;
  reg q71;
  wire n72;
  wire n73;
  reg q73;
  wire n74;
  reg q74;
  wire n75;
  reg q75;
  wire n76;
  wire n77;
  reg q77;
  assign n0 = 16'h37b1 >> {i0, i10, i4, i7};
  assign n1 = 16'h2dbf >> {q0, i2, i5, i5};
  assign n2 = 16'hf92e >> {q0, i11, i8, i8};
  assign n3 = 16'h0bf8 >> {i6, i0, i3, i10};
  assign n4 = 16'h4cde >> {q2, i0, i9, i12};
  assign n5 = 16'h7b0e >> {i4, i9, n3, i8};
  assign n6 = 16'h916b >> {i11, i2, i3, i1};
  assign n7 = 16'ha149 >> {i4, i11, i9, n1};
  assign n8 = 16'h45e2 >> {n1, i12, i5, i4};
  assign n9 = 16'h678d >> {n1, n3, i1, i11};
  assign n10 = 16'h215d >> {n9, i9, i5, i6};
  assign n11 = 16'hd579 >> {n9, i0, i5, i12};
  assign n12 = 16'h2b60 >> {i8, i1, i8, i1};
  assign n13 = 16'hcf21 >> {n3, q10, q11, n12};
  assign n14 = 16'h38e0 >> {i2, i12, q10, q0};
  assign n15 = 16'h05ed >> {n12, i2, q2, n12};
  assign n16 = 16'h05d2 >> {q11, i11, i8, i8};
  assign n17 = 16'h3583 >> {q15, i2, n1, i1};
  assign n18 = 16'h5743 >> {i1, q11, n9, i5};
  assign n19 = 16'h1380 >> {q17, q10, q10, q14};
  assign n20 = 16'hbb20 >> {q17, q0, n5, i10};
  assign n21 = 16'h5ed3 >> {i6, n7, n18, n1};
  assign n22 = 16'hbfba >> {n9, q6, q2, i8};
  assign n23 = 16'h1640 >> {n19, n7, q0, n19};
  assign n24 = 16'h9ec3 >> {i8, n13, i7, q8};
  assign n25 = 16'h1485 >> {q11, q10, q20, q10};
  assign n26 = 16'h2865 >> {q8, i2, n24, n23};
  assign n27 = 16'hae2f >> {n3, n23, n7, q6};
  assign n28 = 16'hf56e >> {n24, n9, i1, q2};
  assign n29 = 16'h6f1a >> {n7, i8, q0, n7};
  assign n30 = 16'h0382 >> {n23, i8, n18, q10};
  assign n31 = 16'hf087 >> {q10, i6, i4, q16};
  assign n32 = 16'h14eb >> {q16, n26, q6, i8};
  assign n33 = 16'h5ae6 >> {q0, q31, i6, n23};
  assign n34 = 16'h55ce >> {n4, q15, q17, n26};
  assign n35 = 16'h2cc3 >> {i9, n3, q6, i8};
  assign s0 = {1'b0, n26, n33, i3} + {1'b0, q16, n13, i2};
  assign n37 = 16'hc10f >> {n30, q14, n18, q10};
  assign n38 = 16'h1cd1 >> {n27, q14, n27, n29};
  assign n39 = 16'h1807 >> {s0[1], q31, n25, n27};
  assign n40 = 16'h6321 >> {n5, q15, i11, q17};
  assign n41 = 16'hd651 >> {q0, i1, i12, n37};
  assign n42 = 16'h905e >> {i6, i0, n35, n4};
  assign n43 = 16'hfd88 >> {q39, q10, n22, n26};
  assign s1 = {1'b0, i8, n9, q14, q16} - {1'b0, n23, i3, n18, i7};
  assign n45 = 16'hd748 >> {n5, n26, n22, s1[0]};
  assign n46 = 16'h591c >> {q16, q31, q10, n3};
  assign n47 = 16'h464c >> {q39, s1[4], n25, i3};
  assign n48 = 16'ha2c6 >> {i3, q20, n3, n42};
  assign n49 = 16'h6b30 >> {q43, n48, n12, i9};
  assign n50 = 16'he1e3 >> {n34, n7, s1[4], s0[3]};
  assign n51 = 16'h26b5 >> {n13, n27, n23, q15};
  assign n52 = 16'hf59d >> {s0[3], q20, q38, n34};
  assign n53 = 16'h5230 >> {n45, q8, s1[3], n28};
  assign n54 = 16'hb406 >> {n46, s1[3], q38, n12};
  assign n55 = 16'hbc3c >> {s0[2], s0[1], n12, s1[3]};
  assign n56 = 16'h050d >> {s0[3], i0, n52, n28};
  assign n57 = 16'h4130 >> {n37, s0[0], n30, n27};
  assign n58 = 16'h5bd4 >> {n54, n48, s0[2], s1[0]};
  assign n59 = 16'h2946 >> {n29, n50, q6, n26};
  assign n60 = 16'h0b8a >> {n55, n28, n22, s1[4]};
  assign n61 = 16'hb706 >> {n12, n32, n27, n35};
  assign n62 = 16'h47bb >> {n13, q14, q17, n23};
  assign n63 = 16'hbb96 >> {q39, s1[0], q14, n37};
  assign n64 = 16'h16b7 >> {n12, n13, s0[0], q62};
  assign n65 = 16'h2254 >> {q38, q20, n60, n19};
  assign n66 = 16'hadf5 >> {n27, s0[3], s0[2], n54};
  assign n67 = 16'hb034 >> {n50, n27, n52, n65};
  assign n68 = 16'hea4d >> {n51, q62, q66, q62};
  assign n69 = 16'hb633 >> {n34, s1[4], n42, n68};
  assign n70 = 16'hcfc2 >> {n59, q57, q38, n53};
  assign n71 = 16'hbebd >> {n55, q64, q40, n48};
  assign n72 = 16'h5961 >> {q61, s1[2], s0[3], q21};
  assign n73 = 16'h536a >> {n28, n67, q38, n29};
  assign n74 = 16'h512e >> {n56, n37, q39, q8};
  assign n75 = 16'hcc3b >> {n37, n33, q39, n42};
  assign n76 = 16'hcead >> {n50, n72, n54, q43};
  assign n77 = 16'h4023 >> {q57, q31, s0[1], n28};
  always @(negedge clk0) begin if (i11) q0 <= i12; else q0 <= n0; end
  always @(negedge clk0) begin if (i4) begin if (i9) q2 <= 1'b0; else q2 <= n2; end end
  always @(negedge clk0) begin if (i2) q6 <= i2; else q6 <= n6; end
  always @(posedge clk0) begin if (i11) q8 <= n3; else q8 <= n8; end
  always @(posedge clk0) begin if (i12) begin if (i0) q10 <= i4; else q10 <= n10; end end
  always @(posedge clk0) begin if (n7) q11 <= 1'b0; else q11 <= n11; end
  always @(posedge clk0 or posedge i0) begin if (i0) q14 <= 1'b0; else begin if (i8) q14 <= i1; else q14 <= n14; end end
  always @(posedge clk0) begin q15 <= n15; end
  always @(posedge clk0) begin if (i4) q16 <= 1'b0; else q16 <= n16; end
  always @(posedge clk0 or posedge i5) begin if (i5) q17 <= 1'b1; else begin if (i11) q17 <= n9; else q17 <= n17; end end
  always @(posedge clk0) begin if (n12) q20 <= 1'b0; else q20 <= n20; end
  always @(posedge clk0 or posedge i6) begin if (i6) q21 <= 1'b1; else begin if (q2) q21 <= 1'b0; else q21 <= n21; end end
  always @(posedge clk0) begin if (q10) begin q31 <= n31; end end
  always @(posedge clk0) begin if (n4) q38 <= n28; else q38 <= n38; end
  always @(posedge clk0 or posedge q20) begin if (q20) q39 <= 1'b1; else begin if (s0[0]) q39 <= q8; else q39 <= n39; end end
  always @(posedge clk0 or posedge n13) begin if (n13) q40 <= 1'b0; else begin if (q10) q40 <= q20; else q40 <= n40; end end
  always @(posedge clk0) begin if (i10) begin if (i12) q43 <= 1'b0; else q43 <= n43; end end
  always @(posedge clk0) begin q47 <= n47; end
  always @(posedge clk0) begin if (n1) q57 <= 1'b0; else if (n4) q57 <= n4; else q57 <= n57; end
  always @(posedge clk0) begin if (q15) begin q61 <= n61; end end
  always @(negedge clk0) begin if (q38) q62 <= n59; else q62 <= n62; end
  always @(posedge clk0) begin if (q38) q63 <= n56; else q63 <= n63; end
  always @(posedge clk0) begin q64 <= n64; end
  always @(posedge clk0) begin q66 <= n66; end
  always @(posedge clk0) begin q71 <= n71; end
  always @(negedge clk0) begin if (i5) begin if (n27) q73 <= 1'b0; else q73 <= n73; end end
  always @(posedge clk0 or posedge i7) begin if (i7) q74 <= 1'b1; else begin if (n34) begin if (n53) q74 <= i0; else q74 <= n74; end end end
  always @(posedge clk0) begin if (n5) q75 <= q2; else q75 <= n75; end
  always @(posedge clk0) begin q77 <= n77; end
  assign o0 = ~(^{s1[1], s0[1], n69, q75, n45, n29, n5, q16, q17, n34, n18, q62, n4, q31, q6});
  assign o1 = (^{q38, n70, n35, q66, n46, n48, n24, n59, n7, n28, q43, s1[0], q15, n26});
  assign o2 = (^{n56, n60, q64, q2, n52, n53, n12, s0[3], n58, q57, n30, q73, q14, n32});
  assign o3 = (^{q71, n76, q11, q40, n23, s0[2], n9, n22, n33, q21, n25, q77, n72, q61});
  assign o4 = ~(^{q74, n51, n55, q63, n65, n54, q39, q20, q8, s1[3], n41, q47, n19, n13});
  assign o5 = ~(^{n1, n50, q10, n67, s1[2], n68, n49, n42, s0[0], n27, s1[4], q0, n3, n37});
endmodule
