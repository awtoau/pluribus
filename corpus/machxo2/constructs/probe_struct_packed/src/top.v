module top (input clk, input [1:0] d, output reg q);
  typedef struct packed { logic a; logic b; } s_t;
  s_t s;
  always @(posedge clk) begin s <= d; q <= s.a; end
endmodule
