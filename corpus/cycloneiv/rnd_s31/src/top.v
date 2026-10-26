module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10, output o11, output o12);
  wire n0;
  reg q0;
  wire n1;
  wire n2;
  wire n3;
  wire n4;
  reg q4;
  wire n5;
  wire n6;
  wire n7;
  reg q7;
  wire n8;
  wire n9;
  reg q9;
  wire n10;
  wire n11;
  wire n12;
  reg q12;
  wire n13;
  reg q13;
  wire n14;
  reg q14;
  wire n15;
  wire n16;
  wire n17;
  reg q17;
  wire n18;
  wire n19;
  wire n20;
  reg q20;
  wire n21;
  wire n22;
  wire n23;
  reg q23;
  wire n24;
  reg q24;
  wire n25;
  reg q25;
  wire n26;
  wire n27;
  reg q27;
  wire n28;
  reg q28;
  wire n29;
  wire n30;
  wire n31;
  wire n32;
  reg q32;
  wire n33;
  reg q33;
  wire n34;
  wire n35;
  wire n36;
  wire n37;
  wire n38;
  reg q38;
  wire n39;
  reg q39;
  wire n40;
  wire n41;
  assign n0 = 16'he5f1 >> {i10, i10, i13, i12};
  assign n1 = 16'h8c59 >> {i4, i4, i1, i6};
  assign n2 = 16'h5dee >> {i12, q0, i4, i3};
  assign n3 = 16'hd64c >> {i6, i6, i8, i6};
  assign n4 = 16'h0ca2 >> {i12, n3, i7, i4};
  assign n5 = 16'h67b9 >> {i1, i8, i3, q0};
  assign n6 = 16'hf252 >> {n3, n1, q0, i3};
  assign n7 = 16'hcf78 >> {i10, i0, i10, q4};
  assign n8 = 16'hbb1c >> {i6, i11, q4, n3};
  assign n9 = 16'h0fe4 >> {n8, n2, i6, q7};
  assign n10 = 16'hc52f >> {i4, i13, n5, i3};
  assign n11 = 16'h9804 >> {n1, i6, n10, n6};
  assign n12 = 16'hafa0 >> {n10, n6, q9, q9};
  assign n13 = 16'h8c3a >> {i7, n1, i8, i0};
  assign n14 = 16'haf1e >> {n10, n3, i4, i7};
  assign n15 = 16'hfef8 >> {n1, n10, i7, i4};
  assign n16 = 16'hbe7e >> {q13, q13, n6, n10};
  assign n17 = 16'h592a >> {q12, i5, n3, q4};
  assign n18 = 16'h26fc >> {i11, n16, n11, i4};
  assign n19 = 16'h12bf >> {n6, n2, n11, i7};
  assign n20 = 16'hd98b >> {i6, n3, n19, n8};
  assign n21 = 16'hf410 >> {i11, q0, i7, i1};
  assign n22 = 16'h9c8d >> {i11, n16, q9, i8};
  assign n23 = 16'h3167 >> {q4, q7, i5, n21};
  assign n24 = 16'h29b2 >> {i6, n6, n22, n6};
  assign n25 = 16'hd1ae >> {n16, n19, i11, n1};
  assign n26 = 16'h215e >> {i13, q23, q7, n3};
  assign n27 = 16'h38f5 >> {n2, n1, n15, i1};
  assign n28 = 16'h5d3f >> {q12, i6, n6, i11};
  assign n29 = 16'hff10 >> {i8, q12, n10, n6};
  assign n30 = 16'h5b6c >> {q4, n8, i2, q24};
  assign n31 = 16'he4fc >> {n19, n15, i3, q7};
  assign n32 = 16'hd7e7 >> {i3, i4, n21, n2};
  assign n33 = 16'h6620 >> {i9, i8, n26, n21};
  assign n34 = 16'h41c6 >> {n5, q24, q13, i7};
  assign n35 = 16'h4d48 >> {i7, n22, q32, n19};
  assign n36 = 16'h58cf >> {i1, q4, q12, n34};
  assign n37 = 16'h8d69 >> {q25, n35, n16, q32};
  assign n38 = 16'h9903 >> {i8, q0, n35, q4};
  assign n39 = 16'h5c0c >> {n34, i12, n8, q33};
  assign n40 = 16'h98db >> {q39, n3, n15, n8};
  assign n41 = 16'hfee7 >> {i10, i3, n34, i0};
  always @(posedge clk0) begin if (i3) begin q0 <= n0; end end
  always @(posedge clk0 or posedge i5) begin if (i5) q4 <= 1'b0; else begin if (i9) begin q4 <= n4; end end end
  always @(posedge clk1) begin if (n3) q7 <= i12; else q7 <= n7; end
  always @(posedge clk0) begin if (i3) q9 <= 1'b0; else q9 <= n9; end
  always @(posedge clk1) begin if (q9) begin if (q0) q12 <= 1'b0; else q12 <= n12; end end
  always @(posedge clk0 or posedge n6) begin if (n6) q13 <= 1'b0; else begin q13 <= n13; end end
  always @(posedge clk0 or posedge n5) begin if (n5) q14 <= 1'b0; else begin if (i1) q14 <= q0; else q14 <= n14; end end
  always @(posedge clk0) begin if (i0) begin if (q4) q17 <= 1'b0; else q17 <= n17; end end
  always @(posedge clk0) begin if (q4) q20 <= q14; else q20 <= n20; end
  always @(posedge clk1) begin q23 <= n23; end
  always @(posedge clk0 or posedge q0) begin if (q0) q24 <= 1'b1; else begin if (n8) begin if (i9) q24 <= 1'b0; else q24 <= n24; end end end
  always @(posedge clk1) begin q25 <= n25; end
  always @(posedge clk1 or posedge i7) begin if (i7) q27 <= 1'b0; else begin if (q0) begin if (q12) q27 <= 1'b0; else q27 <= n27; end end end
  always @(posedge clk1) begin if (i11) q28 <= q0; else q28 <= n28; end
  always @(posedge clk0) begin if (n16) begin q32 <= n32; end end
  always @(posedge clk1) begin q33 <= n33; end
  always @(posedge clk1) begin if (i11) begin q38 <= n38; end end
  always @(posedge clk0 or posedge n8) begin if (n8) q39 <= 1'b0; else begin if (n15) begin q39 <= n39; end end end
  assign o0 = ~(^{q0, q7, q28, q32});
  assign o1 = (^{n31, n29, n26, n41});
  assign o2 = (^{q17, q38, n34, n8});
  assign o3 = (^{n19, n21, n16});
  assign o4 = (^{n6, q12, n2});
  assign o5 = (^{n18, q25, n30});
  assign o6 = ~(^{q27, n5, n36});
  assign o7 = (^{n11, n22, n37});
  assign o8 = (^{q24, n15, q4});
  assign o9 = ~(^{q33, n40, n35});
  assign o10 = (^{q20, q14, q23});
  assign o11 = ~(^{n1, n3, q13});
  assign o12 = (^{n10, q39, q9});
endmodule
