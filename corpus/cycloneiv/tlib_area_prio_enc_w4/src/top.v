module top(input clk, input i0, input i1, input i2, input i3, output [1:0] q);
  reg [1:0] r;
  always @(posedge clk)
    if (i0) r <= 2'd0;
    else if (i0) r <= 2'd0;
    else if (i1) r <= 2'd1;
    else if (i2) r <= 2'd2;
    else if (i3) r <= 2'd3;
    else r <= 2'd4;
  assign q = r;
endmodule
