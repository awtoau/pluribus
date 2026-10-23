module top (input [3:0] a, output [3:0] y);
  for (genvar i = 0; i < 4; i++) begin : g
    assign y[i] = ~a[i];
  end
endmodule
