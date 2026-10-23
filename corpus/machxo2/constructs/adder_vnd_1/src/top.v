module top (clk, a, b, y);
  input clk;
  input a;
  input b;
  output [1:0] y;
  reg [1:0] y;
  wire [1:0] c;
  wire [3:0] s;
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(a[0]), .B0(b[0]), .C0(1'b0), .D0(1'b1), .A1(1'b0), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(1'b0), .S0(s[0]), .S1(s[1]), .COUT(c[1]));
  always @(posedge clk) y <= {c[1], s[0:0]};
endmodule
