module top (clk, up, q);
  input clk;
  input up;
  output [15:0] q;
  reg [15:0] q;
  always @(posedge clk) begin
    if (up) q <= q + 1;
    else q <= q - 1;
  end
endmodule
