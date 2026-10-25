module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, output o0, output o1, output o2, output o3, output o4, output o5);
  wire n0;
  wire n1;
  reg q1;
  wire n2;
  wire n3;
  wire n4;
  wire n5;
  reg q5;
  wire n6;
  reg q6;
  wire n7;
  reg q7;
  wire n8;
  wire n9;
  wire n10;
  wire n11;
  reg q11;
  wire n12;
  reg q12;
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
  reg q18;
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
  wire n26;
  wire n27;
  wire n28;
  wire n29;
  reg q29;
  wire n30;
  wire n31;
  wire n32;
  assign n0 = 16'h596d >> {i0, i3, i4, i10};
  assign n1 = 16'h4079 >> {i0, i10, i12, i4};
  assign n2 = 16'he809 >> {i9, i13, i7, n0};
  assign n3 = 16'h637f >> {i9, i1, q1, i13};
  assign n4 = 16'h8f00 >> {i9, i4, i7, i13};
  assign n5 = 16'h71c0 >> {n3, n0, n3, i15};
  assign n6 = 16'hcd20 >> {i13, i2, q5, i11};
  assign n7 = 16'hf718 >> {i7, i2, i12, i1};
  assign n8 = 16'h12af >> {i9, n0, n4, i3};
  assign n9 = 16'hcab9 >> {q6, i12, i15, i3};
  assign n10 = 16'ha0e1 >> {q5, i2, i15, n8};
  assign n11 = 16'h2df4 >> {n0, i4, n3, n3};
  assign n12 = 16'h88a8 >> {i4, i11, i3, q6};
  assign n13 = 16'hfe79 >> {i11, i15, n4, i2};
  assign n14 = 16'h9fae >> {i8, n10, i9, i7};
  assign n15 = 16'hd0e5 >> {i13, i15, i7, q12};
  assign n16 = 16'h322c >> {i1, i9, n10, i7};
  assign n17 = 16'h06e5 >> {i6, q6, i13, q5};
  assign n18 = 16'h81b8 >> {i11, n8, q16, i7};
  assign n19 = 16'h18d8 >> {i9, n4, i5, q17};
  assign n20 = 16'h0f0b >> {n8, q5, i10, i7};
  assign n21 = 16'hf9b4 >> {n10, q7, q7, q1};
  assign n22 = 16'h2798 >> {q17, n19, i8, i15};
  assign n23 = 16'hba0b >> {q12, i12, q5, n2};
  assign n24 = 16'h277f >> {n0, q6, n21, q16};
  assign n25 = 16'h1088 >> {i11, q7, i16, i8};
  assign n26 = 16'he193 >> {n8, q17, n22, n0};
  assign n27 = 16'hb9b6 >> {n4, i13, q17, q18};
  assign n28 = 16'h9f5e >> {q18, i1, n9, n4};
  assign n29 = 16'hd0d5 >> {i6, n19, q23, n19};
  assign n30 = 16'h9d46 >> {n26, i0, i16, i2};
  assign n31 = 16'h3058 >> {i13, i8, n19, q1};
  assign n32 = 16'h5233 >> {q5, i16, q23, n13};
  always @(posedge clk1 or posedge i1) begin if (i1) q1 <= 1'b1; else begin if (i14) q1 <= 1'b0; else q1 <= n1; end end
  always @(posedge clk0) begin q5 <= n5; end
  always @(posedge clk0) begin if (i2) q6 <= i5; else q6 <= n6; end
  always @(posedge clk0) begin if (i7) q7 <= i15; else q7 <= n7; end
  always @(negedge clk1 or posedge i8) begin if (i8) q11 <= 1'b0; else begin if (i7) begin if (i12) q11 <= 1'b0; else q11 <= n11; end end end
  always @(posedge clk0 or posedge i1) begin if (i1) q12 <= 1'b0; else begin if (n4) q12 <= q11; else q12 <= n12; end end
  always @(posedge clk0 or posedge n2) begin if (n2) q14 <= 1'b0; else begin if (n4) begin if (i2) q14 <= 1'b0; else q14 <= n14; end end end
  always @(posedge clk1 or posedge n0) begin if (n0) q15 <= 1'b0; else begin if (i13) begin if (q11) q15 <= 1'b0; else q15 <= n15; end end end
  always @(posedge clk0) begin if (i16) q16 <= 1'b0; else q16 <= n16; end
  always @(posedge clk0 or posedge i13) begin if (i13) q17 <= 1'b1; else begin q17 <= n17; end end
  always @(posedge clk0) begin q18 <= n18; end
  always @(posedge clk0 or posedge i8) begin if (i8) q20 <= 1'b1; else begin if (q14) begin if (i10) q20 <= 1'b0; else if (q15) q20 <= n2; else q20 <= n20; end end end
  always @(posedge clk0 or posedge i7) begin if (i7) q23 <= 1'b0; else begin q23 <= n23; end end
  always @(negedge clk1 or posedge i4) begin if (i4) q24 <= 1'b0; else begin q24 <= n24; end end
  always @(posedge clk1 or posedge i3) begin if (i3) q29 <= 1'b0; else begin if (n8) q29 <= q11; else q29 <= n29; end end
  assign o0 = (^{n27, q5, n32, q29, q24, n4});
  assign o1 = (^{q1, q17, n26, q7, n8, n22});
  assign o2 = (^{n2, q6, q18, n30, q20, n13});
  assign o3 = (^{q16, n25, n19, n31, q12});
  assign o4 = (^{n9, q11, q14, n3, n21});
  assign o5 = (^{n28, q23, q15, n0, n10});
endmodule
