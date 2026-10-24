module top (input [1:0] s, input a, b, output reg y);
  always @* unique case (s)
    2'd0: y = a;
    default: y = b;
  endcase
endmodule
