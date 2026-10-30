module top (
  input clk,
  output y
);
reg [6:0] ad3;
(* romstyle = "M9K", ram_init_file = "../src/rom1.mif" *) reg [31:0] rom1 [0:127];
reg [31:0] rq2;
reg y_q;
always @(posedge clk) ad3 <= ad3 + 7'd1;
always @(posedge clk) rq2 <= rom1[ad3];
always @(posedge clk) y_q <= (^rq2);
assign y = y_q;
endmodule
