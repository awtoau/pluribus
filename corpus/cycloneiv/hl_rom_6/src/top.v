module top (
  input clk,
  output y
);
reg [7:0] ad3;
(* romstyle = "M9K", ram_init_file = "../src/rom1.mif" *) reg [31:0] rom1 [0:255];
reg [31:0] rq2;
reg [8:0] ad6;
(* romstyle = "M9K", ram_init_file = "../src/rom4.mif" *) reg [7:0] rom4 [0:511];
reg [7:0] rq5;
reg [7:0] ad9;
(* romstyle = "M9K", ram_init_file = "../src/rom7.mif" *) reg [8:0] rom7 [0:255];
reg [8:0] rq8;
reg y_q;
always @(posedge clk) ad3 <= ad3 + 8'd1;
always @(posedge clk) rq2 <= rom1[ad3];
always @(posedge clk) ad6 <= ad6 + 9'd1;
always @(posedge clk) rq5 <= rom4[ad6];
always @(posedge clk) ad9 <= ad9 + 8'd1;
always @(posedge clk) rq8 <= rom7[ad9];
always @(posedge clk) y_q <= (^rq2) ^ (^rq5) ^ (^rq8);
assign y = y_q;
endmodule
