module top(input clk, input rst, input cond, output q);
  reg st;
  always @(posedge clk)
    if (rst) st <= 1'b0;
    else if (cond) st <= ~st;
  assign q = st;
endmodule
