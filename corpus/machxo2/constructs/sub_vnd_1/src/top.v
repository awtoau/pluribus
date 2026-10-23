module top (clk, a, b, y);
  input [0:0] clk;
  input [0:0] a;
  input [0:0] b;
  output [1:0] y;
  reg [1:0] y;
  wire [2:0] c;
  wire [5:0] s;
  wire nc0;
  CCU2D #(.INIT0(16'h0000), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(1'b0), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(a[0]), .B1(b[0]), .C1(1'b0), .D1(1'b0), .COUT(c[1]), .S0(nc0), .S1(s[0]));
  CCU2D #(.INIT0(16'h5999), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(1'b0), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(1'b0), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[1]), .COUT(c[2]), .S0(s[1]), .S1(s[2]));
  always @(posedge clk) y <= s[1:0];
endmodule
