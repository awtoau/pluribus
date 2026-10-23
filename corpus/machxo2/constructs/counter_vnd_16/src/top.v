module top (clk, en, q);
  input [0:0] clk;
  input [0:0] en;
  output [15:0] q;
  reg [15:0] q;
  wire [9:0] c;
  wire [18:0] s;
  wire nc0;
  CCU2D #(.INIT0(16'hF000), .INIT1(16'h0555), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(1'b0), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[0]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .COUT(c[1]), .S0(nc0), .S1(s[0]));
  CCU2D #(.INIT0(16'hFAAA), .INIT1(16'hFAAA), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(q[1]), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[2]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[1]), .COUT(c[2]), .S0(s[1]), .S1(s[2]));
  CCU2D #(.INIT0(16'hFAAA), .INIT1(16'hFAAA), .INJECT1_0("NO"), .INJECT1_1("NO")) u2 (.A0(q[3]), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[4]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[2]), .COUT(c[3]), .S0(s[3]), .S1(s[4]));
  CCU2D #(.INIT0(16'hFAAA), .INIT1(16'hFAAA), .INJECT1_0("NO"), .INJECT1_1("NO")) u3 (.A0(q[5]), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[6]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[3]), .COUT(c[4]), .S0(s[5]), .S1(s[6]));
  CCU2D #(.INIT0(16'hFAAA), .INIT1(16'hFAAA), .INJECT1_0("NO"), .INJECT1_1("NO")) u4 (.A0(q[7]), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[8]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[4]), .COUT(c[5]), .S0(s[7]), .S1(s[8]));
  CCU2D #(.INIT0(16'hFAAA), .INIT1(16'hFAAA), .INJECT1_0("NO"), .INJECT1_1("NO")) u5 (.A0(q[9]), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[10]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[5]), .COUT(c[6]), .S0(s[9]), .S1(s[10]));
  CCU2D #(.INIT0(16'hFAAA), .INIT1(16'hFAAA), .INJECT1_0("NO"), .INJECT1_1("NO")) u6 (.A0(q[11]), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[12]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[6]), .COUT(c[7]), .S0(s[11]), .S1(s[12]));
  CCU2D #(.INIT0(16'hFAAA), .INIT1(16'hFAAA), .INJECT1_0("NO"), .INJECT1_1("NO")) u7 (.A0(q[13]), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[14]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[7]), .COUT(c[8]), .S0(s[13]), .S1(s[14]));
  CCU2D #(.INIT0(16'hFAAA), .INIT1(16'hFAAA), .INJECT1_0("NO"), .INJECT1_1("NO")) u8 (.A0(q[15]), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(1'b0), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[8]), .COUT(c[9]), .S0(s[15]), .S1(s[16]));
  always @(posedge clk) if (en) q <= s[15:0];
endmodule
