module top (clk, en, q);
  input clk;
  input en;
  output q;
  reg q;
  wire [1:0] c;
  wire [1:0] s;
  CCU2D #(.INIT0(16'h96AA), .INIT1(16'h96AA), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(q[0]), .B0(1'b0), .C0(1'b0), .D0(1'b1), .A1(1'b0), .B1(1'b0), .C1(1'b0), .D1(1'b1), .CIN(1'b1), .S0(s[0]), .S1(s[1]), .COUT(c[1]));
  always @(posedge clk) if (en) q <= s[0:0];
endmodule
