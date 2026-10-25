module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, input i18, input i19, input i20, input i21, input i22, input i23, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9);
  wire n0;
  wire n1;
  wire n2;
  wire n3;
  reg q3;
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
  wire n20;
  wire n21;
  wire n22;
  assign n0 = 16'h8473 >> {i3, i17, i0, i9};
  assign n1 = 16'h59be >> {i19, i6, i12, n0};
  assign n2 = 16'h9675 >> {i11, i14, n1, i17};
  assign n3 = 16'h1959 >> {i20, i3, i23, i1};
  assign n4 = 16'h86f3 >> {i10, i4, i3, i1};
  assign n5 = 16'hf584 >> {i23, i11, i5, i13};
  assign n6 = 16'h2707 >> {i8, i15, i12, i5};
  assign n7 = 16'h367c >> {i23, i23, n0, i19};
  assign n8 = 16'h8198 >> {i7, n2, i23, i3};
  assign n9 = 16'h8c3d >> {i2, i12, n2, i20};
  assign n10 = 16'hbf0b >> {n8, i5, n0, n5};
  assign n11 = 16'ha672 >> {n5, i10, i21, i2};
  assign n12 = 16'h195e >> {i14, i2, q9, n2};
  assign n13 = 16'h894d >> {i21, n6, i9, i20};
  assign n14 = 16'hb8f6 >> {n8, n10, i21, i21};
  assign n15 = 16'hdeee >> {n0, n2, i0, i14};
  assign n16 = 16'hd8a8 >> {i0, i13, i11, n0};
  assign n17 = 16'h02e4 >> {i17, i13, i13, n15};
  assign n18 = 16'h51e7 >> {i18, i23, i8, n12};
  assign n19 = 16'h6759 >> {q9, n2, n8, i3};
  assign n20 = 16'h9210 >> {i20, i19, i2, n2};
  assign n21 = 16'h3d4a >> {i8, i18, n8, i15};
  assign n22 = 16'hc7ae >> {n21, n19, n10, n2};
  always @(posedge clk0) begin q3 <= n3; end
  always @(posedge clk0) begin if (i13) q4 <= i9; else q4 <= n4; end
  always @(posedge clk0) begin q7 <= n7; end
  always @(posedge clk0 or posedge i20) begin if (i20) q9 <= 1'b0; else begin if (i13) q9 <= i19; else q9 <= n9; end end
  always @(posedge clk0) begin if (i3) q11 <= 1'b0; else q11 <= n11; end
  always @(posedge clk0 or posedge i5) begin if (i5) q18 <= 1'b0; else begin if (i22) begin q18 <= n18; end end end
  assign o0 = ~(^{n1, n6, n0});
  assign o1 = (^{n22, n20, q7});
  assign o2 = (^{n19, q11, n13});
  assign o3 = (^{n15, n14});
  assign o4 = (^{q18, n16});
  assign o5 = (^{n2, n21});
  assign o6 = ~(^{n12, n5});
  assign o7 = ~(^{n17, q4});
  assign o8 = (^{n8, q3});
  assign o9 = (^{q9, n10});
endmodule
