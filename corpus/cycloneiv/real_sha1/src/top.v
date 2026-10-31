module top(input clk, input rst, input [2:0] cmd_i, input cmd_w_i, output [3:0] cmd_o,
                   output [31:0] text_o);
  reg [31:0] text_i;
  always @(posedge clk) text_i <= text_i + 32'd1;   // free-running, not constant: keeps the datapath live
  sha1 u_core(.clk_i(clk), .rst_i(rst), .text_i(text_i), .text_o(text_o), .cmd_i(cmd_i), .cmd_w_i(cmd_w_i), .cmd_o(cmd_o));
endmodule
