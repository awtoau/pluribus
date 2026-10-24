module top (input clk, input d, output reg q);
  parameter P = 1;
  generate if (P) begin : g
    always @(posedge clk) q <= d;
  end else begin : h
    always @(posedge clk) q <= ~d;
  end endgenerate
endmodule
