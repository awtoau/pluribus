module top (clk, a, b, y);
  input [0:0] clk;
  input [3:0] a;
  input [3:0] b;
  output [4:0] y;
  reg [4:0] y;
  wire [3:0] c;
  wire [7:0] s;
  wire nc0;
  CCU2D #(.INIT0(16'h0000), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(1'b0), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(a[0]), .B1(b[0]), .C1(1'b0), .D1(1'b0), .COUT(c[1]), .S0(nc0), .S1(s[0]));
  CCU2D #(.INIT0(16'h5999), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u1 (.A0(a[1]), .B0(b[1]), .C0(1'b0), .D0(1'b0), .A1(a[2]), .B1(b[2]), .C1(1'b0), .D1(1'b0), .CIN(c[1]), .COUT(c[2]), .S0(s[1]), .S1(s[2]));
  CCU2D #(.INIT0(16'h5999), .INIT1(16'h5999), .INJECT1_0("NO"), .INJECT1_1("NO")) u2 (.A0(a[3]), .B0(b[3]), .C0(1'b0), .D0(1'b0), .A1(1'b0), .B1(1'b0), .C1(1'b0), .D1(1'b0), .CIN(c[2]), .COUT(c[3]), .S0(s[3]), .S1(s[4]));
  always @(posedge clk) y <= s[4:0];
endmodule
