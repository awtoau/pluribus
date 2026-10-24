module top (clk, en, q);
  input [0:0] clk;
  input [0:0] en;
  output [0:0] q;
  reg [0:0] q;
  wire [1:0] c;
  wire [2:0] s;
  wire nc0;
  CCU2D #(.INIT0(16'hF000), .INIT1(16'h0555), .INJECT1_0("NO"), .INJECT1_1("NO")) u0 (.A0(1'b0), .B0(1'b0), .C0(1'b0), .D0(1'b0), .A1(q[0]), .B1(1'b0), .C1(1'b0), .D1(1'b0), .COUT(c[1]), .S0(nc0), .S1(s[0]));
  always @(posedge clk) if (en) q <= s[0:0];
endmodule
