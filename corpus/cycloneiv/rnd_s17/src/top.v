module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, input i9, input i10, input i11, output o0, output o1, output o2, output o3, output o4);
  wire n0;
  wire n1;
  wire n2;
  reg q2;
  wire n3;
  wire n4;
  reg q4;
  wire n5;
  wire n6;
  wire n7;
  wire [10:0] s0;
  wire n9;
  reg q9;
  wire n10;
  wire [7:0] s1;
  wire n12;
  wire n13;
  wire n14;
  wire n15;
  reg q15;
  wire n16;
  wire n17;
  wire n18;
  wire n19;
  wire n20;
  reg q20;
  wire n21;
  wire n22;
  reg q22;
  wire n23;
  reg q23;
  wire n24;
  reg q24;
  wire [12:0] s2;
  wire n26;
  reg q26;
  wire [3:0] s3;
  wire n28;
  reg q28;
  wire n29;
  reg q29;
  wire n30;
  wire n31;
  wire n32;
  wire n33;
  wire n34;
  reg q34;
  wire n35;
  wire n36;
  wire n37;
  wire n38;
  reg q38;
  wire n39;
  reg q39;
  wire n40;
  wire n41;
  reg q41;
  wire n42;
  reg q42;
  wire n43;
  reg q43;
  wire n44;
  wire [7:0] s4;
  wire n46;
  reg q46;
  wire n47;
  wire n48;
  reg q48;
  wire n49;
  reg q49;
  wire n50;
  wire n51;
  reg q51;
  wire n52;
  reg q52;
  wire n53;
  reg q53;
  wire n54;
  assign n0 = 16'h8625 >> {i2, i6, i7, i2};
  assign n1 = 16'h361a >> {n0, n0, i11, n0};
  assign n2 = 16'h25e6 >> {i9, i4, i0, i11};
  assign n3 = 16'hb5c5 >> {i3, i11, i0, i6};
  assign n4 = 16'ha6f1 >> {n1, i11, i6, i0};
  assign n5 = 16'hf66f >> {q4, i2, i7, i3};
  assign n6 = 16'hcc19 >> {i10, i8, i0, i10};
  assign n7 = 16'h3296 >> {i3, n6, i11, i9};
  assign s0 = {1'b0, i2, i0, i9, i9, n6, n7, i7, i7, q2, i4} - {1'b0, i0, i2, i5, i8, q2, n6, n1, i6, i0, i6};
  assign n9 = 16'h639c >> {i3, n6, s0[2], q2};
  assign n10 = 16'h42ff >> {i3, n0, n7, n3};
  assign s1 = {1'b0, q2, s0[3], i0, i4, i1, q2, i11} + {1'b0, i1, i11, q9, i0, s0[1], q4, s0[6]};
  assign n12 = 16'h22e5 >> {s0[9], i3, i1, i1};
  assign n13 = 16'h8009 >> {i2, s1[1], i4, i6};
  assign n14 = 16'h7e96 >> {q2, i8, n1, s1[1]};
  assign n15 = 16'h3d4d >> {i8, s0[0], n14, s0[9]};
  assign n16 = 16'h9330 >> {i11, n5, q4, s0[5]};
  assign n17 = 16'h1226 >> {s1[6], n5, i7, s1[7]};
  assign n18 = 16'h3f14 >> {i5, s1[3], s0[4], i8};
  assign n19 = 16'h275c >> {i6, q9, i8, s0[10]};
  assign n20 = 16'h1a69 >> {n19, i9, n3, i8};
  assign n21 = 16'hfff4 >> {s1[3], i10, n5, n18};
  assign n22 = 16'h9fa9 >> {i7, s1[5], i3, s0[8]};
  assign n23 = 16'h7e73 >> {s0[1], i7, q22, n12};
  assign n24 = 16'h2634 >> {n6, q22, n0, s0[2]};
  assign s2 = {1'b0, q15, n18, n5, q23, n12, s0[0], s0[10], i6, i5, s0[9], i9, n6} + {1'b0, n18, s1[2], s0[4], s0[7], i8, n7, q23, s1[2], q22, q9, q24, s0[1]};
  assign n26 = 16'hdf78 >> {i9, n5, i10, s2[1]};
  assign s3 = {1'b0, s1[1], i4, q9} + {1'b0, i7, q15, s2[8]};
  assign n28 = 16'h51b7 >> {n7, q2, s0[7], q4};
  assign n29 = 16'h8200 >> {s2[0], n13, s3[3], s1[3]};
  assign n30 = 16'h222d >> {q23, q15, q22, n19};
  assign n31 = 16'h128a >> {s1[0], s2[10], s2[9], s2[0]};
  assign n32 = 16'h0c09 >> {q26, s2[9], q29, s2[10]};
  assign n33 = 16'h033a >> {s2[6], n30, s2[12], n32};
  assign n34 = 16'had54 >> {n19, n7, n14, s1[5]};
  assign n35 = 16'h6993 >> {n18, s2[5], s0[7], s2[4]};
  assign n36 = 16'hd3a4 >> {q29, n30, n32, q22};
  assign n37 = 16'h405d >> {n36, s1[3], n32, s1[4]};
  assign n38 = 16'h9f3a >> {n32, n37, q24, n18};
  assign n39 = 16'h225b >> {s0[9], s1[1], s0[4], n36};
  assign n40 = 16'hacbf >> {q28, s2[1], q28, n35};
  assign n41 = 16'h734e >> {n19, s0[10], s2[11], s0[2]};
  assign n42 = 16'h857c >> {s1[0], n21, s2[11], s1[1]};
  assign n43 = 16'h05a0 >> {s1[3], s1[4], n32, n13};
  assign n44 = 16'h6101 >> {n32, s1[3], s1[1], q29};
  assign s4 = {1'b0, s2[10], n21, q41, s2[6], q9, i11, i5} - {1'b0, s1[0], i6, n6, q26, s2[7], i6, q26};
  assign n46 = 16'h4df3 >> {n35, s3[2], s2[5], n17};
  assign n47 = 16'h0400 >> {s4[7], q28, s4[2], n17};
  assign n48 = 16'h9c02 >> {n35, n33, q29, s4[0]};
  assign n49 = 16'h1ecc >> {q24, s2[5], n13, s2[3]};
  assign n50 = 16'hc924 >> {s2[2], s2[2], s2[5], n37};
  assign n51 = 16'h064c >> {q15, n50, q22, n37};
  assign n52 = 16'h9f9c >> {n19, q29, s4[0], s3[0]};
  assign n53 = 16'h6560 >> {s1[5], q52, q41, q39};
  assign n54 = 16'h49e8 >> {q23, q28, s4[6], n47};
  always @(negedge clk0 or posedge i0) begin if (i0) q2 <= 1'b1; else begin q2 <= n2; end end
  always @(posedge clk1) begin q4 <= n4; end
  always @(posedge clk1 or posedge i7) begin if (i7) q9 <= 1'b0; else begin if (s0[1]) q9 <= 1'b0; else q9 <= n9; end end
  always @(posedge clk0 or posedge n10) begin if (n10) q15 <= 1'b1; else begin if (n13) begin q15 <= n15; end end end
  always @(posedge clk1 or posedge n0) begin if (n0) q20 <= 1'b1; else begin if (n10) begin if (s0[8]) q20 <= 1'b0; else q20 <= n20; end end end
  always @(posedge clk1) begin if (s1[1]) q22 <= 1'b0; else if (n3) q22 <= s0[0]; else q22 <= n22; end
  always @(posedge clk1) begin if (s0[10]) q23 <= 1'b0; else q23 <= n23; end
  always @(posedge clk0) begin q24 <= n24; end
  always @(posedge clk0 or posedge s2[6]) begin if (s2[6]) q26 <= 1'b1; else begin if (s0[1]) q26 <= i11; else q26 <= n26; end end
  always @(posedge clk1 or posedge s2[2]) begin if (s2[2]) q28 <= 1'b0; else begin q28 <= n28; end end
  always @(posedge clk1 or posedge s2[6]) begin if (s2[6]) q29 <= 1'b0; else begin if (s2[9]) begin q29 <= n29; end end end
  always @(posedge clk1 or posedge s0[7]) begin if (s0[7]) q34 <= 1'b0; else begin if (q22) begin q34 <= n34; end end end
  always @(posedge clk0) begin if (s2[7]) q38 <= q22; else q38 <= n38; end
  always @(posedge clk1) begin if (q20) q39 <= 1'b0; else q39 <= n39; end
  always @(posedge clk1) begin if (q24) begin q41 <= n41; end end
  always @(posedge clk1) begin q42 <= n42; end
  always @(negedge clk0) begin q43 <= n43; end
  always @(posedge clk0 or posedge n16) begin if (n16) q46 <= 1'b0; else begin if (n21) q46 <= n14; else q46 <= n46; end end
  always @(posedge clk0) begin if (n37) q48 <= s0[10]; else q48 <= n48; end
  always @(posedge clk1) begin if (s2[9]) q49 <= q34; else q49 <= n49; end
  always @(posedge clk1 or posedge n3) begin if (n3) q51 <= 1'b0; else begin q51 <= n51; end end
  always @(negedge clk1) begin q52 <= n52; end
  always @(posedge clk0) begin q53 <= n53; end
  assign o0 = ~(^{s2[6], n13, s2[7], s2[12], s2[11], q23, n30, n33, s1[3], s4[6], s1[6], s3[3], n35, n1, n36, s2[0], s4[4], q20, s1[7]});
  assign o1 = (^{s1[1], s3[2], n17, n54, n37, s2[8], q51, n10, n44, q52, q39, q28, n3, n32, s2[1], s1[5], s0[10], n5, s4[5]});
  assign o2 = (^{n16, q34, n12, q38, q4, s0[2], s2[4], s3[1], n18, s0[5], q41, q29, q26, q46, s4[0], q53, s2[3], s4[2], s4[1]});
  assign o3 = (^{s0[9], s0[0], n47, s0[6], n40, s2[5], q42, s0[4], n6, s1[0], q22, n7, n21, q9, n0, q43, q48, s2[10], q2});
  assign o4 = (^{n19, n14, s0[3], n50, q15, s0[1], s1[4], q49, s1[2], q24, n31, s3[0], s0[8], s2[2], s2[9], s4[7], s4[3], s0[7]});
endmodule
