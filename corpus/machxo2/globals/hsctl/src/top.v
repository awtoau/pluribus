module top (
    input wire clk,
    input wire rst,
    input wire ce,
    input wire arst,
    input wire d,
    output wire q
);
reg [149:0] ra, rb;
always @(posedge clk) if (rst) ra <= 0; else if (ce) ra <= {ra[148:0], d};
always @(posedge clk or posedge arst) if (arst) rb <= 0; else rb <= {rb[148:0], ra[149]};
reg qr; always @(posedge clk) qr <= rb[149];
assign q = qr;
endmodule
