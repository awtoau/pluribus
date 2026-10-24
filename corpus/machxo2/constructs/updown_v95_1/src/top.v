module top (clk, up, q);
  input clk;
  input up;
  output q;
  reg q;
  always @(posedge clk) begin
    if (up) q <= q + 1;
    else q <= q - 1;
  end
endmodule
