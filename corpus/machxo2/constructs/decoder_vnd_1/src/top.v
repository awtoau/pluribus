module top (clk, en, s, y);
  input [0:0] clk;
  input [0:0] en;
  input [0:0] s;
  output [1:0] y;
  reg [1:0] y;
  wire [1:0] z;
  LUT4 #(.init(16'h5500)) l0 (.A(s[0]), .B(1'b0), .C(1'b0), .D(en), .Z(z[0]));
  LUT4 #(.init(16'hAA00)) l1 (.A(s[0]), .B(1'b0), .C(1'b0), .D(en), .Z(z[1]));
  always @(posedge clk) y <= z;
endmodule
