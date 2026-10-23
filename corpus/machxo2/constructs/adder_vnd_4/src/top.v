module top (clk, a, b, y);
  input clk;
  input [3:0] a;
  input [3:0] b;
  output [4:0] y;
  reg [4:0] y;
  wire [2:0] c;
  wire [5:0] s;
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(a[0]), .B0(b[0]), .C0(1'b0), .D0(1'b1), .A1(a[1]), .B1(b[1]), .C1(1'b0), .D1(1'b1), .CIN(1'b0), .S0(s[0]), .S1(s[1]), .COUT(c[1]));
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(a[2]), .B0(b[2]), .C0(1'b0), .D0(1'b1), .A1(a[3]), .B1(b[3]), .C1(1'b0), .D1(1'b1), .CIN(c[1]), .S0(s[2]), .S1(s[3]), .COUT(c[2]));
  always @(posedge clk) y <= {c[2], s[3:0]};
endmodule
