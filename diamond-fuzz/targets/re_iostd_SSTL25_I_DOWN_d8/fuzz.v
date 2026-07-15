module fuzz(input wire clk,output wire d);
 reg t; always @(posedge clk) t<=~t; assign d=t;
endmodule
