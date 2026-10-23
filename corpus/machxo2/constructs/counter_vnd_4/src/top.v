module top (clk, en, q);
  input clk;
  input en;
  output [3:0] q;
  reg [3:0] q;
  wire [2:0] c;
  wire [3:0] s;
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(q[0]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[1]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(1'b1), .S0(s[0]), .S1(s[1]), .COUT(c[1]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(q[2]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(q[3]), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(c[1]), .S0(s[2]), .S1(s[3]), .COUT(c[2]));
  always @(posedge clk) if (en) q <= s[3:0];
endmodule
