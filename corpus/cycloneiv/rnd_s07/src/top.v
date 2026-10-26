module top(input clk0, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, input i12, input i13, input i14, input i15, input i16, input i17, input i18, input i19, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9, output o10);
  wire n0;
  wire n1;
  wire n2;
  reg q2;
  wire n3;
  wire n4;
  wire n5;
  reg q5;
  wire [11:0] s0;
  wire n7;
  wire n8;
  wire n9;
  wire n10;
  reg q10;
  wire n11;
  wire n12;
  reg q12;
  wire n13;
  wire n14;
  wire [11:0] s1;
  wire n16;
  wire n17;
  wire n18;
  wire n19;
  wire n20;
  wire [9:0] s2;
  wire n22;
  reg q22;
  wire n23;
  reg q23;
  wire n24;
  wire n25;
  reg q25;
  wire n26;
  wire n27;
  assign n0 = 16'h5c16 >> {i4, i10, i19, i14};
  assign n1 = 16'hf1b6 >> {i19, i15, n0, i8};
  assign n2 = 16'h7fbe >> {i2, i3, n0, i12};
  assign n3 = 16'hb0cb >> {i10, i9, i7, i5};
  assign n4 = 16'h766c >> {i19, i17, i17, i15};
  assign n5 = 16'hf1de >> {q2, i1, i6, i12};
  assign s0 = {1'b0, n0, i16, q5, i0, i13, i0, q5, i12, i15, i19, n3} + {1'b0, i13, n3, i7, i11, i14, i6, i1, n3, i18, i18, i12};
  assign n7 = 16'h2b5f >> {s0[5], i15, i9, i6};
  assign n8 = 16'h21c0 >> {i0, q5, i13, i16};
  assign n9 = 16'hd6ed >> {i6, q2, i3, s0[0]};
  assign n10 = 16'ha1b9 >> {i17, i5, i15, i0};
  assign n11 = 16'had0b >> {i1, i14, i14, i0};
  assign n12 = 16'h6d6f >> {s0[8], n0, i15, i13};
  assign n13 = 16'h37b5 >> {n3, s0[7], i12, i18};
  assign n14 = 16'h055a >> {s0[8], n9, n11, q10};
  assign s1 = {1'b0, i18, n9, q10, n13, i2, i5, s0[11], i9, s0[0], s0[8], n14} - {1'b0, s0[0], n14, s0[6], i16, s0[11], q5, n14, i15, i15, s0[4], s0[11]};
  assign n16 = 16'h175e >> {s0[3], i6, s1[2], i10};
  assign n17 = 16'hda51 >> {i3, s1[3], s0[1], s1[3]};
  assign n18 = 16'h39c5 >> {i16, i12, i19, i8};
  assign n19 = 16'h467b >> {s1[10], s1[3], s1[8], s0[11]};
  assign n20 = 16'hd8f2 >> {s1[1], i18, i11, s0[1]};
  assign s2 = {1'b0, s0[1], n20, n1, i2, i13, s0[8], n3, s0[6], n9} + {1'b0, q5, s1[8], i15, i6, s1[0], i11, i12, n0, i3};
  assign n22 = 16'h86fb >> {s0[6], n16, q10, s0[10]};
  assign n23 = 16'ha561 >> {i0, s0[11], n17, n8};
  assign n24 = 16'h45e5 >> {s1[10], s1[10], s1[3], s2[6]};
  assign n25 = 16'hfaf3 >> {n14, s0[9], i3, q2};
  assign n26 = 16'ha52a >> {s0[5], n9, n13, s2[5]};
  assign n27 = 16'h4b5b >> {n3, q22, s2[6], i5};
  always @(posedge clk0) begin q2 <= n2; end
  always @(posedge clk0 or posedge i17) begin if (i17) q5 <= 1'b0; else begin q5 <= n5; end end
  always @(posedge clk0) begin q10 <= n10; end
  always @(posedge clk0 or posedge s0[2]) begin if (s0[2]) q12 <= 1'b1; else begin q12 <= n12; end end
  always @(posedge clk0 or posedge n17) begin if (n17) q22 <= 1'b0; else begin if (i4) begin if (i7) q22 <= 1'b0; else q22 <= n22; end end end
  always @(posedge clk0) begin if (i18) begin q23 <= n23; end end
  always @(negedge clk0) begin q25 <= n25; end
  assign o0 = (^{s0[0], s0[5], s2[0], n8, q25, n26});
  assign o1 = (^{q12, n24, s0[4], n7, s2[7], s1[5]});
  assign o2 = (^{s1[2], s1[11], s2[6], s2[1], q23, s2[3]});
  assign o3 = (^{s2[2], s1[3], s0[2], s1[7], s2[5], s1[10]});
  assign o4 = (^{s0[8], n0, s1[6], s0[1], n14});
  assign o5 = (^{n13, s1[8], s0[3], s2[4], n4});
  assign o6 = (^{s2[9], n18, n16, q22, n17});
  assign o7 = (^{q10, n20, n3, s0[6], n19});
  assign o8 = (^{n1, s0[9], s2[8], n9, q5});
  assign o9 = (^{s1[9], s0[10], s0[11], q2, s1[0]});
  assign o10 = (^{n27, s0[7], n11, s1[1], s1[4]});
endmodule
