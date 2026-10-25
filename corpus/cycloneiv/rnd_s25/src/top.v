module top(input clk0, input clk1, input i0, input i1, input i2, input i3, input i4, input i5, input i6, input i7, input i8, output o0, output o1, output o2, output o3, output o4, output o5, output o6, output o7, output o8, output o9);
  wire n0;
  wire n1;
  reg q1;
  wire n2;
  wire n3;
  wire n4;
  wire [11:0] s0;
  wire n6;
  wire n7;
  reg q7;
  wire [9:0] s1;
  wire n9;
  wire [4:0] s2;
  wire n11;
  wire [9:0] s3;
  wire n13;
  reg q13;
  wire n14;
  reg q14;
  wire [9:0] s4;
  wire n16;
  wire n17;
  reg q17;
  wire [5:0] s5;
  wire n19;
  wire n20;
  wire n21;
  reg q21;
  wire n22;
  wire n23;
  wire n24;
  reg q24;
  wire n25;
  reg q25;
  wire n26;
  reg q26;
  wire [7:0] s6;
  wire [10:0] s7;
  wire [10:0] s8;
  wire n30;
  wire n31;
  wire n32;
  reg q32;
  wire n33;
  wire n34;
  reg q34;
  assign n0 = 16'h1fd7 >> {i6, i0, i4, i7};
  assign n1 = 16'h62c5 >> {i4, i6, i4, n0};
  assign n2 = 16'hafa8 >> {i5, i7, n0, i4};
  assign n3 = 16'hd074 >> {i2, q1, i4, i5};
  assign n4 = 16'hd004 >> {n2, i3, n0, i5};
  assign s0 = {1'b0, n0, n0, q1, i2, q1, i5, i3, n2, i4, n4, i4} - {1'b0, i0, i3, i4, i0, n0, i3, i5, i3, i3, i4, i7};
  assign n6 = 16'ha131 >> {q1, i4, i6, s0[10]};
  assign n7 = 16'h72b6 >> {s0[3], n4, s0[1], s0[10]};
  assign s1 = {1'b0, s0[9], s0[7], i8, n2, i3, s0[9], i4, s0[6], s0[10]} + {1'b0, s0[10], s0[9], i5, i2, n0, s0[10], s0[9], n3, s0[10]};
  assign n9 = 16'h93f2 >> {i7, i5, s0[6], s0[9]};
  assign s2 = {1'b0, s0[6], s1[3], s0[3], s0[10]} - {1'b0, i7, i6, s1[1], s0[10]};
  assign n11 = 16'h95fe >> {s1[6], i5, s1[4], s1[6]};
  assign s3 = {1'b0, i3, s0[6], s1[7], s2[2], s0[5], q1, n11, s0[5], s1[5]} - {1'b0, i5, i4, n3, s2[2], n9, n4, n2, s0[6], n2};
  assign n13 = 16'h3acd >> {i4, i8, n2, s1[0]};
  assign n14 = 16'h6ae2 >> {s3[6], s3[9], s0[0], s3[7]};
  assign s4 = {1'b0, s0[6], s1[8], s0[11], n2, s0[0], s1[5], s3[0], s1[7], i1} - {1'b0, s3[6], s0[10], s1[1], i3, s1[0], s3[7], i4, s0[10], s1[4]};
  assign n16 = 16'h7062 >> {s3[8], s0[1], s1[1], s3[1]};
  assign n17 = 16'h8566 >> {n3, s0[8], n11, s3[4]};
  assign s5 = {1'b0, s1[1], s0[3], s0[2], s2[3], s0[6]} + {1'b0, s0[9], s0[0], s0[9], s1[1], s3[1]};
  assign n19 = 16'h3afd >> {s4[2], s2[0], s3[5], s4[3]};
  assign n20 = 16'hd598 >> {s1[8], s3[6], q17, n16};
  assign n21 = 16'h44bd >> {s3[9], s1[5], s5[1], s0[7]};
  assign n22 = 16'hb916 >> {s1[7], s4[6], s5[2], s2[2]};
  assign n23 = 16'hbf34 >> {s0[7], s3[4], s0[7], q13};
  assign n24 = 16'h18b4 >> {s3[8], s0[3], s2[3], s2[3]};
  assign n25 = 16'h153e >> {s3[8], n20, s0[8], q13};
  assign n26 = 16'hd15b >> {n6, s1[7], q24, n6};
  assign s6 = {1'b0, s1[5], s1[0], s1[6], s0[7], n2, i5, s1[8]} - {1'b0, q13, s5[0], s3[0], s0[10], s4[2], s2[3], n6};
  assign s7 = {1'b0, s4[5], n23, n19, s4[3], n16, s2[2], s3[0], s1[4], s3[3], i2} - {1'b0, s6[0], n3, s6[3], s0[0], n16, s0[4], s0[2], s1[2], q25, n23};
  assign s8 = {1'b0, n20, q17, i4, s0[4], i4, n4, s4[5], n20, s2[0], s6[4]} + {1'b0, s3[1], s0[2], q26, q21, q17, s4[5], i5, s1[1], s0[9], s0[8]};
  assign n30 = 16'h1aee >> {s8[7], s6[5], s5[0], s6[6]};
  assign n31 = 16'hea74 >> {s6[1], s0[11], s8[0], s6[7]};
  assign n32 = 16'hd085 >> {s6[1], i6, s1[1], n22};
  assign n33 = 16'h537c >> {s3[4], s5[4], s6[5], s4[0]};
  assign n34 = 16'ha8ee >> {s7[10], s7[5], s8[6], s4[8]};
  always @(posedge clk0 or posedge i6) begin if (i6) q1 <= 1'b1; else begin if (i6) q1 <= 1'b0; else q1 <= n1; end end
  always @(negedge clk1) begin q7 <= n7; end
  always @(posedge clk0) begin if (s0[1]) q13 <= s3[0]; else q13 <= n13; end
  always @(negedge clk0) begin q14 <= n14; end
  always @(posedge clk1) begin if (s0[5]) begin q17 <= n17; end end
  always @(posedge clk1) begin if (s3[7]) begin if (s4[1]) q21 <= s5[4]; else q21 <= n21; end end
  always @(negedge clk0) begin if (n22) q24 <= s3[6]; else q24 <= n24; end
  always @(posedge clk1 or posedge q7) begin if (q7) q25 <= 1'b0; else begin if (s3[0]) begin if (i8) q25 <= s5[2]; else q25 <= n25; end end end
  always @(posedge clk0) begin if (q25) q26 <= q24; else q26 <= n26; end
  always @(posedge clk0) begin q32 <= n32; end
  always @(posedge clk1) begin if (i5) begin if (s6[3]) q34 <= 1'b0; else if (n16) q34 <= n3; else q34 <= n34; end end
  assign o0 = (^{s8[6], q13, q21, s3[0], s8[1], s0[9], s2[2], q26, s3[7], s8[3], n22});
  assign o1 = (^{s0[0], n0, s6[0], s7[2], s6[6], s0[8], s7[1], n4, s3[6], s1[8], s7[0]});
  assign o2 = (^{q1, s2[3], s0[11], s8[9], s6[3], q34, s8[2], n6, s3[4], s4[3], s8[8]});
  assign o3 = (^{q32, s1[7], s7[4], s6[4], s4[2], s4[1], s6[2], s6[5], s6[1], s7[3], s1[1]});
  assign o4 = (^{s7[7], s0[6], s0[5], s0[1], n19, s5[0], q14, s1[9], n2, s0[2], q7});
  assign o5 = (^{s5[5], s7[10], s5[4], s0[4], q24, s0[10], s8[7], n16, s2[4], s7[5], s3[8]});
  assign o6 = ~(^{q17, s4[9], s5[1], s0[3], s1[4], s3[2], n23, s3[9], s7[9], n3, s4[6]});
  assign o7 = (^{s1[6], q25, s5[2], s8[0], s2[0], n30, s8[5], s4[5], s4[0], s3[3], s1[0]});
  assign o8 = (^{s1[2], s6[7], s3[5], n20, s3[1], s7[8], s8[4], s8[10], s1[5], n9, s4[4]});
  assign o9 = ~(^{s7[6], s0[7], s2[1], s5[3], n33, s4[7], s1[3], s4[8], n31, n11});
endmodule
