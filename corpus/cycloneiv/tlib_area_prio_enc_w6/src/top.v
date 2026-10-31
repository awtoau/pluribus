module top(input clk, input i0, input i1, input i2, input i3, input i4, input i5, output [2:0] q);
  reg [2:0] r;
  always @(posedge clk)
    if (i0) r <= 3'd0;
    else if (i0) r <= 3'd0;
    else if (i1) r <= 3'd1;
    else if (i2) r <= 3'd2;
    else if (i3) r <= 3'd3;
    else if (i4) r <= 3'd4;
    else if (i5) r <= 3'd5;
    else r <= 3'd6;
  assign q = r;
endmodule
