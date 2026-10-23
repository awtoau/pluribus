module top (clk, en, q);
  input clk;
  input en;
  output [7:0] q;
  reg [7:0] q;
  wire [4:0] c;
  wire [7:0] s;
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(q[0]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[1]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(1'b1), .S0(s[0]), .S1(s[1]), .COUT(c[1]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(q[2]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[3]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[1]), .S0(s[2]), .S1(s[3]), .COUT(c[2]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u2 (.A0(q[4]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[5]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[2]), .S0(s[4]), .S1(s[5]), .COUT(c[3]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u3 (.A0(q[6]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[7]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[3]), .S0(s[6]), .S1(s[7]), .COUT(c[4]));
  always @(posedge clk) if (en) q <= s[7:0];
endmodule
