// 16 x 4-bit registers: one shared enable, one shared sync clear, 4-bit write address.
module regbank16(input clk, input en, input clr, input [3:0] waddr, input [3:0] wdata,
                 input [3:0] raddr, output [3:0] rdata);
  reg [3:0] r [0:15];
  integer i;
  always @(posedge clk)
    for (i = 0; i < 16; i = i + 1)
      if (clr) r[i] <= 4'd0;
      else if (en && waddr == i) r[i] <= wdata;
  assign rdata = r[raddr];
endmodule
