module top (clk, a, b, y);
  input clk;
  input [7:0] a;
  input [7:0] b;
  output [8:0] y;
  reg [8:0] y;
  wire [4:0] c;
  wire [9:0] s;
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(a[0]), .B0(b[0]), .C0(1'b0), .D0(1'b1), .A1(a[1]), .B1(b[1]), .C1(1'b0), .D1(1'b1), .CIN(1'b0), .S0(s[0]), .S1(s[1]), .COUT(c[1]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(a[2]), .B0(b[2]), .C0(1'b0), .D0(1'b1), .A1(a[3]), .B1(b[3]), .C1(1'b0), .D1(1'b1), .CIN(c[1]), .S0(s[2]), .S1(s[3]), .COUT(c[2]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u2 (.A0(a[4]), .B0(b[4]), .C0(1'b0), .D0(1'b1), .A1(a[5]), .B1(b[5]), .C1(1'b0), .D1(1'b1), .CIN(c[2]), .S0(s[4]), .S1(s[5]), .COUT(c[3]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u3 (.A0(a[6]), .B0(b[6]), .C0(1'b0), .D0(1'b1), .A1(a[7]), .B1(b[7]), .C1(1'b0), .D1(1'b1), .CIN(c[3]), .S0(s[6]), .S1(s[7]), .COUT(c[4]));
  always @(posedge clk) y <= {c[4], s[7:0]};
endmodule
