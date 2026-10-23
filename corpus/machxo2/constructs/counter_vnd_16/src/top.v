module top (clk, en, q);
  input clk;
  input en;
  output [15:0] q;
  reg [15:0] q;
  wire [8:0] c;
  wire [15:0] s;
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(q[0]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[1]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(1'b1), .S0(s[0]), .S1(s[1]), .COUT(c[1]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(q[2]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[3]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[1]), .S0(s[2]), .S1(s[3]), .COUT(c[2]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u2 (.A0(q[4]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[5]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[2]), .S0(s[4]), .S1(s[5]), .COUT(c[3]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u3 (.A0(q[6]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[7]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[3]), .S0(s[6]), .S1(s[7]), .COUT(c[4]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u4 (.A0(q[8]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[9]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[4]), .S0(s[8]), .S1(s[9]), .COUT(c[5]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u5 (.A0(q[10]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[11]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[5]), .S0(s[10]), .S1(s[11]), .COUT(c[6]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u6 (.A0(q[12]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[13]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[6]), .S0(s[12]), .S1(s[13]), .COUT(c[7]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u7 (.A0(q[14]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[15]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[7]), .S0(s[14]), .S1(s[15]), .COUT(c[8]));
  always @(posedge clk) if (en) q <= s[15:0];
endmodule
