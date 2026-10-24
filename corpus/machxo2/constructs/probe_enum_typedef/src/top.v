module top (input clk, input go, output reg q);
  typedef enum reg [1:0] {A=0, B=1, C=2} st_t;
  st_t st;
  always @(posedge clk) begin if (go) st <= B; q <= (st == B); end
endmodule
