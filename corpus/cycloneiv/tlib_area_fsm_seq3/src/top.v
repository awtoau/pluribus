module top(input clk, input rst, input go, output [1:0] q);
  reg [1:0] st;
  always @(posedge clk)
    if (rst) st <= 2'd0;
    else case (st)
      2'd0: st <= go ? 2'd1 : 2'd0;
      2'd1: st <= 2'd2;
      2'd2: st <= 2'd0;
      default: st <= 2'd0;
    endcase
  assign q = st;
endmodule
