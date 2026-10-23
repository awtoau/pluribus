module counter_en_aclr(input clk, input rst_n, input en, output reg [3:0] q, output y);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) q <= 4'd0;
    else if (en) q <= q + 4'd1;
  assign y = &q;
endmodule
