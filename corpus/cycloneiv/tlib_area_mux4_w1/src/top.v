module top(input clk, input [1:0] sel, input a, input b, input c, input d, output q);
  reg r;
  always @(posedge clk) case (sel) 2'd0: r <= a; 2'd1: r <= b; 2'd2: r <= c; default: r <= d; endcase
  assign q = r;
endmodule
